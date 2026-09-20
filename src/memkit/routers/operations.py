"""Operations HTTP endpoints."""

from __future__ import annotations

import logging
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path

import psycopg
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
)
from fastapi.responses import FileResponse, JSONResponse

from .. import (
    jobs,
    operations,
    outbox,
    policies,
    stats,
    telemetry,
    vectors,
)
from .. import (
    principal as principal_module,
)
from ..config import Settings, get_settings
from ..db import iso
from ..http import _memory_summary, _wake_worker, get_conn, get_principal, require_admin
from ..principal import Principal
from ..schemas import (
    AdminHealthOut,
    BackupsOut,
    ConsolidateIn,
    EntityOut,
    EntityStatsOut,
    HealthOut,
    ItemsOut,
    JobOut,
    JobQueuedOut,
    JobsOut,
    JudgeRunOut,
    JudgeRunsOut,
    MemoryStatsOut,
    MetricsOut,
    PeopleStatsOut,
    PipelineStatsOut,
    PolicyIn,
    ReadyOut,
    ReplayIn,
    RetrievalStatsOut,
    ReviewStatsOut,
    SessionMemoriesOut,
    SessionMessagesOut,
    SessionsOut,
)

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/healthz")
def healthz() -> HealthOut:
    return {"ok": True}


@router.get("/readyz", response_model=ReadyOut)
def readyz(
    request: Request,
) -> JSONResponse:
    database_ok = qdrant_ok = embedder_ok = False
    try:
        with request.app.state.db.borrow() as conn:
            row = conn.execute("SELECT 1 AS ok").fetchone()
        database_ok = bool(row and row["ok"] == 1)
        qdrant_ok = bool(getattr(request.app.state, "index_ready", False))
        embedder_ok = bool(request.app.state.embedder.ready)
    except Exception:
        pass
    ready = database_ok and qdrant_ok and embedder_ok
    return JSONResponse(
        status_code=200 if ready else 503,
        content={
            "ready": ready,
            "database": database_ok,
            "qdrant": qdrant_ok,
            "embedder": embedder_ok,
        },
    )


@router.get("/v1/policies")
def list_policies(
    kind: str | None = None,
    scope: str | None = None,
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> ItemsOut:
    scope_id = principal_module.resolve_scope(conn, principal, scope) if scope else None
    rows = policies.list_policies(conn, scope_id=scope_id, kind=kind)
    return {
        "items": [
            {
                "id": row["id"],
                "scope_id": str(row["scope_id"]) if row["scope_id"] else None,
                "kind": row["kind"],
                "name": row["name"],
                "version": int(row["version"]),
                "config": dict(row["config"] or {}),
                "created_at": iso(row["created_at"]),
            }
            for row in rows
        ]
    }


@router.post("/v1/policies", status_code=201)
def create_policy(
    body: PolicyIn,
    principal: Principal = Depends(require_admin),
    conn: psycopg.Connection = Depends(get_conn),
) -> EntityOut:
    scope_id = (
        principal_module.resolve_scope(conn, principal, body.scope, write=True)
        if body.scope
        else None
    )
    try:
        with conn.transaction():
            policy_id = policies.put_policy(
                conn,
                scope_id=scope_id,
                kind=body.kind,
                name=body.name,
                version=body.version,
                config=body.config,
            )
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"id": policy_id}


