"""Dreaming: link and infer across memories that were written one window apart.

Extraction sees ten messages at a time. It can supersede a candidate it was
shown, but a claim from last month that a new window contradicts is often not
among its candidates, and what several memories imply together is invisible to
any single window. Dreaming is the second pass (decisions/0078):

1. Pick the memories in one scope that changed since that scope last dreamed.
2. Around each, gather its nearest neighbours in the same scope.
3. Ask the model, per cluster, for `updates`/`extends` links and at most two
   inferences, each naming the memories it depends on by number.
4. Verify everything against the database before writing: numbers in range,
   both ends active and in the scope, an `updates` pointing forward in time
   between claims with the same subject and context, an inference with two or
   more live premises that is not already stated.

An inference is written with `source_role='inference'`, `review_status=
'pending'` and a `derives` edge to each premise. It ranks below stated facts
until someone confirms it, and it is never a premise for another inference, so
guesses cannot compound.

Scopes never mix: every cluster lives in one scope, so nothing private can be
inferred into a shared space.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import psycopg

from . import judge, maintenance, prompts, store, vectors
from .db import Row, iso

logger = logging.getLogger(__name__)

# Memories a dream starts from, newest first. Each becomes at most one cluster.
MAX_FRESH = 40
# Neighbours gathered per fresh memory, and the similarity they need.
NEIGHBOURS = 6
NEIGHBOUR_FLOOR = 0.55
MAX_CLUSTER = 8
# An inference below this confidence is not written at all.
MIN_INFERENCE_CONFIDENCE = 0.7
# An inference at least this similar to an existing memory is already stated.
DUPLICATE_COSINE = 0.9
PREMISE_ROLES = ("user", "manual", "tool")


@dataclass
class DreamOutcome:
    fresh: int = 0
    clusters: int = 0
    calls: int = 0
    extended: int = 0
    superseded: int = 0
    inferred: int = 0
    cost_usd: float = 0.0
    skipped: list[dict[str, Any]] = field(default_factory=list)
    planned: list[list[str]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "fresh": self.fresh,
            "clusters": self.clusters,
            "calls": self.calls,
            "extended": self.extended,
            "superseded": self.superseded,
            "inferred": self.inferred,
            "cost_usd": round(self.cost_usd, 6),
            "skipped": self.skipped,
            "planned": self.planned,
        }


def last_dreamed(conn: psycopg.Connection, scope_id: str) -> datetime | None:
    """When the scope's last completed dream started, or None if it never has."""
    row = conn.execute(
        """SELECT max(started_at) AS at FROM jobs
            WHERE kind='dream' AND status='complete' AND input->>'scope_id' = %s""",
        (scope_id,),
    ).fetchone()
    return row["at"] if row else None


def fresh_memories(
    conn: psycopg.Connection, scope_id: str, *, since: datetime | None, limit: int = MAX_FRESH
) -> list[Row]:
    return conn.execute(
        """SELECT * FROM memories
            WHERE scope_id=%s AND status='active' AND source_role = ANY(%s)
              AND (valid_until IS NULL OR valid_until > now())
              AND (%s::timestamptz IS NULL OR updated_at > %s::timestamptz)
            ORDER BY updated_at DESC, id LIMIT %s""",
        (scope_id, list(PREMISE_ROLES), since, since, limit),
    ).fetchall()


def plan_clusters(
    conn: psycopg.Connection,
    client: Any,
    embedder: Any,
    *,
    scope_id: str,
    fresh: Sequence[Row],
    max_clusters: int,
) -> list[list[Row]]:
    """Each fresh memory with its nearest same-scope neighbours.

    A cluster whose members are all inside one already chosen is dropped, so a
    burst of related writes costs one call rather than one per write.
    """
    if not fresh:
        return []
    vectors_by_id = dict(
        zip(
            [str(row["id"]) for row in fresh],
            embedder.encode([str(row["text"]) for row in fresh]),
            strict=True,
        )
    )
    chosen: list[list[Row]] = []
    covered: list[set[str]] = []
    for row in fresh:
        if len(chosen) >= max_clusters:
            break
        hits = vectors.search(
            client,
            vectors.MEMORIES,
            vectors_by_id[str(row["id"])],
            limit=NEIGHBOURS + 1,
            must=[vectors.keyword("scope_id", scope_id), vectors.keyword("status", "active")],
        )
        ids = [
            str(hit.id)
            for hit in hits
            if float(hit.score) >= NEIGHBOUR_FLOOR and str(hit.id) != str(row["id"])
        ]
        members = [row]
        if ids:
            members += conn.execute(
                """SELECT * FROM memories
                    WHERE id = ANY(%s) AND scope_id=%s AND status='active'
                      AND source_role = ANY(%s)
                      AND (valid_until IS NULL OR valid_until > now())
                    ORDER BY document_date, id""",
                ([uuid.UUID(i) for i in ids], scope_id, list(PREMISE_ROLES)),
            ).fetchall()
        members = members[:MAX_CLUSTER]
        if len(members) < 2:
            continue
        keys = {str(member["id"]) for member in members}
        if any(keys <= existing for existing in covered):
            continue
        # Oldest first, so "said" dates read in order.
        members.sort(key=lambda member: (member["document_date"], str(member["id"])))
        chosen.append(members)
        covered.append(keys)
    return chosen


