"""Context-safe maintenance: exact-duplicate consolidation plus, when asked,
LLM-confirmed semantic merge of near-duplicate clusters (decisions/0056)."""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from . import jobs, provenance, store
from .db import transaction

logger = logging.getLogger(__name__)

# ADR 0032 chose connected components and stated a six-member cap; the cap was
# never implemented. It matters because a transitive chain at the threshold can
# link facts that are not pairwise similar, and the whole cluster is then
# serialised into a prompt whose answer must fit 200 characters. Oversized
# clusters are reported instead of merged, so nothing is silently rewritten.
MAX_CLUSTER_MEMBERS = 6


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def _connected_components(ids: list[str], edges: set[tuple[str, str]]) -> list[list[str]]:
    """Union-find over cosine edges — ADR 0032 chose connected components."""
    parent = {i: i for i in ids}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in edges:
        parent[find(a)] = find(b)
    groups: dict[str, list[str]] = defaultdict(list)
    for i in ids:
        groups[find(i)].append(i)
    return [members for members in groups.values() if len(members) > 1]


@dataclass
class Outcome:
    expired: list[str] = field(default_factory=list)
    demoted: list[str] = field(default_factory=list)
    superseded: list[str] = field(default_factory=list)
    candidate_groups: list[list[str]] = field(default_factory=list)
    # Same-context clusters at or above the semantic threshold, newest first.
    # Reported by every plan that had an embedder; rewritten only under --merge.
    semantic_groups: list[list[str]] = field(default_factory=list)
    # Clusters above MAX_CLUSTER_MEMBERS: reported for review, never merged.
    oversized_groups: list[list[str]] = field(default_factory=list)
    merged: list[dict[str, Any]] = field(default_factory=list)
    merge_skipped: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "expired": self.expired,
            "demoted": self.demoted,
            "superseded": self.superseded,
            "candidate_groups": self.candidate_groups,
            "semantic_groups": self.semantic_groups,
            "oversized_groups": self.oversized_groups,
            "merged": self.merged,
            "merge_skipped": self.merge_skipped,
        }


def plan(
    conn: sqlite3.Connection,
    *,
    owner_id: str,
    stale_days: int,
    embedder: Any = None,
    consolidate_cosine: float | None = None,
    importance_floor: float = 0.0,
) -> Outcome:
    outcome = Outcome()
    outcome.expired = [
        row["id"]
        for row in conn.execute(
            """SELECT id FROM memories WHERE owner_id=? AND status='active'
                AND valid_until IS NOT NULL
                AND valid_until<=strftime('%Y-%m-%dT%H:%M:%SZ','now')""",
            (owner_id,),
        )
    ]
    outcome.demoted = [
        row["id"]
        for row in conn.execute(
            """SELECT id FROM memories WHERE owner_id=? AND status='active'
                AND importance>?
                AND COALESCE(last_retrieved_at,created_at)
                    <=strftime('%Y-%m-%dT%H:%M:%SZ','now',?)
                AND updated_at<=strftime('%Y-%m-%dT%H:%M:%SZ','now',?)""",
            (owner_id, importance_floor, f"-{stale_days} days", f"-{stale_days} days"),
        )
    ]
    groups: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for row in conn.execute(
        """SELECT id,kind,text,context_json FROM memories
            WHERE owner_id=? AND status='active' ORDER BY updated_at DESC,id""",
        (owner_id,),
    ):
        groups[(row["kind"], row["context_json"], _normalise(row["text"]))].append(row["id"])
    outcome.candidate_groups = [ids for ids in groups.values() if len(ids) > 1]

    if embedder is not None and consolidate_cosine is not None:
        outcome.semantic_groups, outcome.oversized_groups = _semantic_groups(
            conn,
            owner_id=owner_id,
            embedder=embedder,
            threshold=consolidate_cosine,
            exact_groups=outcome.candidate_groups,
        )
    return outcome


def _semantic_groups(
    conn: sqlite3.Connection,
    *,
    owner_id: str,
    embedder: Any,
    threshold: float,
    exact_groups: list[list[str]],
) -> tuple[list[list[str]], list[list[str]]]:
    """Same-context near-duplicate clusters, and the ones too big to merge.

    Contexts are never crossed — by this repo's model a fact duplicated across
    contexts is two facts — and a cluster identical to an exact group is
    omitted: the cheap path already owns it. Clusters above
    MAX_CLUSTER_MEMBERS are returned separately and never merged.
    """
    by_context: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for row in conn.execute(
        """SELECT id,text,context_json FROM memories
            WHERE owner_id=? AND status='active' ORDER BY updated_at DESC,id""",
        (owner_id,),
    ):
        by_context[row["context_json"] or "{}"].append(row)

    exact_sets = [set(group) for group in exact_groups]
    clusters: list[list[str]] = []
    oversized: list[list[str]] = []
    for rows in by_context.values():
        if len(rows) < 2:
            continue
        vectors = embedder.encode([row["text"] for row in rows])
        edges: set[tuple[str, str]] = set()
        for i in range(len(rows)):
            for j in range(i + 1, len(rows)):
                cosine = sum(a * b for a, b in zip(vectors[i], vectors[j], strict=True))
                if cosine >= threshold:
                    edges.add((rows[i]["id"], rows[j]["id"]))
        for component in _connected_components([row["id"] for row in rows], edges):
            if set(component) in exact_sets:
                continue
            if len(component) > MAX_CLUSTER_MEMBERS:
                oversized.append(component)
                continue
            clusters.append(component)
    return clusters, oversized


