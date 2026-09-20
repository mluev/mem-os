"""Context-safe maintenance: exact-duplicate consolidation plus, when asked,
LLM-confirmed semantic merge of near-duplicate clusters (decisions/0056)."""

from __future__ import annotations

import logging
import re
import time
import uuid
from collections import defaultdict
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import numpy as np
import psycopg
from psycopg.types.json import Jsonb
from qdrant_client import QdrantClient

from . import jobs, maintenance, provenance, store, vectors
from .db import Row, transaction
from .embed import DIM

logger = logging.getLogger(__name__)

# ADR 0032 chose connected components and stated a six-member cap; the cap was
# never implemented. It matters because a transitive chain at the threshold can
# link facts that are not pairwise similar, and the whole cluster is then
# serialised into a prompt whose answer must fit 200 characters. Oversized
# clusters are reported instead of merged, so nothing is silently rewritten.
MAX_CLUSTER_MEMBERS = 6

# Rows per similarity block. The full N-by-N product of a large scope would be
# materialised in one array (10k rows is 400 MB at float32); a block of rows
# against the transpose gives the same pairs in bounded memory.
SIMILARITY_BLOCK = 1024


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def _scope_uuids(scope_ids: Sequence[str]) -> list[uuid.UUID]:
    """Scope ids as uuids, because `scope_id = ANY(%s)` compares uuid to uuid.

    A list of strings arrives as `text[]` and Postgres has no `uuid = text`, so
    the predicate that carries the authorization boundary would fail as a type
    error rather than filter.
    """
    return [uuid.UUID(str(scope)) for scope in scope_ids]


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
    # Same-scope, same-context clusters at or above the semantic threshold,
    # newest first. Reported by every plan that had an embedder; rewritten only
    # under --merge.
    semantic_groups: list[list[str]] = field(default_factory=list)
    # Clusters above MAX_CLUSTER_MEMBERS: reported for review, never merged.
    oversized_groups: list[list[str]] = field(default_factory=list)
    merged: list[dict[str, Any]] = field(default_factory=list)
    merge_skipped: list[dict[str, Any]] = field(default_factory=list)
    planned_revisions: dict[str, int] = field(default_factory=dict, repr=False)

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
    conn: psycopg.Connection,
    *,
    scope_ids: Sequence[str],
    stale_days: int,
    embedder: Any = None,
    consolidate_cosine: float | None = None,
    importance_floor: float = 0.0,
    client: QdrantClient | None = None,
) -> Outcome:
    """What one pass over these scopes would change, without changing anything.

    Every query is bounded by `scope_id = ANY(scope_ids)`: a maintenance pass
    reads only the scopes it was given, so a nightly instance-wide run and a
    single-team run are the same code with a different list.
    """
    outcome = Outcome()
    if not scope_ids:
        return outcome
    scopes = _scope_uuids(scope_ids)
    outcome.expired = [
        str(row["id"])
        for row in conn.execute(
            """SELECT id FROM memories
                WHERE scope_id = ANY(%s) AND status='active'
                  AND valid_until IS NOT NULL AND valid_until <= now()""",
            (scopes,),
        )
    ]
    # `updated_at` carries the last demotion, so a fact discounted today is not
    # eligible again until it has been idle for another whole period.
    #
    # The floor is cast to `real` because that is the column's type: compared as
    # float8, a stored 0.3 widens to 0.30000001192092896 and sits *above* a
    # float8 0.3, so a fact resting exactly on the floor would be demoted on
    # every pass forever, gaining a revision each time and never changing value.
    outcome.demoted = [
        str(row["id"])
        for row in conn.execute(
            """SELECT id FROM memories
                WHERE scope_id = ANY(%s) AND status='active'
                  AND importance > %s::real
                  AND COALESCE(last_retrieved_at,created_at) <= now() - make_interval(days => %s)
                  AND updated_at <= now() - make_interval(days => %s)""",
            (scopes, importance_floor, stale_days, stale_days),
        )
    ]

    rows = conn.execute(
        """SELECT * FROM memories
            WHERE scope_id = ANY(%s) AND status='active'
              AND (valid_until IS NULL OR valid_until > now())
            ORDER BY updated_at DESC,id""",
        (scopes,),
    ).fetchall()
    groups: dict[tuple, list[str]] = defaultdict(list)
    for row in rows:
        outcome.planned_revisions[str(row["id"])] = int(row["revision"])
        key = (*store.memory_identity(row), _normalise(str(row["text"])))
        groups[key].append(str(row["id"]))
    outcome.candidate_groups = [ids for ids in groups.values() if len(ids) > 1]

    if embedder is not None and consolidate_cosine is not None:
        outcome.semantic_groups, outcome.oversized_groups = _semantic_groups(
            rows,
            scope_ids=scope_ids,
            embedder=embedder,
            client=client,
            threshold=consolidate_cosine,
            exact_groups=outcome.candidate_groups,
        )
    return outcome