def run(
    conn: psycopg.Connection,
    *,
    scope_id: str,
    user_id: str,
    client: Any,
    embedder: Any,
    model: str,
    monthly_limit_usd: float,
    api_key: str = "",
    gemini_api_key: str = "",
    project: str = "",
    location: str = "",
    since: datetime | str | None = "auto",
    max_clusters: int = 8,
    dry_run: bool = False,
    job_id: str | None = None,
    guard: Callable[[], None] | None = None,
) -> DreamOutcome:
    """Dream over one scope on behalf of `user_id`, who must be able to write it."""
    outcome = DreamOutcome()
    with conn.transaction():
        if guard is not None:
            guard()
        store.require_scope_write(conn, user_id=user_id, scope_id=scope_id)
    start = last_dreamed(conn, scope_id) if since == "auto" else since
    fresh = fresh_memories(conn, scope_id, since=start)  # type: ignore[arg-type]
    outcome.fresh = len(fresh)
    clusters = plan_clusters(
        conn, client, embedder, scope_id=scope_id, fresh=fresh, max_clusters=max_clusters
    )
    outcome.clusters = len(clusters)
    outcome.planned = [[str(member["id"]) for member in cluster] for cluster in clusters]
    if dry_run:
        return outcome
    for cluster in clusters:
        if guard is not None:
            with conn.transaction():
                guard()
        shown = [
            {
                "kind": member["kind"],
                "text": member["text"],
                "said": (iso(member["document_date"]) or "")[:10] or None,
                "event_dates": list(member["event_dates"] or []),
            }
            for member in cluster
        ]
        result = judge.structured_call(
            conn,
            kind="dream",
            prompt_version=prompts.DREAM_VERSION,
            prompt=prompts.render_dream(shown),
            schema=prompts.dream_schema(),
            name="emit_dream",
            model=model,
            monthly_limit_usd=monthly_limit_usd,
            audit={
                "scope_id": scope_id,
                "memory_ids": [str(member["id"]) for member in cluster],
            },
            api_key=api_key,
            gemini_api_key=gemini_api_key,
            project=project,
            location=location,
            user_id=user_id,
            job_id=job_id,
        )
        outcome.calls += 1
        outcome.cost_usd += result.cost_usd
        if result.error or result.raw is None or result.judge_run_id is None:
            outcome.skipped.append({"reason": result.error or "empty_response"})
            if result.error in {"monthly_cost_limit_reached", "job_call_limit_reached"}:
                break
            continue
        with conn.transaction():
            maintenance.require_write(conn)
            if guard is not None:
                guard()
            store.require_scope_write(conn, user_id=user_id, scope_id=scope_id)
            _apply(
                conn,
                outcome,
                cluster=cluster,
                answer=result.raw,
                scope_id=scope_id,
                user_id=user_id,
                run_id=result.judge_run_id,
                client=client,
                embedder=embedder,
            )
    return outcome


def _number(value: Any, size: int) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number - 1 if 1 <= number <= size else None


def _live(conn: psycopg.Connection, memory_id: str, scope_id: str) -> Row | None:
    return conn.execute(
        """SELECT * FROM memories WHERE id=%s AND scope_id=%s AND status='active'
             AND (valid_until IS NULL OR valid_until > now()) FOR UPDATE""",
        (memory_id, scope_id),
    ).fetchone()


