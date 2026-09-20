"""Memory HTTP endpoints."""

from __future__ import annotations

import hashlib
import logging
import time
import uuid
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any

import psycopg
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
)
from psycopg.types.json import Jsonb

from .. import (
    context_assembly,
    entities,
    maintenance,
    profiles,
    retrieval,
    store,
    telemetry,
    vectors,
)
from .. import (
    principal as principal_module,
)
from ..config import Settings, get_settings
from ..db import iso, utcnow
from ..http import _drain, _memory_id, _memory_summary, _outbox_state, get_conn, get_principal
from ..principal import Principal, ScopeForbidden, UnknownScope
from ..schemas import (
    AttentionResolveIn,
    EntityOut,
    FeedbackIn,
    FeedbackOut,
    FlexibleOut,
    MemoryCreatedOut,
    MemoryHistoryOut,
    MemoryIn,
    MemoryOut,
    MemoryPageOut,
    MemoryPatch,
    MemorySearchOut,
    MemorySourcesOut,
    ProfileIn,
    ProfileOut,
    RetrievalRunFeedbackIn,
    RetrievalRunsOut,
    ReviewIn,
    ReviewQueueOut,
    SearchIn,
)

_SORTABLE = {
    "updated_at": "m.updated_at",
    "created_at": "m.created_at",
    "importance": "m.importance",
    "confidence": "m.confidence",
    "retrieval_count": "m.retrieval_count",
}