@router.post("/v1/export", status_code=202)
def export_data(
    request: Request,
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> JobQueuedOut:
    """Export everything this user owns or authored."""
    with conn.transaction():
        job_id = jobs.create(
            conn,
            kind="export",
            input_data={
                "user_id": principal.user_id,
                "private_scope_id": principal.own_entity_id,
                "authored_scopes": principal.scopes(),
            },
            user_id=principal.user_id,
        )
    _wake_worker(request)
    return {"job_id": job_id, "status": "queued"}


@router.post("/v1/admin/reindex", status_code=202)
def start_reindex(
    request: Request,
    principal: Principal = Depends(require_admin),
    conn: psycopg.Connection = Depends(get_conn),
) -> JobQueuedOut:
    with conn.transaction():
        job_id = jobs.create(conn, kind="reindex", user_id=principal.user_id)
    _wake_worker(request)
    return {"job_id": job_id, "status": "queued"}


@router.post("/v1/admin/consolidate", status_code=202)
def start_consolidation(
    request: Request,
    body: ConsolidateIn,
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> JobQueuedOut:
    """Consolidate the caller's scopes, or every scope for an administrator."""
    scope_ids = (
        [str(row["id"]) for row in conn.execute("SELECT id FROM entities")]
        if principal.is_admin
        else sorted(principal.writable_scope_ids)
    )
    with conn.transaction():
        job_id = jobs.create(
            conn,
            kind="consolidation",
            input_data={
                "scope_ids": scope_ids,
                "dry_run": body.dry_run,
                "merge": body.merge,
            },
            call_limit=0 if body.dry_run else 20,
            user_id=principal.user_id,
        )
    _wake_worker(request)
    return {"job_id": job_id, "status": "queued"}


@router.post("/v1/admin/reextract", status_code=202)
def start_reextract_report(
    request: Request,
    body: ReplayIn | None = None,
    principal: Principal = Depends(require_admin),
    conn: psycopg.Connection = Depends(get_conn),
) -> JobQueuedOut:
    """Plan a re-extraction. Reports only; it never rewrites the store."""
    del body
    with conn.transaction():
        job_id = jobs.create(
            conn,
            kind="reextract_report",
            input_data={"scope_ids": sorted(principal.writable_scope_ids)},
            user_id=principal.user_id,
        )
    _wake_worker(request)
    return {"job_id": job_id, "status": "queued"}


@router.get("/v1/jobs")
def list_jobs(
    status: str | None = None,
    kind: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> JobsOut:
    rows = conn.execute(
        """SELECT j.*, u.handle AS user_handle FROM jobs j
             LEFT JOIN users u ON u.id = j.user_id
            WHERE (%s::text IS NULL OR j.status=%s)
              AND (%s::text IS NULL OR j.kind=%s)
              AND (j.user_id = %s OR %s)
            ORDER BY j.created_at DESC LIMIT %s""",
        (status, status, kind, kind, principal.user_id, principal.is_admin, limit),
    ).fetchall()
    return {
        "items": [
            {
                "id": str(row["id"]),
                "kind": row["kind"],
                "status": row["status"],
                "user": row["user_handle"],
                "error": row["error"],
                "error_code": row["error_code"],
                "result": row["result"],
                "created_at": iso(row["created_at"]),
                "finished_at": iso(row["finished_at"]),
            }
            for row in rows
        ]
    }


@router.get(
    "/v1/jobs/{job_id}/download",
    response_class=FileResponse,
    responses={
        200: {"content": {"application/json": {"schema": {"type": "string", "format": "binary"}}}}
    },
)
def download_export(
    job_id: str,
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    """Download an export owned by this caller, never an arbitrary server path."""
    try:
        row = jobs.get(conn, job_id)
    except KeyError as exc:
        raise HTTPException(404, "unknown export") from exc
    # Even administrators cannot download another person's private export.
    if row["kind"] != "export" or str(row["user_id"]) != principal.user_id:
        raise HTTPException(404, "unknown export")
    if row["status"] != "complete":
        raise HTTPException(409, "export is not complete")
    result = row.get("result") or {}
    raw_path = result.get("path")
    if not isinstance(raw_path, str):
        raise HTTPException(404, "export artifact unavailable")
    path = Path(raw_path).resolve()
    root = settings.export_dir.expanduser().resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise HTTPException(404, "export artifact unavailable")
    return FileResponse(
        path,
        media_type="application/json",
        filename=f"memos-export-{job_id}.json",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.get("/v1/jobs/{job_id}")
def get_job(
    job_id: str,
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> JobOut:
    try:
        row = jobs.get(conn, job_id)
    except KeyError as exc:
        raise HTTPException(404, "unknown job") from exc
    if str(row["user_id"]) != principal.user_id and not principal.is_admin:
        raise HTTPException(404, "unknown job")
    return {
        "id": str(row["id"]),
        "kind": row["kind"],
        "status": row["status"],
        "result": row["result"],
        "error": row["error"],
        "error_code": row["error_code"],
        "created_at": iso(row["created_at"]),
        "finished_at": iso(row["finished_at"]),
        "events": jobs.history(conn, job_id),
    }


@router.post("/v1/jobs/{job_id}/cancel", status_code=202)
def cancel_job(
    job_id: str,
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> JobQueuedOut:
    try:
        row = jobs.get(conn, job_id)
    except KeyError as exc:
        raise HTTPException(404, "unknown job") from exc
    if str(row["user_id"]) != principal.user_id and not principal.is_admin:
        raise HTTPException(404, "unknown job")
    try:
        with conn.transaction():
            jobs.request_cancel(conn, job_id)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"job_id": job_id, "status": "cancel_requested"}


@router.get("/v1/admin/sessions")
def list_sessions(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> SessionsOut:
    """Conversations, with what each one produced.

    Administrators see the instance; everyone else sees their own, because a
    transcript is the rawest thing the system holds.
    """
    total = conn.execute(
        """SELECT COUNT(*) AS n FROM sessions
            WHERE user_id = %s OR %s""",
        (principal.user_id, principal.is_admin),
    ).fetchone()
    rows = conn.execute(
        """SELECT s.*, u.handle AS user_handle, e.name AS scope_name, e.slug AS scope_slug,
                  (SELECT COUNT(*) FROM messages m WHERE m.session_id = s.id) AS messages,
                  (SELECT COUNT(DISTINCT ms.memory_id) FROM memory_sources ms
                     JOIN messages m2 ON m2.id = ms.message_id
                    WHERE m2.session_id = s.id) AS extracted
             FROM sessions s
             JOIN users u ON u.id = s.user_id
             JOIN entities e ON e.id = s.scope_id
            WHERE s.user_id = %s OR %s
            ORDER BY s.started_at DESC LIMIT %s OFFSET %s""",
        (principal.user_id, principal.is_admin, limit, offset),
    ).fetchall()
    return {
        "items": [
            {
                "id": row["id"],
                "user": row["user_handle"],
                "scope": row["scope_name"],
                "scope_slug": row["scope_slug"],
                "agent_id": row["agent_id"],
                "started_at": iso(row["started_at"]),
                "ended_at": iso(row["ended_at"]),
                "context": dict(row["context"] or {}),
                "messages": int(row["messages"]),
                "extracted": int(row["extracted"]),
            }
            for row in rows
        ],
        "total": int(total["n"]) if total else 0,
        "limit": limit,
        "offset": offset,
    }


@router.get("/v1/admin/sessions/{session_id}/messages")
def list_session_messages(
    session_id: str,
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> SessionMessagesOut:
    session = conn.execute("SELECT * FROM sessions WHERE id=%s", (session_id,)).fetchone()
    if session is None or (str(session["user_id"]) != principal.user_id and not principal.is_admin):
        raise HTTPException(404, "unknown session")
    total = conn.execute(
        "SELECT COUNT(*) AS n FROM messages WHERE session_id=%s", (session_id,)
    ).fetchone()
    rows = conn.execute(
        """SELECT * FROM messages WHERE session_id=%s ORDER BY id LIMIT %s OFFSET %s""",
        (session_id, limit, offset),
    ).fetchall()
    return {
        "session": {
            "id": session["id"],
            "user_id": str(session["user_id"]),
            "scope_id": str(session["scope_id"]),
            "agent_id": session["agent_id"],
            "started_at": iso(session["started_at"]),
            "ended_at": iso(session["ended_at"]),
        },
        "items": [
            {
                "id": int(row["id"]),
                "role": row["role"],
                "content": row["content"],
                "created_at": iso(row["created_at"]),
                "processed": bool(row["processed"]),
                "redacted": bool(row["redacted"]),
            }
            for row in rows
        ],
        "total": int(total["n"]) if total else 0,
        "limit": limit,
        "offset": offset,
    }


@router.get("/v1/admin/sessions/{session_id}/memories")
def list_session_memories(
    session_id: str,
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> SessionMemoriesOut:
    """What this conversation produced, and what it refused to produce.

    The rejections matter as much as the facts: they are the only place the
    reason a plausible-looking claim was dropped is visible.
    """
    session = conn.execute("SELECT * FROM sessions WHERE id=%s", (session_id,)).fetchone()
    if session is None or (str(session["user_id"]) != principal.user_id and not principal.is_admin):
        raise HTTPException(404, "unknown session")
    rows = conn.execute(
        """SELECT DISTINCT m.*, sc.name AS scope_name FROM memories m
             JOIN entities sc ON sc.id = m.scope_id
             JOIN memory_sources ms ON ms.memory_id = m.id
             JOIN messages msg ON msg.id = ms.message_id
            WHERE msg.session_id = %s AND m.scope_id = ANY(%s)
            ORDER BY m.created_at""",
        (session_id, principal.scopes()),
    ).fetchall()
    memories = []
    for row in rows:
        item = _memory_summary(row)
        item["evidence"] = [
            {
                "message_id": int(span["message_id"]),
                "start_char": int(span["start_char"]),
                "end_char": int(span["end_char"]),
            }
            for span in conn.execute(
                "SELECT * FROM memory_evidence WHERE memory_id=%s ORDER BY message_id,start_char",
                (str(row["id"]),),
            )
        ]
        memories.append(item)
    extraction_jobs = conn.execute(
        """SELECT id,status,result,error,created_at FROM jobs
            WHERE kind='extraction' AND input->>'session_id' = %s
            ORDER BY created_at""",
        (session_id,),
    ).fetchall()
    return {
        "items": memories,
        **{
            "jobs": [
                {
                    "id": str(job["id"]),
                    "status": job["status"],
                    "result": job["result"],
                    "error": job["error"],
                    "created_at": iso(job["created_at"]),
                }
                for job in extraction_jobs
            ]
        },
    }


@router.get("/v1/admin/judge-runs")
def list_judge_runs(
    limit: int = Query(50, ge=1, le=200),
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> JudgeRunsOut:
    rows = conn.execute(
        """SELECT j.id,j.kind,j.model,j.prompt_version,j.error,j.input_tokens,j.output_tokens,
                  j.cost_usd,j.latency_ms,j.created_at,u.handle AS user_handle
             FROM judge_runs j LEFT JOIN users u ON u.id = j.user_id
            WHERE j.user_id = %s OR %s
            ORDER BY j.created_at DESC LIMIT %s""",
        (principal.user_id, principal.is_admin, limit),
    ).fetchall()
    return {
        "items": [
            {
                "id": int(row["id"]),
                "kind": row["kind"],
                "model": row["model"],
                "prompt_version": row["prompt_version"],
                "error": row["error"],
                "input_tokens": row["input_tokens"],
                "output_tokens": row["output_tokens"],
                "cost_usd": float(row["cost_usd"]) if row["cost_usd"] is not None else None,
                "latency_ms": row["latency_ms"],
                "user": row["user_handle"],
                "created_at": iso(row["created_at"]),
            }
            for row in rows
        ]
    }


@router.get("/v1/admin/judge-runs/{run_id}")
def get_judge_run(
    run_id: int,
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> JudgeRunOut:
    row = conn.execute("SELECT * FROM judge_runs WHERE id=%s", (run_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "unknown judge run")
    if str(row["user_id"]) != principal.user_id and not principal.is_admin:
        raise HTTPException(404, "unknown judge run")
    return {
        "id": int(row["id"]),
        "kind": row["kind"],
        "model": row["model"],
        "prompt_version": row["prompt_version"],
        "input": row["input"],
        "output": row["output"],
        "error": row["error"],
        "input_tokens": row["input_tokens"],
        "output_tokens": row["output_tokens"],
        "cost_usd": float(row["cost_usd"]) if row["cost_usd"] is not None else None,
        "latency_ms": row["latency_ms"],
        "created_at": iso(row["created_at"]),
    }


@router.get("/v1/admin/health")
def admin_health(
    request: Request,
    principal: Principal = Depends(require_admin),
    conn: psycopg.Connection = Depends(get_conn),
) -> AdminHealthOut:
    index_ready = getattr(request.app.state, "index_ready", False)
    memory_count = raw_count = None
    if index_ready:
        try:
            memory_count = vectors.count(request.app.state.qdrant, vectors.MEMORIES)
            raw_count = vectors.count(request.app.state.qdrant, vectors.RAW)
        except Exception as exc:
            request.app.state.index_ready = False
            request.app.state.index_error = str(exc)
            index_ready = False
    version = conn.execute("SELECT MAX(version) AS v FROM schema_migrations").fetchone()
    return {
        "database": {"schema_version": int(version["v"]) if version and version["v"] else None},
        "qdrant": {
            "available": index_ready,
            "memories": memory_count,
            "raw": raw_count,
            "error": getattr(request.app.state, "index_error", None),
        },
        "embedder": {
            "ready": request.app.state.embedder.ready,
            "device": request.app.state.embedder.device,
            "revision": get_settings().embed_revision,
        },
        "outbox": {"pending": outbox.pending_count(conn)},
        "jobs": {
            row["status"]: int(row["n"])
            for row in conn.execute("SELECT status,COUNT(*) AS n FROM jobs GROUP BY status")
        },
    }


@router.get("/v1/admin/metrics")
def metrics(
    request: Request,
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> MetricsOut:
    """Instance metrics for an administrator, own metrics for anyone else."""
    period = datetime.now(UTC).strftime("%Y-%m")
    scope = None if principal.is_admin else principal.user_id
    retrieval_metrics = telemetry.metrics(conn, scope)
    active_memories = conn.execute(
        """SELECT COUNT(*) AS n FROM memories WHERE status='active'
             AND (valid_until IS NULL OR valid_until>now())
             AND (%s OR scope_id = ANY(%s))""",
        (principal.is_admin, principal.scopes()),
    ).fetchone()
    indexed_memories: int | None = None
    if principal.is_admin and getattr(request.app.state, "index_ready", True):
        with suppress(Exception):
            indexed_memories = vectors.count(request.app.state.qdrant, vectors.MEMORIES)
    row = conn.execute(
        """SELECT
              (SELECT MIN(created_at) FROM messages WHERE NOT processed
                AND (%(admin)s OR user_id=%(user)s)) AS oldest_unprocessed,
              (SELECT COUNT(*) FROM judge_runs WHERE error IS NOT NULL
                AND (%(admin)s OR user_id=%(user)s)) AS provider_errors,
              (SELECT COALESCE(SUM(cost_usd),0) FROM judge_runs
                WHERE to_char(created_at AT TIME ZONE 'UTC','YYYY-MM') = %(period)s
                  AND (%(admin)s OR user_id=%(user)s))
                AS month_spend_usd,
              (SELECT COALESCE(SUM(reserved_usd),0) FROM budget_reservations
                WHERE period = %(period)s AND status='active'
                  AND (%(admin)s OR user_id=%(user)s)) AS month_reserved_usd,
              (SELECT EXTRACT(EPOCH FROM (now() - MIN(created_at))) FROM index_outbox
                WHERE status IN ('pending','processing','failed')) AS outbox_oldest_age_seconds,
              (SELECT COALESCE(SUM(attempts),0) FROM index_outbox) AS outbox_retries,
              (SELECT EXTRACT(EPOCH FROM (now() - MAX(verified_at))) FROM backup_artifacts)
                AS backup_freshness_seconds,
              (SELECT COUNT(*) FROM memories
                WHERE review_status='pending' AND status='active'
                  AND (%(admin)s OR scope_id = ANY(%(scopes)s))) AS pending_review""",
        {
            "period": period,
            "scopes": principal.scopes(),
            "admin": principal.is_admin,
            "user": principal.user_id,
        },
    ).fetchone()
    return {
        "outbox_pending": outbox.pending_count(conn) if principal.is_admin else None,
        "oldest_unprocessed_message": iso(row["oldest_unprocessed"]),
        "provider_errors": int(row["provider_errors"]),
        "month_spend_usd": float(row["month_spend_usd"]),
        "month_reserved_usd": float(row["month_reserved_usd"]),
        "month_limit_usd": get_settings().monthly_cost_limit_usd if principal.is_admin else None,
        "pending_review": int(row["pending_review"]),
        **retrieval_metrics,
        "outbox_oldest_age_seconds": round(float(row["outbox_oldest_age_seconds"]), 1)
        if principal.is_admin and row["outbox_oldest_age_seconds"] is not None
        else None,
        "outbox_retries": int(row["outbox_retries"]) if principal.is_admin else None,
        "index_parity": {
            "database_active": int(active_memories["n"]) if active_memories else 0,
            "qdrant_active": indexed_memories,
        },
        "backup_freshness_seconds": round(float(row["backup_freshness_seconds"]), 1)
        if principal.is_admin and row["backup_freshness_seconds"] is not None
        else None,
    }


@router.get("/v1/admin/backups")
def backup_status(principal: Principal = Depends(require_admin)) -> BackupsOut:
    return {"items": operations.list_backups(get_settings())}


@router.get("/v1/admin/stats/memories")
def stats_memories(
    days: int = Query(30, ge=1, le=365),
    group_by: str = Query("kind"),
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> MemoryStatsOut:
    try:
        return stats.memories(conn, scope_ids=principal.scopes(), days=days, group_by=group_by)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/v1/admin/stats/pipeline")
def stats_pipeline(
    days: int = Query(30, ge=1, le=365),
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> PipelineStatsOut:
    """Instance-wide for an administrator, own work for anyone else."""
    return stats.pipeline(
        conn, user_id=None if principal.is_admin else principal.user_id, days=days
    )


@router.get("/v1/admin/stats/retrieval")
def stats_retrieval(
    days: int = Query(30, ge=1, le=365),
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> RetrievalStatsOut:
    return stats.retrieval(
        conn, user_id=None if principal.is_admin else principal.user_id, days=days
    )


@router.get("/v1/admin/stats/review")
def stats_review(
    days: int = Query(30, ge=1, le=365),
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> ReviewStatsOut:
    """Also drives the nav badge, so it stays cheap enough to poll."""
    return stats.review(conn, scope_ids=principal.scopes(), user_id=principal.user_id, days=days)


@router.get("/v1/admin/stats/entities")
def stats_entities(
    limit: int = Query(10, ge=1, le=50),
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> EntityStatsOut:
    return stats.entities(conn, scope_ids=principal.scopes(), limit=limit)


@router.get("/v1/admin/stats/users")
def stats_users(
    days: int = Query(30, ge=1, le=365),
    principal: Principal = Depends(require_admin),
    conn: psycopg.Connection = Depends(get_conn),
) -> PeopleStatsOut:
    """Admin-only: this is the one panel that reports on other people."""
    return stats.users(conn, days=days)