def _member_vectors(
    rows: Sequence[Row],
    *,
    scope_ids: Sequence[str],
    embedder: Any,
    client: QdrantClient | None,
) -> dict[str, list[float]]:
    """One vector per row, taken from the index wherever it already exists.

    Qdrant holds a vector for every active memory — the same vector the read
    path searches — so embedding the store again to cluster it runs the model
    over data the index is already keeping. Rows the index is missing (drift, or
    a scope whose outbox has not drained) are embedded in a single batch, so the
    fallback costs one model call rather than one per row.

    With no client at all the whole set is embedded, which keeps consolidation
    working when the index is down or absent.
    """
    found: dict[str, list[float]] = {}
    if client is not None:
        found = vectors.scroll_vectors(
            client,
            vectors.MEMORIES,
            must=[
                vectors.keyword("scope_id", [str(scope) for scope in scope_ids]),
                vectors.keyword("status", "active"),
            ],
        )
        stored = next((len(vector) for vector in found.values()), DIM)
        if stored != DIM:
            # An index built with a different model. Mixing its vectors with
            # freshly embedded ones would compare two unrelated spaces, so the
            # index is ignored until a reindex rebuilds it.
            logger.warning(
                "index holds %s-dim vectors, expected %s; embedding instead", stored, DIM
            )
            found = {}
    missing = [row for row in rows if str(row["id"]) not in found]
    if missing:
        encoded = embedder.encode([str(row["text"]) for row in missing])
        for row, vector in zip(missing, encoded, strict=True):
            found[str(row["id"])] = list(vector)
    return found


def _similar_pairs(matrix: np.ndarray, threshold: float) -> Iterator[tuple[int, int]]:
    """Index pairs at or above the threshold, upper triangle only.

    Every stored vector is L2-normalised (`Embedder.encode` normalises, and
    Qdrant hands back what was stored), so the dot product *is* the cosine and
    one matrix multiply replaces the pairwise Python loop this used to run.
    """
    for start in range(0, len(matrix), SIMILARITY_BLOCK):
        block = matrix[start : start + SIMILARITY_BLOCK] @ matrix.T
        for row, column in zip(*np.nonzero(block >= threshold), strict=True):
            i = start + int(row)
            j = int(column)
            if j > i:
                yield i, j


def _semantic_groups(
    rows: Sequence[Row],
    *,
    scope_ids: Sequence[str],
    embedder: Any,
    client: QdrantClient | None,
    threshold: float,
    exact_groups: list[list[str]],
) -> tuple[list[list[str]], list[list[str]]]:
    """Near-duplicate clusters within one scope and one context, and the
    oversized ones.

    Clustering is keyed on `(scope_id, context)` and crosses neither. Contexts
    are separate because by this repo's model a fact stated in two contexts is
    two facts; scopes are separate because the same sentence in two scopes is
    also two facts, one of them possibly shared and the other private — merging
    them would move a private claim into a space other people can read, or
    delete the shared copy the team relies on.

    A cluster identical to an exact group is omitted: the cheap path already
    owns it. Clusters above MAX_CLUSTER_MEMBERS are returned separately and
    never merged.
    """
    grouped: dict[tuple, list[Row]] = defaultdict(list)
    for row in rows:
        grouped[store.memory_identity(row)].append(row)
    comparable = [row for group in grouped.values() if len(group) > 1 for row in group]
    if not comparable:
        return [], []

    by_id = _member_vectors(comparable, scope_ids=scope_ids, embedder=embedder, client=client)
    exact_sets = [set(group) for group in exact_groups]
    clusters: list[list[str]] = []
    oversized: list[list[str]] = []
    for group in grouped.values():
        if len(group) < 2:
            continue
        ids = [str(row["id"]) for row in group]
        matrix = np.asarray([by_id[member] for member in ids], dtype=np.float32)
        edges = {(ids[i], ids[j]) for i, j in _similar_pairs(matrix, threshold)}
        for component in _connected_components(ids, edges):
            if set(component) in exact_sets:
                continue
            if len(component) > MAX_CLUSTER_MEMBERS:
                oversized.append(component)
                continue
            clusters.append(component)
    return clusters, oversized


