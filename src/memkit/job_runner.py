"""Execute durable jobs with one connection and one fenced lease per operation."""

from __future__ import annotations

import logging
from typing import Any

from . import consolidate, entities, extract, jobs, maintenance, privacy, reextract, reindex, store
from .config import get_settings

logger = logging.getLogger(__name__)
MAX_WINDOWS_PER_JOB = 25


def queue_extraction(conn, *, session_id, agent_id, force, pending=0, user_id=None):
    windows = min(MAX_WINDOWS_PER_JOB, max(1, -(-max(pending, 0) // extract.WINDOW_SIZE)))
    return jobs.create(
        conn,
        kind="extraction",
        input_data={
            "session_id": session_id,
            "agent_id": agent_id,
            "force": force,
            "max_windows": windows,
        },
        call_limit=windows,
        user_id=user_id,
    )


def run(application, job_id: str) -> None:
    """Claims and completions belong here; domain operations own their transactions."""
    with application.state.db.borrow() as conn:
        try:
            job = jobs.claim(conn, job_id)
        except RuntimeError:
            return  # Another worker claimed it after the queue peek.
        holder = str(job["holder"])
        try:
            with jobs.heartbeat(conn, job_id, holder=holder, pool=application.state.db) as lost:

                def guard():
                    if lost.is_set():
                        raise jobs.LeaseLost(f"job heartbeat failed: {job_id}")
                    jobs.require_current(conn, job_id, holder)

                def cancelled():
                    guard()
                    return jobs.cancel_requested(conn, job_id)

                data = dict(job["input"] or {})
                cleanup_started = bool(data.get("erasure"))
                if cancelled() and not cleanup_started:
                    jobs.finish(conn, job_id, holder=holder, status="cancelled")
                    return
                result = _execute(application, conn, job, guard, cancelled)
                status = (
                    "cancelled"
                    if job["kind"] == "extraction" and result.get("cancelled")
                    else "complete"
                )
                jobs.finish(conn, job_id, holder=holder, status=status, result=result)
        except jobs.LeaseLost:
            logger.warning("discarded stale job execution: %s", job_id)
        except reindex.ReindexCancelled:
            try:
                jobs.finish(conn, job_id, holder=holder, status="cancelled")
            except jobs.LeaseLost:
                logger.warning("cancellation belongs to obsolete job lease: %s", job_id)
        except maintenance.MaintenanceBusy as exc:
            _defer(conn, job_id, holder, str(exc))
        except privacy.ErasureCleanupPending as exc:
            _defer(conn, job_id, holder, str(exc))
        except Exception as exc:
            logger.exception("%s job %s failed", job["kind"], job_id)
            code = (
                "erase_refused"
                if job["kind"] == "erase" and isinstance(exc, ValueError)
                else f"{job['kind']}_failed"
            )
            try:
                jobs.finish(
                    conn, job_id, holder=holder, status="failed", error_code=code, error=str(exc)
                )
            except jobs.LeaseLost:
                logger.warning("failure belongs to obsolete job lease: %s", job_id)


def _defer(conn, job_id, holder, reason):
    try:
        jobs.defer(conn, job_id, holder=holder, error=reason)
    except jobs.LeaseLost:
        logger.warning("retry belongs to obsolete job lease: %s", job_id)


def _active_actor(conn, user_id):
    """Hold the actor's current role/enablement stable within this transaction."""
    row = conn.execute(
        "SELECT id,role FROM users WHERE id=%s AND disabled_at IS NULL FOR SHARE", (user_id,)
    ).fetchone()
    if row is None:
        raise PermissionError("job actor no longer exists or is disabled")
    return row


def _execute(application, conn, job, guard, cancelled) -> dict[str, Any]:
    settings = get_settings()
    state = application.state
    job_id = str(job["id"])
    data = dict(job["input"] or {})
    match job["kind"]:
        case "extraction":
            outcome = extract.run_session_extraction(
                conn,
                max_windows=int(data.get("max_windows") or 1),
                cancelled=cancelled,
                guard=guard,
                session_id=data["session_id"],
                agent_id=data["agent_id"],
                api_key=settings.anthropic_api_key,
                gemini_api_key=settings.gemini_api_key,
                project=settings.vertex_project,
                location=settings.vertex_location,
                monthly_limit_usd=settings.monthly_cost_limit_usd,
                model=settings.judge_model,
                job_id=job_id,
                force=bool(data.get("force")),
                client=state.qdrant,
                embedder=state.embedder,
                dedup_cosine=settings.dedup_cosine,
                semantic=getattr(state, "semantic", None),
            )
            if outcome.error:
                raise RuntimeError(outcome.error)
            continuation = None
            with conn.transaction():
                guard()
                was_cancelled = jobs.cancel_requested(conn, job_id)
                remaining = extract.messages_since_last(conn, data["session_id"])
                if (
                    not was_cancelled
                    and outcome.claimed
                    and remaining >= (1 if data.get("force") else extract.WINDOW_SIZE)
                ):
                    continuation = queue_extraction(
                        conn,
                        session_id=data["session_id"],
                        agent_id=data["agent_id"],
                        force=bool(data.get("force")),
                        pending=remaining,
                        user_id=job["user_id"],
                    )
            state.worker.wake()
            return {
                **outcome.as_dict(),
                "continuation_job_id": continuation,
                "cancelled": was_cancelled,
            }
        case "export":
            with conn.transaction():
                guard()
                actor = _active_actor(conn, job["user_id"])
                if str(actor["id"]) != data["user_id"]:
                    raise PermissionError("export target no longer matches its actor")
                current_scopes = {
                    str(row["id"]) for row in entities.visible_to(conn, str(actor["id"]))
                }
                saved_scopes = data.get("authored_scopes")
                authored_scopes = sorted(
                    current_scopes
                    if saved_scopes is None
                    else current_scopes.intersection(saved_scopes)
                )
            result = privacy.export_user(
                conn,
                user_id=data["user_id"],
                export_dir=settings.export_dir,
                private_scope_id=data["private_scope_id"],
                authored_scopes=authored_scopes,
            )
            return {**result, "path": str(result["path"])}
        case "erase":
            return privacy.erase_user(
                conn,
                state.qdrant,
                user_id=data["user_id"],
                private_scope_id=data["private_scope_id"],
                export_dir=settings.export_dir,
                backup_dir=settings.backup_dir,
                job_id=job_id,
                guard=guard,
            )
        case "reindex":
            return reindex.rebuild(
                conn, state.qdrant, state.embedder, cancelled=cancelled, guard=guard
            )
        case "consolidation":

            def consolidation_guard():
                guard()
                actor = _active_actor(conn, job["user_id"])
                if actor["role"] != "admin":
                    for scope_id in sorted(set(data["scope_ids"])):
                        store.require_scope_write(conn, user_id=str(actor["id"]), scope_id=scope_id)

            with conn.transaction():
                consolidation_guard()
            outcome = consolidate.run(
                conn,
                scope_ids=data["scope_ids"],
                stale_days=settings.consolidate_stale_days,
                demotion=settings.consolidate_demotion,
                importance_floor=settings.consolidate_importance_floor,
                dry_run=bool(data.get("dry_run", True)),
                embedder=state.embedder,
                client=state.qdrant,
                consolidate_cosine=settings.consolidate_cosine,
                merge=bool(data.get("merge", False)),
                merge_model=settings.judge_model,
                monthly_limit_usd=settings.monthly_cost_limit_usd,
                anthropic_api_key=settings.anthropic_api_key,
                gemini_api_key=settings.gemini_api_key,
                project=settings.vertex_project,
                location=settings.vertex_location,
                user_id=job["user_id"],
                guard=consolidation_guard,
            )
            state.worker.wake()
            return outcome.as_dict()
        case "reextract_report":
            return reextract.dry_run_report(conn, scope_ids=data["scope_ids"])
        case _:
            raise ValueError(f"no handler for job kind {job['kind']!r}")