def _apply(
    conn: psycopg.Connection,
    outcome: DreamOutcome,
    *,
    cluster: list[Row],
    answer: dict[str, Any],
    scope_id: str,
    user_id: str,
    run_id: int,
    client: Any,
    embedder: Any,
) -> None:
    size = len(cluster)
    for link in answer.get("links") or []:
        if not isinstance(link, dict):
            continue
        source, target = _number(link.get("from"), size), _number(link.get("to"), size)
        relation = link.get("relation")
        if source is None or target is None or source == target:
            outcome.skipped.append({"reason": "invalid_link"})
            continue
        new = _live(conn, str(cluster[source]["id"]), scope_id)
        old = _live(conn, str(cluster[target]["id"]), scope_id)
        if new is None or old is None:
            outcome.skipped.append({"reason": "link_target_changed"})
            continue
        if relation == "extends":
            if store.add_relation(
                conn,
                from_id=str(new["id"]),
                to_id=str(old["id"]),
                relation="extends",
                judge_run_id=run_id,
            ):
                outcome.extended += 1
            continue
        if relation != "updates":
            outcome.skipped.append({"reason": "invalid_link"})
            continue
        # A replacement must come after what it replaces, be about the same
        # subject in the same context, and be a claim someone stated.
        if (
            new["document_date"] < old["document_date"]
            or new["subject_id"] != old["subject_id"]
            or dict(new["context"] or {}) != dict(old["context"] or {})
            or new["source_role"] not in PREMISE_ROLES
        ):
            outcome.skipped.append({"reason": "update_not_forward"})
            continue
        store.supersede(
            conn,
            old_id=str(old["id"]),
            new_id=str(new["id"]),
            scopes=[scope_id],
            judge_run_id=run_id,
        )
        outcome.superseded += 1

    written = 0
    for item in answer.get("inferences") or []:
        if written >= 2 or not isinstance(item, dict):
            break
        text = str(item.get("text") or "").strip()
        try:
            confidence = float(item.get("confidence"))
        except (TypeError, ValueError):
            confidence = 0.0
        numbers = sorted(
            {n for n in (_number(p, size) for p in item.get("premises") or []) if n is not None}
        )
        if not text or len(text) > 200 or len(numbers) < 2:
            outcome.skipped.append({"reason": "invalid_inference"})
            continue
        if confidence < MIN_INFERENCE_CONFIDENCE:
            outcome.skipped.append({"reason": "low_confidence"})
            continue
        premises = [_live(conn, str(cluster[n]["id"]), scope_id) for n in numbers]
        if any(premise is None for premise in premises):
            outcome.skipped.append({"reason": "premise_changed"})
            continue
        live = [premise for premise in premises if premise is not None]
        if _already_stated(conn, client, embedder, scope_id=scope_id, text=text):
            outcome.skipped.append({"reason": "already_stated"})
            continue
        subjects = {premise["subject_id"] for premise in live}
        contexts = {repr(sorted(dict(premise["context"] or {}).items())) for premise in live}
        memory_id = store.add_memory(
            conn,
            scope_id=scope_id,
            subject_id=str(next(iter(subjects)))
            if len(subjects) == 1 and None not in subjects
            else None,
            author_id=user_id,
            text=text,
            kind=(str(item.get("kind") or "fact").strip() or "fact")[:64],
            context=dict(live[0]["context"] or {}) if len(contexts) == 1 else {},
            importance=min(0.6, max(float(premise["importance"]) for premise in live)),
            confidence=min(1.0, max(0.0, confidence)),
            extraction_version=f"dream-{prompts.DREAM_VERSION}",
            judge_run_id=run_id,
            source_role="inference",
            review_status="pending",
            document_date=max(premise["document_date"] for premise in live),
        )
        for premise in live:
            store.add_relation(
                conn,
                from_id=memory_id,
                to_id=str(premise["id"]),
                relation="derives",
                judge_run_id=run_id,
            )
        written += 1
        outcome.inferred += 1


def _already_stated(
    conn: psycopg.Connection, client: Any, embedder: Any, *, scope_id: str, text: str
) -> bool:
    if conn.execute(
        """SELECT 1 FROM memories WHERE scope_id=%s AND status='active' AND content_hash=%s
            LIMIT 1""",
        (scope_id, store.content_hash(text)),
    ).fetchone():
        return True
    hits = vectors.search(
        client,
        vectors.MEMORIES,
        embedder.encode_one(text),
        limit=1,
        must=[vectors.keyword("scope_id", scope_id), vectors.keyword("status", "active")],
    )
    return bool(hits) and float(hits[0].score) >= DUPLICATE_COSINE


def queue(
    conn: psycopg.Connection, *, scope_id: str, user_id: str, max_clusters: int
) -> str | None:
    """Queue a dream for a scope unless one is already waiting or running."""
    pending = conn.execute(
        """SELECT 1 FROM jobs WHERE kind='dream' AND status IN ('queued','running')
             AND input->>'scope_id' = %s LIMIT 1""",
        (scope_id,),
    ).fetchone()
    if pending:
        return None
    from . import jobs

    return jobs.create(
        conn,
        kind="dream",
        input_data={"scope_id": scope_id, "max_clusters": max_clusters},
        call_limit=max_clusters,
        user_id=user_id,
    )