def run(
    conn: psycopg.Connection,
    *,
    scope_ids: Sequence[str],
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
    client: QdrantClient | None = None,
    merge: bool = False,
    merge_model: str = "",
    monthly_limit_usd: float = 0.0,
    anthropic_api_key: str = "",
    gemini_api_key: str = "",
    project: str = "",
    location: str = "",
    merge_cap: int = 20,
    # None for a scheduled instance-wide pass, which no user asked for; a
    # dashboard-triggered run attributes its judge spend to the caller.
    user_id: str | None = None,
    guard: Callable[[], None] | None = None,
) -> Outcome:
    outcome = plan(
        conn,
        scope_ids=scope_ids,
        stale_days=stale_days,
        embedder=embedder,
        consolidate_cosine=consolidate_cosine,
        importance_floor=importance_floor,
        client=client,
    )
    if dry_run:
        return outcome
    with transaction(conn):
        maintenance.require_write(conn)
        if guard is not None:
            guard()
        for memory_id in outcome.expired:
            current = conn.execute(
                """SELECT id FROM memories WHERE id=%s AND status='active'
                   AND valid_until <= now() FOR UPDATE""",
                (memory_id,),
            ).fetchone()
            if current is None:
                continue
            store.set_memory_status(
                conn,
                memory_id=memory_id,
                scopes=scope_ids,
                status="expired",
            )
        for memory_id in outcome.demoted:
            row = conn.execute(
                """SELECT * FROM memories WHERE id=%s AND status='active'
                   AND importance > %s::real
                   AND COALESCE(last_retrieved_at,created_at) <= now()-make_interval(days => %s)
                   AND updated_at <= now()-make_interval(days => %s) FOR UPDATE""",
                (memory_id, importance_floor, stale_days, stale_days),
            ).fetchone()
            if row is None:  # pragma: no cover - planned in this transaction
                continue
            saved = store.update_memory(
                conn,
                memory_id=memory_id,
                scopes=scope_ids,
                expected_revision=int(row["revision"]),
                text=str(row["text"]),
                kind=str(row["kind"]),
                context=dict(row["context"] or {}),
                tags=list(row["tags"] or []),
                importance=max(importance_floor, float(row["importance"]) - demotion),
                confidence=float(row["confidence"]),
                valid_until=row["valid_until"],
            )
            outcome.planned_revisions[memory_id] = int(saved["revision"])
        for group in outcome.candidate_groups:
            current = _lock_group(conn, group, scope_ids, outcome.planned_revisions)
            if current is None or len({_normalise(row["text"]) for row in current}) != 1:
                outcome.merge_skipped.append({"group": group, "reason": "members_changed"})
                continue
            survivor, *duplicates = group
            for duplicate in duplicates:
                store.set_memory_status(
                    conn,
                    memory_id=duplicate,
                    scopes=scope_ids,
                    status="superseded",
                    superseded_by=survivor,
                )
                _inherit_provenance(conn, survivor, duplicate)
                outcome.superseded.append(duplicate)
    if merge and outcome.semantic_groups:
        _apply_merges(
            conn,
            outcome,
            scope_ids=scope_ids,
            user_id=user_id,
            model=merge_model,
            monthly_limit_usd=monthly_limit_usd,
            anthropic_api_key=anthropic_api_key,
            gemini_api_key=gemini_api_key,
            project=project,
            location=location,
            cap=merge_cap,
            guard=guard,
        )
    return outcome


