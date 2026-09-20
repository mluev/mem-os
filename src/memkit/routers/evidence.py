"""Evidence HTTP endpoints."""

from __future__ import annotations

import logging
from typing import Any

import psycopg
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
)

from .. import (
    extract,
    maintenance,
    store,
    vectors,
)
from .. import (
    principal as principal_module,
)
from ..config import Settings, get_settings
from ..http import _outbox_state, _wake_worker, get_conn, get_principal, judge_configured
from ..job_runner import queue_extraction as _queue_extraction
from ..principal import Principal
from ..schemas import BatchOut, EvidenceBatchIn, JobQueuedOut, MessageIn, MessageOut

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/v1/evidence/events", status_code=201)
@router.post("/v1/messages", status_code=201, include_in_schema=False)
def post_message(
    request: Request,
    body: MessageIn,
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
    settings: Settings = Depends(get_settings),
) -> MessageOut:
    scope_id = (
        principal_module.resolve_scope(conn, principal, body.scope, write=True)
        if body.scope
        else principal_module.scope_for_workspace(
            conn, principal, str(body.context.get("source_workspace") or "")
        )
    )
    try:
        with conn.transaction():
            message_id, deduplicated, redacted = store.add_message(
                conn,
                session_id=body.session_id,
                user_id=principal.user_id,
                scope_id=scope_id,
                agent_id=body.agent_id,
                role=body.role,
                content=body.content,
                external_source=body.external_source,
                external_id=body.external_id,
                context=body.context,
                created_at=body.created_at,
                strict_scope=body.scope is not None,
            )
    except store.SessionNotAvailable as exc:
        raise HTTPException(404, "unknown session") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    # Indexing is the worker's job. Draining inline made the response wait for
    # one embedding per queued row, so a hundred-event hook batch blocked the
    # request for seconds. The response reports `indexed` separately from
    # `stored`, which is what that distinction is for.
    _wake_worker(request)
    indexed, index_job_id = _outbox_state(conn, vectors.RAW, message_id)
    applicable = body.role == "user" and len(body.content) >= store.MIN_INDEX_CHARS
    extraction_job_id = None
    pending = extract.messages_since_last(conn, body.session_id)
    if judge_configured(settings) and extract.judge.should_extract(
        messages_since_last=pending,
        session_closed=False,
        text=body.content,
    ):
        with conn.transaction():
            extraction_job_id = _queue_extraction(
                conn,
                session_id=body.session_id,
                agent_id=body.agent_id,
                force=True,
                pending=pending,
                user_id=principal.user_id,
            )
        _wake_worker(request)
    return MessageOut(
        message_id=message_id,
        indexed=indexed if applicable else True,
        index_status=("complete" if indexed else "pending") if applicable else "not_applicable",
        index_job_id=index_job_id,
        extraction_job_id=extraction_job_id,
        deduplicated=deduplicated,
        redacted=redacted,
    )


@router.post("/v1/evidence/events:batch", status_code=201)
def post_evidence_batch(
    request: Request,
    body: EvidenceBatchIn,
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
    settings: Settings = Depends(get_settings),
) -> BatchOut:
    stored: list[tuple[MessageIn, int, bool, bool]] = []
    try:
        with conn.transaction():
            for event in body.events:
                scope_id = (
                    principal_module.resolve_scope(conn, principal, event.scope, write=True)
                    if event.scope
                    else principal_module.scope_for_workspace(
                        conn, principal, str(event.context.get("source_workspace") or "")
                    )
                )
                message_id, duplicate, redacted = store.add_message(
                    conn,
                    session_id=event.session_id,
                    user_id=principal.user_id,
                    scope_id=scope_id,
                    agent_id=event.agent_id,
                    role=event.role,
                    content=event.content,
                    external_source=event.external_source,
                    external_id=event.external_id,
                    context=event.context,
                    created_at=event.created_at,
                    strict_scope=event.scope is not None,
                )
                stored.append((event, message_id, duplicate, redacted))
    except store.SessionNotAvailable as exc:
        raise HTTPException(404, "unknown session") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    _wake_worker(request)
    results: list[dict[str, Any]] = []
    queued_sessions: set[tuple[str, str]] = set()
    for event, message_id, duplicate, redacted in stored:
        applicable = event.role == "user" and len(event.content) >= store.MIN_INDEX_CHARS
        indexed, index_job_id = _outbox_state(conn, vectors.RAW, message_id)
        results.append(
            MessageOut(
                message_id=message_id,
                indexed=indexed if applicable else True,
                index_status=("complete" if indexed else "pending")
                if applicable
                else "not_applicable",
                index_job_id=index_job_id,
                deduplicated=duplicate,
                redacted=redacted,
            ).model_dump()
        )
        queued_sessions.add((event.session_id, event.agent_id))
    if judge_configured(settings):
        with conn.transaction():
            for session_id, agent_id in sorted(queued_sessions):
                _queue_extraction(
                    conn,
                    session_id=session_id,
                    agent_id=agent_id,
                    force=False,
                    pending=extract.messages_since_last(conn, session_id),
                    user_id=principal.user_id,
                )
        _wake_worker(request)
    return {"items": results, "count": len(results)}


@router.post("/v1/sessions/{session_id}/close", status_code=202)
def close_session(
    request: Request,
    session_id: str,
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
    settings: Settings = Depends(get_settings),
) -> JobQueuedOut:
    row = conn.execute(
        "SELECT user_id,agent_id,scope_id FROM sessions WHERE id=%s", (session_id,)
    ).fetchone()
    if row is None or str(row["user_id"]) != principal.user_id:
        raise HTTPException(404, "unknown session")
    with conn.transaction():
        maintenance.require_write(conn)
        store.require_scope_write(conn, user_id=principal.user_id, scope_id=str(row["scope_id"]))
        conn.execute(
            "UPDATE sessions SET ended_at=COALESCE(ended_at, now()) WHERE id=%s", (session_id,)
        )
    if not judge_configured(settings):
        return {"job_id": None, "status": "complete", "reason": "judge_not_configured"}
    with conn.transaction():
        job_id = _queue_extraction(
            conn,
            session_id=session_id,
            agent_id=str(row["agent_id"]),
            force=True,
            pending=extract.messages_since_last(conn, session_id),
            user_id=principal.user_id,
        )
    _wake_worker(request)
    return {"job_id": job_id, "status": "queued"}