def run(
    conn: sqlite3.Connection,
    *,
    owner_id: str,
    stale_days: int,
    demotion: float,
    dry_run: bool,
    # Decay has a floor: an untouched fact used to lose 0.1 per pass with no
    # lower bound, so ten passes drove importance to zero. That removes it from
    # the top of the profile's importance ordering and zeroes its retrieval
    # bonus -- silent deletion by attrition, for a fact nobody happened to
    # search for.
    importance_floor: float = 0.0,
    embedder: Any = None,
    consolidate_cosine: float | None = None,
    merge: bool = False,
    merge_model: str = "",
    monthly_limit_usd: float = 0.0,
    anthropic_api_key: str = "",
    gemini_api_key: str = "",
    project: str = "",
    location: str = "",
    merge_cap: int = 20,
) -> Outcome:
    outcome = plan(
        conn,
        owner_id=owner_id,
        stale_days=stale_days,
        embedder=embedder,
        consolidate_cosine=consolidate_cosine,
        importance_floor=importance_floor,
    )
    if dry_run:
        return outcome
    with transaction(conn):
        for memory_id in outcome.expired:
            store.set_memory_status(
                conn,
                memory_id=memory_id,
                owner_id=owner_id,
                status="expired",
            )
        for memory_id in outcome.demoted:
            row = conn.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
            store.update_memory(
                conn,
                memory_id=memory_id,
                owner_id=owner_id,
                expected_revision=int(row["revision"]),
                text=row["text"],
                kind=row["kind"],
                context=json.loads(row["context_json"]),
                tags=json.loads(row["tags_json"]),
                importance=max(importance_floor, float(row["importance"]) - demotion),
                confidence=float(row["confidence"]),
                valid_until=row["valid_until"],
            )
        for group in outcome.candidate_groups:
            survivor, *duplicates = group
            for duplicate in duplicates:
                store.set_memory_status(
                    conn,
                    memory_id=duplicate,
                    owner_id=owner_id,
                    status="superseded",
                    superseded_by=survivor,
                )
                conn.execute(
                    """INSERT OR IGNORE INTO memory_sources(memory_id,message_id)
                       SELECT ?,message_id FROM memory_sources WHERE memory_id=?""",
                    (survivor, duplicate),
                )
                conn.execute(
                    """INSERT OR IGNORE INTO memory_evidence
                       (memory_id,message_id,start_char,end_char,excerpt_sha256)
                       SELECT ?,message_id,start_char,end_char,excerpt_sha256
                         FROM memory_evidence WHERE memory_id=?""",
                    (survivor, duplicate),
                )
                outcome.superseded.append(duplicate)
    if merge and outcome.semantic_groups:
        _apply_merges(
            conn,
            outcome,
            owner_id=owner_id,
            model=merge_model,
            monthly_limit_usd=monthly_limit_usd,
            anthropic_api_key=anthropic_api_key,
            gemini_api_key=gemini_api_key,
            project=project,
            location=location,
            cap=merge_cap,
        )
    return outcome


def _inherit_provenance(conn: sqlite3.Connection, survivor: str, member: str) -> None:
    conn.execute(
        """INSERT OR IGNORE INTO memory_sources(memory_id,message_id)
           SELECT ?,message_id FROM memory_sources WHERE memory_id=?""",
        (survivor, member),
    )
    conn.execute(
        """INSERT OR IGNORE INTO memory_evidence
           (memory_id,message_id,start_char,end_char,excerpt_sha256)
           SELECT ?,message_id,start_char,end_char,excerpt_sha256
             FROM memory_evidence WHERE memory_id=?""",
        (survivor, member),
    )


def _log_merge_run(
    conn: sqlite3.Connection,
    *,
    owner_id: str,
    model: str,
    memory_ids: list[str],
    raw: Any,
    error: str | None,
    input_tokens: int,
    output_tokens: int,
    cost: float,
    latency_ms: int,
) -> int:
    from . import prompts

    cur = conn.execute(
        """INSERT INTO judge_runs
           (owner_id,kind,model,prompt_version,input_json,output_json,error,
            input_tokens,output_tokens,cost_usd,latency_ms,created_at)
           VALUES (?,'merge',?,?,?,?,?,?,?,?,?,?)""",
        (
            owner_id,
            model,
            prompts.CONSOLIDATE_VERSION,
            json.dumps({"memory_ids": memory_ids}, ensure_ascii=False),
            json.dumps(raw, ensure_ascii=False) if raw is not None else None,
            error,
            input_tokens,
            output_tokens,
            cost,
            latency_ms,
            datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        ),
    )
    return int(cur.lastrowid)