def _inherit_provenance(conn: psycopg.Connection, survivor: str, member: str) -> None:
    """Give the survivor every citation its member had.

    Both tables are keyed on (memory, message[, span]), so re-inserting a
    citation the survivor already holds is a no-op rather than a conflict.
    """
    conn.execute(
        """INSERT INTO memory_sources(memory_id,message_id)
           SELECT %s,message_id FROM memory_sources WHERE memory_id=%s
           ON CONFLICT DO NOTHING""",
        (uuid.UUID(survivor), uuid.UUID(member)),
    )
    conn.execute(
        """INSERT INTO memory_evidence
           (memory_id,message_id,start_char,end_char,excerpt_sha256)
           SELECT %s,message_id,start_char,end_char,excerpt_sha256
             FROM memory_evidence WHERE memory_id=%s
           ON CONFLICT DO NOTHING""",
        (uuid.UUID(survivor), uuid.UUID(member)),
    )
    conn.execute(
        """INSERT INTO memory_revision_evidence
           (memory_id,revision,message_id,start_char,end_char)
           SELECT destination.id,destination.revision,e.message_id,e.start_char,e.end_char
             FROM memory_revision_evidence e
             JOIN memories source ON source.id=e.memory_id AND source.revision=e.revision
             JOIN memories destination ON destination.id=%s
            WHERE e.memory_id=%s ON CONFLICT DO NOTHING""",
        (uuid.UUID(survivor), uuid.UUID(member)),
    )


def _lock_group(
    conn: psycopg.Connection, group: list[str], scopes: Sequence[str], revisions: dict[str, int]
) -> list[Row] | None:
    rows = conn.execute(
        """SELECT * FROM memories WHERE id=ANY(%s) AND scope_id=ANY(%s)
           AND status='active' AND (valid_until IS NULL OR valid_until > now())
           ORDER BY id FOR UPDATE""",
        (_scope_uuids(group), _scope_uuids(scopes)),
    ).fetchall()
    if len(rows) != len(group) or len({store.memory_identity(row) for row in rows}) != 1:
        return None
    if any(int(row["revision"]) != revisions[str(row["id"])] for row in rows):
        return None
    return rows