router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/v1/memories", status_code=201)
def post_memory(
    request: Request,
    body: MemoryIn,
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> MemoryCreatedOut:
    """Save one memory.

    A user's own manual save into their own scope is confirmed immediately:
    they just said it, so asking them to confirm it again is noise. Anything
    else -- a shared scope, or a model-authored write -- starts pending.
    """
    scope_id = principal_module.resolve_scope(conn, principal, body.scope, write=True)
    subject_id = principal_module.resolve_subject(conn, principal, body.subject)
    self_asserted = body.source_role in {"user", "manual"} and scope_id == principal.own_entity_id
    try:
        with conn.transaction():
            existing = store.find_duplicate(
                conn,
                scope_id=scope_id,
                text=body.text,
                kind=body.kind,
                context=body.context,
                subject_id=subject_id,
                valid_until=body.valid_until,
                source_role=body.source_role,
            )
            if existing is not None:
                return MemoryCreatedOut(
                    id=str(existing["id"]),
                    stored=True,
                    indexed=True,
                    deduplicated=True,
                    review_status=str(existing["review_status"]),
                )
            memory_id = store.add_memory(
                conn,
                scope_id=scope_id,
                subject_id=subject_id,
                author_id=principal.user_id,
                text=body.text,
                kind=body.kind,
                context=body.context,
                tags=list(body.tags),
                agent_id=body.agent_id,
                importance=body.importance,
                confidence=body.confidence,
                valid_until=body.valid_until,
                source_role=body.source_role,
                review_status="confirmed" if self_asserted else "pending",
            )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    _drain(request)
    indexed, job_id = _outbox_state(conn, vectors.MEMORIES, memory_id)
    return MemoryCreatedOut(
        id=memory_id,
        stored=True,
        indexed=indexed,
        index_job_id=job_id,
        review_status="confirmed" if self_asserted else "pending",
    )


@router.patch("/v1/memories/{memory_id}")
def patch_memory(
    request: Request,
    memory_id: str,
    body: MemoryPatch,
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> EntityOut:
    memory_id = _memory_id(memory_id)
    current = conn.execute(
        "SELECT * FROM memories WHERE id=%s AND scope_id = ANY(%s)",
        (memory_id, principal.scopes()),
    ).fetchone()
    if current is None:
        raise HTTPException(404, "unknown memory")
    if not principal.may_write(str(current["scope_id"])):
        raise HTTPException(403, "memory is read-only for this user")
    context = dict(current["context"] or {})
    if body.context is not None and body.context != context and not body.move_context:
        raise HTTPException(422, "changing context requires move_context=true")
    scope_id = None
    if body.scope is not None:
        if not body.move_scope:
            raise HTTPException(422, "changing scope requires move_scope=true")
        scope_id = principal_module.resolve_scope(conn, principal, body.scope, write=True)
    subject_id = current["subject_id"]
    if body.clear_subject:
        subject_id = None
    elif body.subject is not None:
        subject_id = principal_module.resolve_subject(conn, principal, body.subject)
    valid_until = current["valid_until"]
    if body.clear_valid_until:
        valid_until = None
    elif body.valid_until is not None:
        valid_until = body.valid_until
    try:
        with conn.transaction():
            saved = store.update_memory(
                conn,
                memory_id=memory_id,
                scopes=sorted(principal.writable_scope_ids),
                expected_revision=body.expected_revision,
                text=body.text or str(current["text"]),
                kind=body.kind or str(current["kind"]),
                context=body.context if body.context is not None else context,
                tags=list(body.tags) if body.tags is not None else list(current["tags"] or []),
                importance=body.importance
                if body.importance is not None
                else float(current["importance"]),
                confidence=body.confidence
                if body.confidence is not None
                else float(current["confidence"]),
                valid_until=valid_until,
                subject_id=subject_id,
                scope_id=scope_id,
            )
    except KeyError as exc:
        raise HTTPException(404, "unknown memory") from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    _drain(request)
    return {
        "id": memory_id,
        "revision": int(saved["revision"]),
        "status": saved["status"],
        # An edit by the extractor returns a fact to review, so the caller has
        # to be told what it now is rather than refetching to find out.
        "review_status": saved["review_status"],
    }


@router.delete("/v1/memories/{memory_id}")
def delete_memory(
    request: Request,
    memory_id: str,
    expected_revision: int | None = Query(None, ge=1),
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> EntityOut:
    """Archive a memory. Reversible, because a mistaken delete is common.

    The precondition is optional here and required on a patch: archiving is
    reversible, so a lost race costs an undo rather than someone's wording.
    """
    memory_id = _memory_id(memory_id)
    try:
        with conn.transaction():
            saved = store.set_memory_status(
                conn,
                memory_id=memory_id,
                scopes=sorted(principal.writable_scope_ids),
                status="archived",
                expected_revision=expected_revision,
            )
    except KeyError as exc:
        raise HTTPException(404, "unknown memory") from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    _drain(request)
    return {"id": memory_id, "revision": int(saved["revision"]), "status": saved["status"]}


@router.post("/v1/memories/{memory_id}/restore")
def restore_memory(
    request: Request,
    memory_id: str,
    expected_revision: int | None = Query(None, ge=1),
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> EntityOut:
    memory_id = _memory_id(memory_id)
    try:
        with conn.transaction():
            saved = store.set_memory_status(
                conn,
                memory_id=memory_id,
                scopes=sorted(principal.writable_scope_ids),
                status="active",
                expected_revision=expected_revision,
            )
    except KeyError as exc:
        raise HTTPException(404, "unknown memory") from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    _drain(request)
    return {"id": memory_id, "revision": int(saved["revision"]), "status": saved["status"]}


@router.post("/v1/memories/{memory_id}/review")
def review_memory(
    request: Request,
    memory_id: str,
    body: ReviewIn,
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> EntityOut:
    """Confirm or delete an unreviewed memory, or undo that decision."""
    memory_id = _memory_id(memory_id)
    status = {"confirm": "confirmed", "decline": "declined", "undo": "pending"}[body.decision]
    try:
        with conn.transaction():
            saved = store.set_review_status(
                conn,
                memory_id=memory_id,
                scopes=sorted(principal.writable_scope_ids),
                review_status=status,
                reviewed_by=principal.user_id,
                expected_revision=body.expected_revision,
            )
    except KeyError as exc:
        raise HTTPException(404, "unknown memory") from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    _drain(request)
    return {
        "id": memory_id,
        "revision": int(saved["revision"]),
        "status": saved["status"],
        "review_status": saved["review_status"],
    }


@router.get("/v1/memories")
def list_memories(
    q: str | None = None,
    kind: str | None = None,
    status: str = "active",
    source_role: str | None = None,
    scope: str | None = None,
    subject: str | None = None,
    review_status: str | None = None,
    tag: str | None = None,
    importance_min: float | None = Query(None, ge=0, le=1),
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    sort: str = "updated_at",
    order: str = "desc",
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> MemoryPageOut:
    """Filterable, sortable listing with a real total.

    Ordered by recency by default. The previous implementation paged by uuid
    while the dashboard called the result "recent memories", so the list was in
    an arbitrary order that looked chronological.
    """
    if sort not in _SORTABLE:
        raise HTTPException(422, f"cannot sort by {sort!r}")
    direction = "DESC" if order.lower() == "desc" else "ASC"
    scopes = (
        [principal_module.resolve_scope(conn, principal, scope)] if scope else principal.scopes()
    )
    subject_id = principal_module.resolve_subject(conn, principal, subject) if subject else None
    params: dict[str, Any] = {
        "scopes": scopes,
        "status": status,
        "kind": kind,
        "source_role": source_role,
        "subject": subject_id,
        "review_status": review_status,
        "tag": tag,
        "importance_min": importance_min,
        "created_from": created_from,
        "created_to": created_to,
        "query": q,
        "limit": limit,
        "offset": offset,
    }
    where = """
        WHERE m.scope_id = ANY(%(scopes)s)
          AND (%(status)s::text IS NULL OR %(status)s = 'any' OR m.status = %(status)s)
          AND (%(kind)s::text IS NULL OR m.kind = %(kind)s)
          AND (%(source_role)s::text IS NULL OR m.source_role = %(source_role)s)
          AND (%(subject)s::uuid IS NULL OR m.subject_id = %(subject)s)
          AND (%(review_status)s::text IS NULL OR m.review_status = %(review_status)s)
          AND (%(tag)s::text IS NULL OR m.tags ? %(tag)s)
          AND (%(importance_min)s::real IS NULL OR m.importance >= %(importance_min)s)
          AND (%(created_from)s::timestamptz IS NULL OR m.created_at >= %(created_from)s)
          AND (%(created_to)s::timestamptz IS NULL OR m.created_at <= %(created_to)s)
          AND (
              %(query)s::text IS NULL
              OR m.search_tsv @@ plainto_tsquery('russian', %(query)s)
              OR m.text ILIKE '%%' || %(query)s || '%%'
          )
    """
    total_row = conn.execute(
        f"SELECT COUNT(*) AS n FROM memories m {where}",
        params,
    ).fetchone()
    rows = conn.execute(
        f"""SELECT m.*, sc.name AS scope_name, sc.slug AS scope_slug,
                   sub.name AS subject_name, sub.slug AS subject_slug,
                   u.handle AS author_handle
              FROM memories m
              JOIN entities sc ON sc.id = m.scope_id
              LEFT JOIN entities sub ON sub.id = m.subject_id
              LEFT JOIN users u ON u.id = m.author_id
              {where}
             ORDER BY {_SORTABLE[sort]} {direction}, m.id
             LIMIT %(limit)s OFFSET %(offset)s""",
        params,
    ).fetchall()
    items = []
    for row in rows:
        item = _memory_summary(row)
        item.update(
            {
                "scope_slug": row["scope_slug"],
                "subject": row["subject_name"],
                "subject_slug": row["subject_slug"],
                "author": row["author_handle"],
                "status": row["status"],
                "context": dict(row["context"] or {}),
                "tags": list(row["tags"] or []),
                "created_at": iso(row["created_at"]),
                "valid_until": iso(row["valid_until"]),
                "retrieval_count": int(row["retrieval_count"]),
                "last_retrieved_at": iso(row["last_retrieved_at"]),
            }
        )
        items.append(item)
    return {
        "items": items,
        "total": int(total_row["n"]) if total_row else 0,
        "limit": limit,
        "offset": offset,
    }


@router.get("/v1/memories/{memory_id}")
def get_memory(
    memory_id: str,
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> MemoryOut:
    """One memory, including `revision`.

    A correction is a PATCH carrying `expected_revision`, so an agent needs a
    way to read the current revision of a single fact. Search results carry it
    too, but an id learned from a profile block has nowhere else to come from.
    """
    memory_id = _memory_id(memory_id)
    row = conn.execute(
        """SELECT m.*, sc.name AS scope_name, sc.slug AS scope_slug,
                  sub.name AS subject_name, sub.slug AS subject_slug,
                  u.handle AS author_handle
             FROM memories m
             JOIN entities sc ON sc.id = m.scope_id
             LEFT JOIN entities sub ON sub.id = m.subject_id
             LEFT JOIN users u ON u.id = m.author_id
            WHERE m.id=%s AND m.scope_id = ANY(%s)""",
        (memory_id, principal.scopes()),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "unknown memory")
    memory = _memory_summary(row)
    memory.update(
        {
            "scope_slug": row["scope_slug"],
            "subject": row["subject_name"],
            "subject_slug": row["subject_slug"],
            "author": row["author_handle"],
            "status": row["status"],
            "context": dict(row["context"] or {}),
            "tags": list(row["tags"] or []),
            "created_at": iso(row["created_at"]),
            "valid_until": iso(row["valid_until"]),
            "judge_run_id": row["judge_run_id"],
            "extraction_version": row["extraction_version"],
            "writable": principal.may_write(str(row["scope_id"])),
            "sessions": [
                str(item["session_id"])
                for item in conn.execute(
                    """SELECT DISTINCT ms.session_id FROM memory_sources s
                         JOIN messages ms ON ms.id = s.message_id
                         JOIN sessions session ON session.id=ms.session_id
                        WHERE s.memory_id=%s AND session.scope_id=ANY(%s)""",
                    (memory_id, principal.scopes()),
                )
            ],
        }
    )
    return {"memory": memory}


@router.get("/v1/memories/{memory_id}/sources")
def memory_sources(
    memory_id: str,
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> MemorySourcesOut:
    memory_id = _memory_id(memory_id)
    memory = conn.execute(
        """SELECT m.*, sc.name AS scope_name, sc.slug AS scope_slug,
                  sub.name AS subject_name, sub.slug AS subject_slug
             FROM memories m
             JOIN entities sc ON sc.id = m.scope_id
             LEFT JOIN entities sub ON sub.id = m.subject_id
            WHERE m.id=%s AND m.scope_id = ANY(%s)""",
        (memory_id, principal.scopes()),
    ).fetchone()
    if memory is None:
        raise HTTPException(404, "unknown memory")
    # The span is verified here, not by the caller. It was returning the whole
    # cited message with the offsets and the hash and leaving the client to do
    # the check -- which shipped a transcript per span and made "verbatim" a
    # claim nobody was enforcing.
    evidence, historical = [], []
    for row in store.evidence_rows(conn, [memory_id], scope_ids=principal.scopes()):
        excerpt = str(row["content"])[row["start_char"] : row["end_char"]]
        target = evidence if row["current_evidence"] else historical
        target.append(
            {
                "message_id": int(row["message_id"]),
                "start_char": int(row["start_char"]),
                "end_char": int(row["end_char"]),
                "excerpt": excerpt,
                # False means the message moved under the citation. The span is
                # still reported, because its absence would read as "no
                # evidence" rather than "evidence that no longer checks out".
                "verified": (
                    0 <= row["start_char"] < row["end_char"] <= len(row["content"])
                    and hashlib.sha256(excerpt.encode()).hexdigest() == row["excerpt_sha256"]
                ),
                "role": row["role"],
                "created_at": iso(row["created_at"]),
                "supported_revisions": row["supported_revisions"],
                "evidence_status": (
                    "current"
                    if row["revision"]
                    else "historical"
                    if row["supported_revisions"]
                    else "legacy_unversioned"
                ),
            }
        )
    return {
        "memory": _memory_summary(memory),
        "source_role": str(memory["source_role"]),
        "evidence": evidence,
        "historical_evidence": historical,
    }


@router.get("/v1/memories/{memory_id}/history")
def memory_history(
    memory_id: str,
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> MemoryHistoryOut:
    memory_id = _memory_id(memory_id)
    memory = conn.execute(
        """SELECT m.*, sc.name AS scope_name, sc.slug AS scope_slug,
                  sub.name AS subject_name, sub.slug AS subject_slug
             FROM memories m
             JOIN entities sc ON sc.id = m.scope_id
             LEFT JOIN entities sub ON sub.id = m.subject_id
            WHERE m.id=%s AND m.scope_id = ANY(%s)""",
        (memory_id, principal.scopes()),
    ).fetchone()
    if memory is None:
        raise HTTPException(404, "unknown memory")
    revisions = [
        {
            "revision": int(row["revision"]),
            "text": row["text"],
            "kind": row["kind"],
            "status": row["status"],
            "review_status": row["review_status"],
            "importance": float(row["importance"]),
            "confidence": float(row["confidence"]),
            "context": dict(row["context"] or {}),
            "tags": list(row["tags"] or []),
            "source_role": row["source_role"],
            "extraction_version": row["extraction_version"],
            "created_at": iso(row["created_at"]),
        }
        for row in conn.execute(
            """SELECT * FROM memory_revisions WHERE memory_id=%s
               AND scope_id=ANY(%s) ORDER BY revision DESC""",
            (memory_id, principal.scopes()),
        )
    ]
    chain = """SELECT m.*, sc.name AS scope_name, sc.slug AS scope_slug,
                      sub.name AS subject_name, sub.slug AS subject_slug
                 FROM memories m
                 JOIN entities sc ON sc.id = m.scope_id
                 LEFT JOIN entities sub ON sub.id = m.subject_id
                WHERE {clause} AND m.scope_id=ANY(%s)"""
    predecessors = [
        _memory_summary(row)
        for row in conn.execute(
            chain.format(clause="m.superseded_by=%s"), (memory_id, principal.scopes())
        )
    ]
    successor_row = (
        conn.execute(
            chain.format(clause="m.id=%s"), (str(memory["superseded_by"]), principal.scopes())
        ).fetchone()
        if memory["superseded_by"]
        else None
    )
    return {
        "memory": _memory_summary(memory),
        "revisions": revisions,
        "predecessors": predecessors,
        "successor": _memory_summary(successor_row) if successor_row else None,
    }


@router.post("/v1/memories/search")
@router.post("/v1/search", include_in_schema=False)
def search_memories(
    request: Request,
    body: SearchIn,
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
    settings: Settings = Depends(get_settings),
) -> MemorySearchOut:
    if not getattr(request.app.state, "index_ready", False):
        raise HTTPException(503, "vector search dependency is temporarily unavailable")
    scopes = (
        [principal_module.resolve_scope(conn, principal, item) for item in body.scopes]
        if body.scopes
        else principal.scopes()
    )
    expression = body.filter
    if body.subject:
        subject_id = principal_module.resolve_subject(conn, principal, body.subject)
        subject_clause = {"field": "subject_id", "op": "eq", "value": subject_id}
        expression = {"all": [expression, subject_clause]} if expression else subject_clause
    try:
        policy = retrieval.load_policy(conn, body.policy_id)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    started = time.perf_counter()
    semantic = getattr(request.app.state, "semantic", None)
    assemble = bool(body.include_raw and semantic is not None and semantic.context != "off")
    raw = None
    try:
        result = retrieval.explain(
            conn,
            request.app.state.qdrant,
            request.app.state.embedder,
            query=body.query,
            scope_ids=scopes,
            expression=expression,
            kinds=body.kinds,
            limit=60 if assemble else body.limit,
            budget_tokens=120_000 if assemble else body.budget_tokens,
            policy=policy,
            include_untrusted=body.include_untrusted,
            reranker=None if assemble else getattr(request.app.state, "reranker", None),
        )
        if assemble:
            context_started = time.perf_counter()
            result, raw = context_assembly.assemble(
                conn,
                request.app.state.qdrant,
                result,
                query=body.query,
                scope_ids=scopes,
                expression=expression,
                kinds=body.kinds,
                budget_tokens=body.budget_tokens,
                limit=body.limit,
                select=lambda query, candidates: semantic.select_context(
                    query, candidates, budget_tokens=body.budget_tokens, max_results=body.limit
                ),
            )
            result.timings["context_ms"] = (time.perf_counter() - context_started) * 1000
            result.timings["total_ms"] = (time.perf_counter() - started) * 1000
        elif body.include_raw:
            raw = store.search_raw(
                conn,
                request.app.state.qdrant,
                request.app.state.embedder,
                query=body.query,
                scope_ids=scopes,
                limit=body.limit,
                vector=result.query_vector,
                expression=expression,
                kinds=body.kinds,
            )
            result.timings["total_ms"] = (time.perf_counter() - started) * 1000
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:
        request.app.state.index_ready = False
        request.app.state.index_error = str(exc)
        logger.warning("vector search failed; dependency monitor will reconnect")
        raise HTTPException(503, "vector search dependency is temporarily unavailable") from exc
    result.timings["request_ms"] = (time.perf_counter() - started) * 1000
    excerpts = (
        store.evidence_excerpts(conn, [item.id for item in result.chosen], scope_ids=scopes)
        if body.include_sources and result.chosen
        else {}
    )
    result, raw, selected_excerpts = context_assembly.pack_context(
        result, raw or [], excerpts, budget_tokens=body.budget_tokens, limit=body.limit
    )
    with conn.transaction():
        retrieval_id = telemetry.record_retrieval_run(
            conn,
            user_id=principal.user_id,
            query_hash=telemetry.hash_query(settings.telemetry_hmac_key, body.query),
            policy_id=result.policy_id,
            results=[item.as_dict() for item in result.chosen],
            timings=result.timings,
            used_tokens=result.used_tokens,
            has_evidence=bool(raw),
        )
        if result.chosen:
            store.record_retrieval(conn, [item.id for item in result.chosen])
    payload = result.as_dict()
    if body.include_sources and result.chosen:
        for memory in payload["memories"]:
            memory["sources"] = selected_excerpts.get(memory["id"], [])
    return {**payload, "raw": raw or [], "retrieval_id": retrieval_id}


@router.post("/v1/retrieval-feedback", status_code=201)
def retrieval_feedback(
    body: FeedbackIn,
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
    settings: Settings = Depends(get_settings),
) -> FeedbackOut:
    row = conn.execute(
        "SELECT 1 FROM memories WHERE id=%s AND scope_id = ANY(%s)",
        (body.memory_id, principal.scopes()),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "unknown memory")
    with conn.transaction():
        store.record_feedback(
            conn,
            memory_id=body.memory_id,
            query_hash=telemetry.hash_query(settings.telemetry_hmac_key, body.query),
            useful=body.useful,
            correct=body.correct,
        )
    return {"recorded": True}


@router.post("/v1/retrieval-runs/{retrieval_id}/feedback", status_code=201)
def retrieval_run_feedback(
    retrieval_id: str,
    body: RetrievalRunFeedbackIn,
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> FeedbackOut:
    try:
        with conn.transaction():
            telemetry.record_run_feedback(
                conn,
                retrieval_id=retrieval_id,
                user_id=principal.user_id,
                memory_id=body.memory_id,
                useful=body.useful,
                correct=body.correct,
            )
    except LookupError as exc:
        raise HTTPException(404, "unknown retrieval run") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"recorded": True}


@router.get("/v1/retrieval-runs")
def recent_retrieval_runs(
    limit: int = Query(20, ge=1, le=100),
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> RetrievalRunsOut:
    return {
        "items": telemetry.recent_runs(
            conn,
            user_id=principal.user_id,
            allowed_scope_ids=principal.scopes(),
            limit=limit,
        )
    }


@router.get("/v1/review")
def review_queue(
    kind: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
    settings: Settings = Depends(get_settings),
) -> ReviewQueueOut:
    """Everything waiting on a person.

    Four different things share one queue because they share one question --
    "is this right?" -- and splitting them across screens is how a queue stops
    being read. Pending memories are found by their review status rather than
    duplicated into a work table, so confirming one cannot leave a stale row.
    """
    items: list[dict[str, Any]] = []
    if kind in (None, "memory"):
        rows = conn.execute(
            """SELECT m.*, sc.name AS scope_name, sc.slug AS scope_slug,
                      sub.name AS subject_name, u.handle AS author_handle,
                      prev.text AS previous_text
                 FROM memories m
                 JOIN entities sc ON sc.id = m.scope_id
                 LEFT JOIN entities sub ON sub.id = m.subject_id
                 LEFT JOIN users u ON u.id = m.author_id
                 LEFT JOIN memory_revisions prev
                        ON prev.memory_id = m.id AND prev.revision = m.revision - 1
                       AND prev.scope_id=ANY(%s)
                WHERE m.scope_id = ANY(%s) AND m.status='active'
                  AND m.review_status='pending'
                ORDER BY m.created_at DESC
                LIMIT %s OFFSET %s""",
            (principal.scopes(), principal.scopes(), limit, offset),
        ).fetchall()
        for row in rows:
            item = _memory_summary(row)
            items.append(
                {
                    "id": str(row["id"]),
                    "kind": "memory",
                    "title": row["text"],
                    "memory": item,
                    "author": row["author_handle"],
                    "subject": row["subject_name"],
                    # An update to a confirmed fact keeps the new text live and
                    # returns for review, so the reviewer needs the old wording.
                    "previous_text": row["previous_text"],
                    "created_at": iso(row["created_at"]),
                    "actions": ["confirm", "decline"],
                }
            )
    if kind in (None, "unresolved_mention", "conflict"):
        rows = conn.execute(
            """SELECT n.*, m.text AS memory_text FROM needs_attention n
                 LEFT JOIN memories m ON m.id = n.ref_memory_id
                   AND m.scope_id = ANY(%s)
                WHERE n.user_id=%s AND n.status='open'
                  AND n.kind = ANY(%s)
                ORDER BY n.created_at DESC LIMIT %s OFFSET %s""",
            (
                principal.scopes(),
                principal.user_id,
                ["unresolved_mention", "conflict"] if kind is None else [kind],
                limit,
                offset,
            ),
        ).fetchall()
        for row in rows:
            payload = dict(row["payload"] or {})
            items.append(
                {
                    "id": str(row["id"]),
                    "kind": row["kind"],
                    "title": payload.get("name") or row["memory_text"] or "",
                    "detail": row["memory_text"],
                    "memory_id": str(row["ref_memory_id"]) if row["ref_memory_id"] else None,
                    "payload": payload,
                    "created_at": iso(row["created_at"]),
                    "actions": ["link_entity", "dismiss"],
                }
            )
    if kind in (None, "failed_job"):
        rows = conn.execute(
            """SELECT j.* FROM jobs j
                WHERE j.status='failed' AND j.created_at > now() - interval '7 days'
                  AND (j.user_id = %s OR %s)
                  AND NOT EXISTS (
                      SELECT 1 FROM needs_attention n
                       WHERE n.ref_job_id = j.id AND n.status='resolved'
                  )
                ORDER BY j.created_at DESC LIMIT %s""",
            (principal.user_id, principal.is_admin, limit),
        ).fetchall()
        for row in rows:
            items.append(
                {
                    "id": str(row["id"]),
                    "kind": "failed_job",
                    "title": f"{row['kind']} job failed",
                    "detail": row["error"],
                    "error_code": row["error_code"],
                    "created_at": iso(row["created_at"]),
                    "actions": ["dismiss"],
                }
            )
    if principal.is_admin and kind in (None, "budget"):
        spend = float(
            (
                conn.execute(
                    """SELECT COALESCE(SUM(cost_usd),0) AS s FROM judge_runs
                        WHERE to_char(created_at AT TIME ZONE 'UTC','YYYY-MM') = %s""",
                    (datetime.now(UTC).strftime("%Y-%m"),),
                ).fetchone()
                or {"s": 0}
            )["s"]
        )
        limit_usd = settings.monthly_cost_limit_usd
        dismissed = conn.execute(
            """SELECT 1 FROM needs_attention
                WHERE user_id=%s AND kind='budget' AND status='resolved'
                  AND to_char(resolved_at AT TIME ZONE 'UTC','YYYY-MM')
                      = to_char(now() AT TIME ZONE 'UTC','YYYY-MM')""",
            (principal.user_id,),
        ).fetchone()
        if limit_usd and spend >= limit_usd * 0.8 and dismissed is None:
            items.append(
                {
                    "id": "budget",
                    "kind": "budget",
                    "title": f"Model spend is at {spend / limit_usd:.0%} of the monthly limit",
                    "detail": f"{spend:.2f} of {limit_usd:.2f} USD",
                    "created_at": iso(utcnow()),
                    "actions": ["dismiss"],
                }
            )
    return {"items": items}


def _dismiss_computed(
    conn: psycopg.Connection,
    principal: Principal,
    item_id: str,
    body: AttentionResolveIn,
) -> dict[str, Any]:
    """Close a queue item that had no row until now.

    The review queue reads failed jobs and the budget warning straight from
    live state, so dismissing one has to write the row that suppresses it. The
    queue's own `NOT EXISTS` clause is what then hides it.
    """
    if body.action != "dismiss":
        raise HTTPException(404, "unknown or already resolved item")
    kind = "budget" if item_id == "budget" else "failed_job"
    job_id: str | None = None
    if kind == "failed_job":
        try:
            job_id = str(uuid.UUID(item_id))
        except ValueError as exc:
            raise HTTPException(404, "unknown or already resolved item") from exc
        job = conn.execute(
            """SELECT id FROM jobs
                WHERE id=%s AND status='failed'
                  AND (user_id = %s OR %s)""",
            (job_id, principal.user_id, principal.is_admin),
        ).fetchone()
        if job is None:
            raise HTTPException(404, "unknown or already resolved item")
    with conn.transaction():
        conn.execute(
            """INSERT INTO needs_attention
               (id,user_id,kind,ref_job_id,payload,status,resolved_at,resolved_by)
               VALUES (%s,%s,%s,%s,%s,'resolved',now(),%s)""",
            (
                str(uuid.uuid4()),
                principal.user_id,
                kind,
                job_id,
                Jsonb({"dismissed": item_id}),
                principal.user_id,
            ),
        )
    return {"id": item_id, "status": "resolved", "action": "dismiss"}


@router.post("/v1/attention/{item_id}/resolve")
def resolve_attention(
    request: Request,
    item_id: str,
    body: AttentionResolveIn,
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> FlexibleOut:
    """Place an unresolved name, or dismiss the item.

    Linking attributes the memory to a visible entity. It also teaches the
    alias when the caller can edit that entity; `alias_taught` reports that
    additional change explicitly.
    """
    row = conn.execute(
        "SELECT * FROM needs_attention WHERE id=%s AND user_id=%s AND status='open'",
        (item_id, principal.user_id),
    ).fetchone()
    if row is None:
        # A failed job and a budget warning are computed from live state rather
        # than stored, so there is no row to close until somebody dismisses
        # one. Both advertise `dismiss` in the queue; recording the dismissal
        # is what makes that true instead of a 404.
        return _dismiss_computed(conn, principal, item_id, body)

    resolution: dict[str, Any] = {"action": body.action}
    with conn.transaction():
        maintenance.require_write(conn)
        if body.action == "link_entity":
            if not body.entity:
                raise HTTPException(422, "link_entity requires an entity")
            principal_module.resolve_subject(conn, principal, body.entity)
            target = entities.by_slug(conn, body.entity)
            if target is None:
                raise HTTPException(404, "unknown entity")
            name = str((row["payload"] or {}).get("name") or "")
            if row["ref_memory_id"] is not None:
                memory = conn.execute(
                    "SELECT * FROM memories WHERE id=%s", (str(row["ref_memory_id"]),)
                ).fetchone()
                if memory is not None:
                    team = entities.team(conn)
                    store.update_memory(
                        conn,
                        memory_id=str(memory["id"]),
                        scopes=sorted(principal.writable_scope_ids),
                        expected_revision=int(memory["revision"]),
                        text=str(memory["text"]),
                        kind=str(memory["kind"]),
                        context=dict(memory["context"] or {}),
                        tags=list(memory["tags"] or []),
                        importance=float(memory["importance"]),
                        confidence=float(memory["confidence"]),
                        valid_until=memory["valid_until"],
                        subject_id=str(target["id"]),
                        # A fact about a person belongs where the team can see
                        # it, which is what routing would have done had the
                        # name resolved at extraction time.
                        scope_id=str(team["id"]) if team and target["kind"] == "user" else None,
                    )
            if name and (principal.may_write(str(target["id"])) or principal.is_admin):
                entities.add_aliases(conn, entity_id=str(target["id"]), aliases=[name])
                resolution["alias_taught"] = name
            resolution["entity_id"] = str(target["id"])
        conn.execute(
            """UPDATE needs_attention
                  SET status='resolved',resolved_at=now(),resolved_by=%s,
                      payload = payload || %s
                WHERE id=%s""",
            (principal.user_id, Jsonb({"resolution": resolution}), item_id),
        )
    _drain(request)
    return {"id": item_id, "status": "resolved", **resolution}


@router.post("/v1/profiles/render")
def render_profile(
    body: ProfileIn,
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> ProfileOut:
    """The block an agent injects at the start of a session."""
    project_scope_id = None
    if body.workspace:
        # An unknown or inaccessible workspace is not an error here: a hook
        # sends whatever repository it is in, and a session that happens not to
        # map to an entity should still get the rest of the profile.
        with suppress(ScopeForbidden, UnknownScope):
            project_scope_id = principal_module.resolve_scope(conn, principal, body.workspace)
    rendered = profiles.render(
        conn,
        own_scope_id=principal.own_entity_id,
        team_scope_id=principal.team_entity_id,
        allowed_scope_ids=principal.scopes(),
        project_scope_id=project_scope_id,
        dynamic_days=body.dynamic_days,
        budget_tokens=body.budget_tokens,
        blocks=body.blocks,
        include_untrusted=body.include_untrusted,
    )
    # What the workspace resolved to, named here rather than inferred from the
    # project block: that block is empty exactly when a scope is new, which is
    # when a client most needs to tell the user where their words are going.
    scope = (
        conn.execute(
            "SELECT slug,name FROM entities WHERE id=%s",
            (project_scope_id or principal.own_entity_id,),
        ).fetchone()
        or {}
    )
    rendered["scope"] = {
        "slug": scope.get("slug"),
        "name": scope.get("name"),
        "shared": bool(project_scope_id) and project_scope_id != principal.own_entity_id,
    }
    return rendered
