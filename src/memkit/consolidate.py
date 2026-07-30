"""Nightly consolidation: stage 4 of docs/06-roadmap.md.

Four jobs, in the order they run:

1. **Expire** facts whose `valid_until` has passed. Cheap, no model involved, and
   nothing else in the system enforces that column -- the read path does not filter
   on it, so until this pass exists a date-expired fact is retrieved as if current.
2. **Demote** facts that have not surfaced in `consolidate_stale_days`. A fact that
   is never retrieved is usually an extractor mistake; lowering its importance lets
   the ranking bury it without anyone deciding to delete it.
3. **Merge** near-duplicate clusters. This is the only step that costs money.
4. Report. Nothing is deleted, ever -- merged facts become `superseded` with
   `superseded_by` pointing at the survivor, so provenance survives.

Two deliberate deviations from the docs:

* **No Batch API.** docs/04-judge.md is right that Batch is half price, but at this
  corpus size a whole run is a handful of calls -- roughly $0.01 -- and Batch buys
  that discount with asynchronous polling. The complexity is not worth a cent.
* **Clustering is stricter than read-path dedup** (0.92 against 0.90) because the
  consequences differ in kind: dedup hides a duplicate from one answer, this
  rewrites the store. Measured on this corpus, 0.92 still catches a real duplicate
  pair at 0.9278 while leaving "Prefers pnpm" / "Prefers pytest" (0.7422) alone.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from typing import Any

from qdrant_client import QdrantClient

from . import mutate, prompts, providers, store, vectors
from .db import utcnow
from .embed import Embedder

logger = logging.getLogger(__name__)

# Facts are only ever compared within one owner and one type: docs/04-judge.md's
# rule, and it is what stops a preference merging with a project decision.
CLUSTER_KEY = ("owner_id", "type")

# A cluster larger than this is almost certainly the threshold being too low rather
# than eight genuine restatements of one fact. Log and skip rather than ask a model
# to merge a crowd.
MAX_CLUSTER = 6


@dataclass
class Merge:
    """One proposed or applied merge."""

    ids: list[str]
    type: str
    texts: list[str]
    text: str | None = None
    importance: float | None = None
    reason: str = ""
    survivor_id: str | None = None
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "ids": self.ids,
            "type": self.type,
            "texts": self.texts,
            "merged_text": self.text,
            "importance": self.importance,
            "reason": self.reason,
            "survivor_id": self.survivor_id,
            "error": self.error,
        }


@dataclass
class Outcome:
    expired: int = 0
    demoted: int = 0
    clusters: int = 0
    merged: int = 0
    declined: int = 0
    superseded: int = 0
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    merges: list[Merge] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "expired": self.expired,
            "demoted": self.demoted,
            "clusters": self.clusters,
            "merged": self.merged,
            "declined": self.declined,
            "superseded": self.superseded,
            "cost_usd": round(self.cost_usd, 6),
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "merges": [m.as_dict() for m in self.merges],
            "errors": self.errors,
        }


# --------------------------------------------------------------------------
# 1. Expiry
# --------------------------------------------------------------------------

def expire_by_validity(conn: sqlite3.Connection, *, owner_id: str) -> list[str]:
    """Ids of active facts whose `valid_until` has passed.

    Compared against an ISO-with-Z stamp rather than `datetime('now')`: these
    columns store "2026-07-29T00:00:00Z" and are compared lexicographically, so at
    offset 10 a literal 'T' sorts above the space `datetime('now')` produces and a
    same-day expiry reads as still valid.
    """
    rows = conn.execute(
        """SELECT id FROM memories
            WHERE owner_id = ? AND status = 'active'
              AND valid_until IS NOT NULL
              AND valid_until <= strftime('%Y-%m-%dT%H:%M:%SZ','now')""",
        (owner_id,),
    ).fetchall()
    return [row["id"] for row in rows]


# --------------------------------------------------------------------------
# 2. Demotion
# --------------------------------------------------------------------------

def stale_facts(
    conn: sqlite3.Connection, *, owner_id: str, days: int
) -> list[sqlite3.Row]:
    """Active facts that have not been retrieved in `days`.

    Never-retrieved facts count only once they are older than the window, so a fact
    extracted this morning is not demoted for having had no chance yet.
    """
    return conn.execute(
        """SELECT id, importance FROM memories
            WHERE owner_id = ? AND status = 'active' AND importance > 0
              AND (
                (last_retrieved_at IS NOT NULL
                 AND last_retrieved_at < strftime('%Y-%m-%dT%H:%M:%SZ','now',?))
                OR
                (last_retrieved_at IS NULL
                 AND created_at < strftime('%Y-%m-%dT%H:%M:%SZ','now',?))
              )""",
        (owner_id, f"-{days} days", f"-{days} days"),
    ).fetchall()


# --------------------------------------------------------------------------
# 3. Clustering
# --------------------------------------------------------------------------

def _neighbours(
    client: QdrantClient,
    *,
    vector: list[float],
    owner_id: str,
    type_: str,
    threshold: float,
    limit: int,
) -> list[str]:
    hits = vectors.search(
        client,
        vectors.MEMORIES,
        vector,
        limit=limit,
        must=[
            vectors.keyword("owner_id", owner_id),
            vectors.keyword("status", "active"),
            vectors.keyword("type", type_),
        ],
    )
    return [str(h.id) for h in hits if float(h.score) >= threshold]


def find_clusters(
    conn: sqlite3.Connection,
    client: QdrantClient,
    embedder: Embedder,
    *,
    owner_id: str,
    threshold: float,
    max_cluster: int = MAX_CLUSTER,
) -> list[list[sqlite3.Row]]:
    """Connected components of the "closer than threshold" graph, within owner+type.

    Union-find rather than a single pass: if A is close to B and B to C but A is not
    close to C, all three describe the same subject and belong in one cluster.
    Clusters of one are not clusters.
    """
    rows = conn.execute(
        """SELECT id, type, text, importance, updated_at FROM memories
            WHERE owner_id = ? AND status = 'active' ORDER BY id""",
        (owner_id,),
    ).fetchall()
    if len(rows) < 2:
        return []
    by_id = {row["id"]: row for row in rows}

    parent: dict[str, str] = {row["id"]: row["id"] for row in rows}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    vecs = embedder.encode([row["text"] for row in rows])
    for row, vec in zip(rows, vecs, strict=True):
        for other in _neighbours(
            client,
            vector=vec,
            owner_id=owner_id,
            type_=row["type"],
            threshold=threshold,
            limit=max_cluster + 1,
        ):
            if other != row["id"] and other in by_id:
                union(row["id"], other)

    groups: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        groups.setdefault(find(row["id"]), []).append(row)

    clusters = []
    for members in groups.values():
        if len(members) < 2:
            continue
        if len(members) > max_cluster:
            # Almost certainly the threshold, not fifteen restatements of one fact.
            logger.warning(
                "skipping cluster of %d (max %d) — check consolidate_cosine",
                len(members), max_cluster,
            )
            continue
        # Newest first: rule 1 of the merge prompt keeps the most recent state, and
        # showing it first is the cheapest way to help.
        clusters.append(sorted(members, key=lambda r: r["updated_at"], reverse=True))
    return clusters


# --------------------------------------------------------------------------
# 4. The run
# --------------------------------------------------------------------------

def _merge_cluster(
    cluster: list[sqlite3.Row],
    *,
    model: str,
    anthropic_api_key: str,
    gemini_api_key: str,
    project: str,
    location: str,
) -> tuple[Merge, providers.ProviderResult]:
    facts = [dict(row) for row in cluster]
    merge = Merge(
        ids=[f["id"] for f in facts],
        type=facts[0]["type"],
        texts=[f["text"] for f in facts],
    )
    result = providers.call_merge(
        model=model,
        prompt=prompts.render_consolidate(facts),
        anthropic_api_key=anthropic_api_key,
        gemini_api_key=gemini_api_key,
        project=project,
        location=location,
    )
    if result.error:
        merge.error = result.error
        return merge, result
    raw = result.raw or {}
    text = (raw.get("text") or "").strip() or None
    merge.text = text
    merge.reason = str(raw.get("reason") or "")
    try:
        merge.importance = min(1.0, max(0.0, float(raw.get("importance"))))
    except (TypeError, ValueError):
        merge.importance = max(float(f["importance"] or 0) for f in facts)
    return merge, result


def run(
    conn: sqlite3.Connection,
    client: QdrantClient,
    embedder: Embedder,
    *,
    owner_id: str,
    threshold: float,
    stale_days: int,
    demotion: float,
    model: str,
    monthly_limit_usd: float,
    anthropic_api_key: str = "",
    gemini_api_key: str = "",
    project: str = "",
    location: str = "",
    dry_run: bool = False,
) -> Outcome:
    """One consolidation pass. The caller owns the transaction and the Qdrant apply.

    Ordered so the expensive step sees the smallest possible store: expiring and
    demoting first means a fact that is already dead is never sent to the model.
    """
    from . import judge

    out = Outcome()

    expired_ids = expire_by_validity(conn, owner_id=owner_id)
    stale = stale_facts(conn, owner_id=owner_id, days=stale_days)
    out.expired = len(expired_ids)
    out.demoted = len(stale)

    if not dry_run:
        for memory_id in expired_ids:
            result = mutate.set_status(
                conn, client, embedder, memory_id=memory_id, status="expired"
            )
            result.apply_index(client)
        for row in stale:
            new_importance = round(max(0.0, float(row["importance"]) - demotion), 4)
            result = mutate.update_memory(
                conn, client, embedder,
                memory_id=row["id"], changes={"importance": new_importance},
            )
            result.apply_index(client)

    clusters = find_clusters(
        conn, client, embedder, owner_id=owner_id, threshold=threshold
    )
    out.clusters = len(clusters)

    spent = judge.month_spend_usd(conn)
    for cluster in clusters:
        if spent + out.cost_usd >= monthly_limit_usd:
            out.errors.append("monthly_cost_limit_reached")
            logger.error("consolidation paused: monthly limit reached")
            break
        if dry_run:
            out.merges.append(
                Merge(
                    ids=[r["id"] for r in cluster],
                    type=cluster[0]["type"],
                    texts=[r["text"] for r in cluster],
                )
            )
            continue

        merge, result = _merge_cluster(
            cluster, model=model, anthropic_api_key=anthropic_api_key,
            gemini_api_key=gemini_api_key, project=project, location=location,
        )
        out.input_tokens += result.input_tokens
        out.output_tokens += result.output_tokens
        cost = judge.cost_of(result.input_tokens, result.output_tokens, model=model)
        out.cost_usd += cost
        _log_run(conn, model=model, merge=merge, result=result, cost=cost)

        if merge.error:
            out.errors.append(merge.error)
            out.merges.append(merge)
            continue
        if not merge.text:
            # Rule 4 fired: these are different things. Leaving them alone is the
            # whole point of making null an easy answer.
            out.declined += 1
            out.merges.append(merge)
            continue

        survivor = cluster[0]
        merge.survivor_id = _apply_merge(
            conn, client, embedder, cluster=cluster, merge=merge, owner_id=owner_id
        )
        out.merged += 1
        out.superseded += len(cluster)
        out.merges.append(merge)
        logger.info(
            "merged %d %s facts into %s", len(cluster), survivor["type"],
            merge.survivor_id,
        )

    return out


def _apply_merge(
    conn: sqlite3.Connection,
    client: QdrantClient,
    embedder: Embedder,
    *,
    cluster: list[sqlite3.Row],
    merge: Merge,
    owner_id: str,
) -> str:
    """Write the merged fact, then supersede its inputs.

    Scope and agent are inherited from the newest member. Nothing is deleted:
    docs/04-judge.md's application rule is ADD the new one, mark the old ones
    `superseded` with `superseded_by` set, so the chain stays walkable.
    """
    newest = cluster[0]
    row = conn.execute(
        "SELECT scope, scope_key, agent_id, valid_until FROM memories WHERE id=?",
        (newest["id"],),
    ).fetchone()
    survivor_id = store.add_memory(
        conn,
        client,
        embedder,
        owner_id=owner_id,
        text=merge.text or newest["text"],
        type=newest["type"],
        scope=row["scope"],
        scope_key=row["scope_key"],
        agent_id=row["agent_id"],
        importance=merge.importance if merge.importance is not None else 0.6,
        extraction_version=f"consolidated:{prompts.CONSOLIDATE_VERSION}",
        valid_until=row["valid_until"],
    )
    # Provenance: the merged fact inherits every source message of its inputs, so
    # GET /v1/memories/{id}/sources still answers "where did this come from".
    conn.execute(
        f"""INSERT INTO memory_sources (memory_id, message_id)
            SELECT ?, message_id FROM memory_sources
             WHERE memory_id IN ({",".join("?" for _ in cluster)})
            ON CONFLICT DO NOTHING""",
        (survivor_id, *[r["id"] for r in cluster]),
    )
    for member in cluster:
        result = mutate.supersede(
            conn, client, memory_id=member["id"], by_id=survivor_id
        )
        result.apply_index(client)
    return survivor_id


def _log_run(
    conn: sqlite3.Connection,
    *,
    model: str,
    merge: Merge,
    result: providers.ProviderResult,
    cost: float,
) -> None:
    """Every consolidation call lands in `judge_runs` with kind='consolidate'.

    Same table as extraction on purpose: `GET /v1/admin/costs` groups by kind, and
    the docs promise a `by_kind` breakdown that only works if both write here.
    """
    import json

    conn.execute(
        """INSERT INTO judge_runs
           (kind, model, prompt_version, input_json, output_json, error,
            input_tokens, output_tokens, cost_usd, latency_ms, created_at)
           VALUES ('consolidate', ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)""",
        (
            model,
            prompts.CONSOLIDATE_VERSION,
            json.dumps({"ids": merge.ids, "texts": merge.texts}, ensure_ascii=False),
            json.dumps(result.raw, ensure_ascii=False) if result.raw else None,
            merge.error,
            result.input_tokens,
            result.output_tokens,
            cost,
            utcnow(),
        ),
    )