def _log_merge_run(
    conn: psycopg.Connection,
    *,
    user_id: str | None,
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

    row = conn.execute(
        """INSERT INTO judge_runs
           (user_id,kind,model,prompt_version,input,output,error,
            input_tokens,output_tokens,cost_usd,latency_ms,created_at)
           VALUES (%s,'merge',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
           RETURNING id""",
        (
            user_id,
            model,
            prompts.CONSOLIDATE_VERSION,
            Jsonb({"memory_ids": memory_ids}),
            Jsonb(raw) if raw is not None else None,
            error,
            input_tokens,
            output_tokens,
            cost,
            latency_ms,
            datetime.now(UTC),
        ),
    ).fetchone()
    if row is None:  # pragma: no cover - RETURNING cannot be empty here
        raise RuntimeError("judge_runs insert returned no row")
    return int(row["id"])


def _apply_merges(
    conn: psycopg.Connection,
    outcome: Outcome,
    *,
    scope_ids: Sequence[str],
    user_id: str | None,
    model: str,
    monthly_limit_usd: float,
    anthropic_api_key: str,
    gemini_api_key: str,
    project: str,
    location: str,
    cap: int,
    guard: Callable[[], None] | None = None,
) -> None:
    """LLM-confirmed merges of the planned semantic clusters.

    Provider calls run outside write transactions and under the same monthly
    budget reservation discipline as extraction. Rollback is free by design:
    members keep their text and `superseded_by`, so reverting a merge is
    re-activating them and archiving the survivor.
    """
    from . import judge, prompts, providers
    from .retrieval import _token_count

    scopes = _scope_uuids(scope_ids)
    if len(outcome.semantic_groups) > cap:
        outcome.merge_skipped.append(
            {"reason": "merge_cap", "groups_beyond_cap": len(outcome.semantic_groups) - cap}
        )
    for group in outcome.semantic_groups[:cap]:
        if guard is not None:
            with transaction(conn):
                guard()
        rows = conn.execute(
            """SELECT * FROM memories
                WHERE id = ANY(%s) AND scope_id = ANY(%s) AND status='active'""",
            ([uuid.UUID(member) for member in group], scopes),
        ).fetchall()
        rows.sort(key=lambda row: group.index(str(row["id"])))  # newest first, as planned
        if len(rows) < 2:
            outcome.merge_skipped.append({"group": group, "reason": "members_no_longer_active"})
            continue
        if len(rows) != len(group) or len({store.memory_identity(row) for row in rows}) != 1:
            outcome.merge_skipped.append({"group": group, "reason": "members_changed"})
            continue
        revisions = {str(row["id"]): int(row["revision"]) for row in rows}
        if any(revisions[key] != outcome.planned_revisions.get(key) for key in revisions):
            outcome.merge_skipped.append({"group": group, "reason": "members_changed"})
            continue
        facts = [
            {
                "id": str(row["id"]),
                "kind": row["kind"],
                "context": dict(row["context"] or {}),
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
                conn,
                period=period,
                amount_usd=maximum_cost,
                limit_usd=monthly_limit_usd,
                user_id=user_id,
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
                user_id=user_id,
                model=model,
                memory_ids=[str(row["id"]) for row in rows],
                raw=result.raw,
                error=result.error,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                cost=cost,
                latency_ms=latency_ms,
            )
            jobs.reconcile_budget(conn, reservation_id, actual_usd=cost)
        merged_text = str((result.raw or {}).get("text") or "").strip() if not result.error else ""
        if result.error or not merged_text or len(merged_text) > 200:
            reason = result.error or ("null_merge" if not merged_text else "merged_text_too_long")
            outcome.merge_skipped.append({"group": group, "reason": reason})
            continue

        newest = rows[0]
        roles = {str(row["source_role"]) for row in rows}
        raw_importance = (result.raw or {}).get("importance")
        try:
            importance = min(1.0, max(0.0, float(raw_importance)))
        except (TypeError, ValueError):
            importance = max(float(row["importance"]) for row in rows)
        # A merge of unreviewed facts is itself unreviewed: confirmation means a
        # human read the wording, and the survivor's wording is new.
        with transaction(conn):
            maintenance.require_write(conn)
            if guard is not None:
                guard()
            if _lock_group(conn, group, scope_ids, revisions) is None:
                outcome.merge_skipped.append({"group": group, "reason": "members_changed"})
                continue
            survivor = store.add_memory(
                conn,
                # The cluster never crosses a scope, so the newest member's
                # scope is the cluster's, and its subject carries over: a merge
                # of facts about one teammate is still about that teammate.
                scope_id=str(newest["scope_id"]),
                subject_id=(
                    str(newest["subject_id"]) if newest["subject_id"] is not None else None
                ),
                author_id=str(newest["author_id"]),
                text=merged_text,
                kind=str(newest["kind"]),
                context=dict(newest["context"] or {}),
                tags=list(newest["tags"] or []),
                agent_id=newest["agent_id"],
                importance=importance,
                confidence=min(float(row["confidence"]) for row in rows),
                valid_until=newest["valid_until"],
                extraction_version=f"consolidate-{prompts.CONSOLIDATE_VERSION}",
                judge_run_id=run_id,
                # A merge is no better sourced than its worst input; anything
                # else would launder assistant text into a user-sourced fact.
                source_role=provenance.weakest(roles),
                review_status="pending",
            )
            for row in rows:
                member_id = str(row["id"])
                _inherit_provenance(conn, survivor, member_id)
                store.set_memory_status(
                    conn,
                    memory_id=member_id,
                    scopes=scope_ids,
                    status="superseded",
                    superseded_by=survivor,
                    expected_revision=int(row["revision"]),
                )
                outcome.superseded.append(member_id)
        outcome.merged.append({"survivor": survivor, "members": [str(row["id"]) for row in rows]})