def _apply_merges(
    conn: sqlite3.Connection,
    outcome: Outcome,
    *,
    owner_id: str,
    model: str,
    monthly_limit_usd: float,
    anthropic_api_key: str,
    gemini_api_key: str,
    project: str,
    location: str,
    cap: int,
) -> None:
    """LLM-confirmed merges of the planned semantic clusters.

    Provider calls run outside write transactions and under the same monthly
    budget reservation discipline as extraction. Rollback is free by design:
    members keep their text and `superseded_by`, so reverting a merge is
    re-activating them and archiving the survivor.
    """
    from . import judge, prompts, providers
    from .retrieval import _token_count

    if len(outcome.semantic_groups) > cap:
        outcome.merge_skipped.append(
            {"reason": "merge_cap", "groups_beyond_cap": len(outcome.semantic_groups) - cap}
        )
    for group in outcome.semantic_groups[:cap]:
        placeholders = ",".join("?" for _ in group)
        rows = conn.execute(
            f"""SELECT * FROM memories
                 WHERE id IN ({placeholders}) AND owner_id=? AND status='active'""",
            (*group, owner_id),
        ).fetchall()
        rows.sort(key=lambda row: group.index(row["id"]))  # newest first, as planned
        if len(rows) < 2:
            outcome.merge_skipped.append({"group": group, "reason": "members_no_longer_active"})
            continue
        facts = [
            {
                "id": row["id"],
                "kind": row["kind"],
                "context": json.loads(row["context_json"] or "{}"),
                "text": row["text"],
            }
            for row in rows
        ]
        prompt = prompts.render_consolidate(facts)
        estimated_input = max(_token_count(prompt), len(prompt.encode("utf-8")))
        maximum_cost = judge.cost_of(estimated_input, 1024, model=model)
        period = datetime.now(UTC).strftime("%Y-%m")
        try:
            reservation_id = jobs.reserve_budget(
                conn, period=period, amount_usd=maximum_cost, limit_usd=monthly_limit_usd
            )
        except jobs.BudgetExceeded:
            outcome.merge_skipped.append({"group": group, "reason": "monthly_cost_limit_reached"})
            break

        t0 = time.perf_counter()
        try:
            result = providers.call_merge(
                model=model,
                prompt=prompt,
                anthropic_api_key=anthropic_api_key,
                gemini_api_key=gemini_api_key,
                project=project,
                location=location,
            )
        except Exception as exc:  # provider SDKs raise freely; a merge is optional
            result = providers.ProviderResult(error=f"{type(exc).__name__}: {exc}")
        latency_ms = int((time.perf_counter() - t0) * 1000)
        cost = judge.cost_of(result.input_tokens, result.output_tokens, model=model)
        with transaction(conn):
            run_id = _log_merge_run(
                conn,
                owner_id=owner_id,
                model=model,
                memory_ids=[row["id"] for row in rows],
                raw=result.raw,
                error=result.error,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                cost=cost,
                latency_ms=latency_ms,
            )
            conn.execute(
                """UPDATE budget_reservations
                      SET actual_usd=?,status='reconciled',updated_at=? WHERE id=?""",
                (cost, datetime.now(UTC).isoformat(), reservation_id),
            )
        merged_text = str((result.raw or {}).get("text") or "").strip() if not result.error else ""
        if result.error or not merged_text or len(merged_text) > 200:
            reason = result.error or ("null_merge" if not merged_text else "merged_text_too_long")
            outcome.merge_skipped.append({"group": group, "reason": reason})
            continue

        newest = rows[0]
        roles = {row["source_role"] for row in rows}
        raw_importance = (result.raw or {}).get("importance")
        try:
            importance = min(1.0, max(0.0, float(raw_importance)))
        except (TypeError, ValueError):
            importance = max(float(row["importance"]) for row in rows)
        with transaction(conn):
            survivor = store.add_memory(
                conn,
                owner_id=owner_id,
                text=merged_text,
                kind=newest["kind"],
                context=json.loads(newest["context_json"] or "{}"),
                tags=json.loads(newest["tags_json"] or "[]"),
                agent_id=newest["agent_id"],
                importance=importance,
                confidence=min(float(row["confidence"]) for row in rows),
                extraction_version=f"consolidate-{prompts.CONSOLIDATE_VERSION}",
                judge_run_id=run_id,
                # A merge is no better sourced than its worst input; anything
                # else would launder assistant text into a user-sourced fact.
                source_role=provenance.weakest(roles),
            )
            for row in rows:
                _inherit_provenance(conn, survivor, row["id"])
                store.set_memory_status(
                    conn,
                    memory_id=row["id"],
                    owner_id=owner_id,
                    status="superseded",
                    superseded_by=survivor,
                )
                outcome.superseded.append(row["id"])
        outcome.merged.append({"survivor": survivor, "members": [row["id"] for row in rows]})
