"""Human-facing admin routes and query builders."""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from . import judge, mutate, retrieval, store, vectors
from .config import get_settings
from .db import connect, transaction

logger = logging.getLogger(__name__)
router = APIRouter()

MEMORY_TYPES = {
    "preference", "fact", "skill", "relation", "project", "decision", "task"
}
MEMORY_SORTS = {
    "updated_at": "updated_at",
    "created_at": "created_at",
    "importance": "importance",
    "confidence": "confidence",
    "retrieval_count": "retrieval_count",
    "valid_until": "valid_until",
    "type": "type",
}


def _csv(value: str | None) -> list[str]:
    return [part for part in (value or "").split(",") if part]


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def memories_where(
    *,
    owner_id: str,
    q: str | None = None,
    type: str | None = None,
    status: str = "active",
    scope: str | None = None,
    scope_key: str | None = None,
    agent_id: str | None = None,
    never_retrieved: bool | None = None,
    min_importance: float | None = None,
    max_importance: float | None = None,
    expired_validity: bool | None = None,
    created_after: str | None = None,
    created_before: str | None = None,
) -> tuple[str, list[Any]]:
    clauses = ["owner_id = ?"]
    params: list[Any] = [owner_id]
    if status != "all":
        statuses = _csv(status)
        if not statuses:
            statuses = ["active"]
        clauses.append(f"status IN ({','.join('?' for _ in statuses)})")
        params.extend(statuses)
    types = _csv(type)
    if types:
        clauses.append(f"type IN ({','.join('?' for _ in types)})")
        params.extend(types)
    scopes = _csv(scope)
    if scopes:
        clauses.append(f"scope IN ({','.join('?' for _ in scopes)})")
        params.extend(scopes)
    if scope_key == "__none__":
        clauses.append("scope_key IS NULL")
    elif scope_key is not None:
        clauses.append("scope_key = ?")
        params.append(scope_key)
    if agent_id is not None:
        clauses.append("agent_id IS ?")
        params.append(None if agent_id == "__none__" else agent_id)
    if q:
        clauses.append("lowerx(text) LIKE lowerx(?) ESCAPE '\\'")
        params.append(f"%{_escape_like(q)}%")
    if never_retrieved:
        clauses.append("retrieval_count = 0")
    if min_importance is not None:
        clauses.append("importance >= ?")
        params.append(min_importance)
    if max_importance is not None:
        clauses.append("importance <= ?")
        params.append(max_importance)
    if expired_validity:
        # Compared against an ISO-with-Z stamp, not datetime('now'). Timestamps
        # here are stored as "2026-07-29T00:00:00Z" while datetime('now') yields
        # "2026-07-29 07:34:22": at offset 10 that is 'T' (0x54) against ' '
        # (0x20), so a same-day value always sorted *after* now and an expiry
        # earlier today was reported as still valid.
        clauses.append(
            "valid_until IS NOT NULL"
            " AND valid_until <= strftime('%Y-%m-%dT%H:%M:%SZ','now')"
        )
    if created_after:
        clauses.append("created_at >= ?")
        params.append(created_after)
    if created_before:
        clauses.append("created_at <= ?")
        params.append(created_before)
    return " AND ".join(clauses), params


def list_memories_data(
    conn: sqlite3.Connection,
    *,
    owner_id: str,
    limit: int = 100,
    offset: int = 0,
    sort: str = "updated_at",
    order: str = "desc",
    **filters: Any,
) -> dict[str, Any]:
    if sort not in MEMORY_SORTS:
        raise HTTPException(
            422, f"invalid sort; expected one of {', '.join(MEMORY_SORTS)}"
        )
    if order not in ("asc", "desc"):
        raise HTTPException(422, "order must be asc or desc")
    where, params = memories_where(owner_id=owner_id, **filters)
    column = MEMORY_SORTS[sort]
    rows = conn.execute(
        f"""SELECT * FROM memories WHERE {where}
             ORDER BY {column} {order.upper()}, id ASC LIMIT ? OFFSET ?""",
        [*params, limit, offset],
    ).fetchall()
    total = conn.execute(
        f"SELECT COUNT(*) n FROM memories WHERE {where}", params
    ).fetchone()["n"]
    return {
        "memories": [dict(row) for row in rows],
        "count": len(rows),
        "total": int(total),
        "limit": limit,
        "offset": offset,
        "sort": sort,
        "order": order,
    }


def _job_running(request: Request) -> bool:
    job = getattr(request.app.state, "reindex_job", None)
    return bool(job and job.get("status") == "running")


def _guard_mutation(request: Request) -> None:
    if _job_running(request):
        raise HTTPException(409, "memory mutations are disabled while reindex runs")


def _apply_index(request: Request, result: mutate.MutationResult | mutate.BulkResult) -> bool:
    for attempt in range(2):
        try:
            result.apply_index(request.app.state.qdrant)
            return False
        except Exception:
            if attempt == 0:
                continue
            logger.exception("memory committed but Qdrant update failed")
            request.app.state.index_dirty = True
            return True
    return True


class MemoryPatch(BaseModel):
    text: str | None = None
    type: Literal[
        "preference", "fact", "skill", "relation", "project", "decision", "task"
    ] | None = None
    scope: Literal["user", "project", "task"] | None = None
    scope_key: str | None = None
    agent_id: str | None = None
    importance: float | None = Field(default=None, ge=0, le=1)
    confidence: float | None = Field(default=None, ge=0, le=1)
    valid_until: str | None = None
    status: Literal["active", "expired"] | None = None
    expected_updated_at: str | None = None


@router.patch("/v1/memories/{memory_id}")
def patch_memory(memory_id: str, body: MemoryPatch, request: Request) -> dict[str, Any]:
    _guard_mutation(request)
    fields = body.model_fields_set - {"expected_updated_at"}
    changes = {field: getattr(body, field) for field in fields}
    if "text" in changes and not (changes["text"] or "").strip():
        raise HTTPException(422, "text cannot be empty")
    try:
        with transaction(request.app.state.db()):
            result = mutate.update_memory(
                request.app.state.db(),
                request.app.state.qdrant,
                request.app.state.embedder,
                memory_id=memory_id,
                changes=changes,
                expected_updated_at=body.expected_updated_at,
            )
    except mutate.MutationError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    stale = _apply_index(request, result)
    return {
        "memory": result.row,
        "reembedded": result.reembedded,
        "index_stale": stale,
    }


@router.delete("/v1/memories/{memory_id}")
def delete_memory(
    memory_id: str, request: Request, hard: bool = False
) -> dict[str, Any]:
    _guard_mutation(request)
    try:
        with transaction(request.app.state.db()):
            if hard:
                result = mutate.hard_delete(
                    request.app.state.db(),
                    request.app.state.qdrant,
                    memory_id=memory_id,
                )
            else:
                result = mutate.set_status(
                    request.app.state.db(),
                    request.app.state.qdrant,
                    request.app.state.embedder,
                    memory_id=memory_id,
                    status="expired",
                )
    except mutate.MutationError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    stale = _apply_index(request, result)
    return {
        "deleted": True,
        "hard": hard,
        "id": memory_id,
        "sources_unlinked": result.sources_unlinked,
        "successors_unlinked": result.successors_unlinked,
        "index_stale": stale,
    }


class SupersedeIn(BaseModel):
    by: str


@router.post("/v1/memories/{memory_id}/supersede")
def supersede_memory(
    memory_id: str, body: SupersedeIn, request: Request
) -> dict[str, Any]:
    _guard_mutation(request)
    try:
        with transaction(request.app.state.db()):
            result = mutate.supersede(
                request.app.state.db(),
                request.app.state.qdrant,
                memory_id=memory_id,
                by_id=body.by,
            )
    except mutate.MutationError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    return {"memory": result.row, "index_stale": _apply_index(request, result)}


class BulkIn(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=500)
    op: Literal[
        "expire", "restore", "hard_delete", "set_type", "set_importance", "set_scope"
    ]
    value: Any = None
    confirm: bool = False


@router.post("/v1/admin/memories/bulk")
def bulk_memories(body: BulkIn, request: Request) -> dict[str, Any]:
    _guard_mutation(request)
    if body.op == "hard_delete" and (not body.confirm or len(body.ids) > 100):
        raise HTTPException(422, "hard_delete requires confirm and at most 100 ids")
    with transaction(request.app.state.db()):
        result = mutate.bulk(
            request.app.state.db(),
            request.app.state.qdrant,
            request.app.state.embedder,
            ids=body.ids,
            op=body.op,
            value=body.value,
        )
    return {
        "requested": result.requested,
        "applied": result.applied,
        "skipped": result.skipped,
        "index_stale": _apply_index(request, result),
    }


def _ops(raw: Any) -> list[dict[str, Any]]:
    if not raw:
        return []
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
    except (ValueError, TypeError):
        return []
    if isinstance(value, dict):
        value = value.get("operations") or value.get("ops") or []
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


JUDGE_SORTS = {
    "created_at": "created_at",
    "cost_usd": "cost_usd",
    "latency_ms": "latency_ms",
    "tokens": "COALESCE(input_tokens,0)+COALESCE(output_tokens,0)",
}


@router.get("/v1/admin/judge-runs")
def judge_runs(
    request: Request,
    kind: str | None = None,
    errors_only: bool = False,
    has_ops: bool | None = None,
    min_cost: float | None = None,
    q: str | None = None,
    created_after: str | None = None,
    created_before: str | None = None,
    sort: str = "created_at",
    order: Literal["asc", "desc"] = "desc",
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    if sort not in JUDGE_SORTS:
        raise HTTPException(422, f"invalid sort; expected one of {', '.join(JUDGE_SORTS)}")
    clauses = ["1=1"]
    params: list[Any] = []
    if kind:
        clauses.append("kind=?")
        params.append(kind)
    if errors_only:
        clauses.append("error IS NOT NULL")
    if min_cost is not None:
        clauses.append("cost_usd>=?")
        params.append(min_cost)
    if q:
        clauses.append("lowerx(COALESCE(output_json,'')) LIKE lowerx(?) ESCAPE '\\'")
        params.append(f"%{_escape_like(q)}%")
    if created_after:
        clauses.append("created_at>=?")
        params.append(created_after)
    if created_before:
        clauses.append("created_at<=?")
        params.append(created_before)
    if has_ops is True:
        clauses.append("output_json IS NOT NULL AND output_json NOT LIKE '%\"operations\": []%'")
    elif has_ops is False:
        clauses.append("(output_json IS NULL OR output_json LIKE '%\"operations\": []%')")
    where = " AND ".join(clauses)
    rows = request.app.state.db().execute(
        f"""SELECT * FROM judge_runs WHERE {where}
             ORDER BY {JUDGE_SORTS[sort]} {order.upper()}, id ASC LIMIT ? OFFSET ?""",
        [*params, limit, offset],
    ).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        item["ops"] = _ops(row["output_json"])
        items.append(item)
    total = request.app.state.db().execute(
        f"SELECT COUNT(*) n FROM judge_runs WHERE {where}", params
    ).fetchone()["n"]
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/v1/admin/judge-runs/{run_id}")
def judge_run_detail(run_id: int, request: Request) -> dict[str, Any]:
    conn = request.app.state.db()
    row = conn.execute("SELECT * FROM judge_runs WHERE id=?", (run_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "unknown judge run")
    try:
        input_data = json.loads(row["input_json"] or "{}")
    except (ValueError, TypeError):
        input_data = {}
    operations = _ops(row["output_json"])
    ids = [op.get("id") for op in operations if op.get("id")]
    memories: list[dict[str, Any]] = []
    if ids:
        placeholders = ",".join("?" for _ in ids)
        memories = [
            dict(item)
            for item in conn.execute(
                f"SELECT * FROM memories WHERE id IN ({placeholders})", ids
            ).fetchall()
        ]
    message_ids = input_data.get("message_ids") or []
    if not message_ids and memories:
        mem_ids = [item["id"] for item in memories]
        placeholders = ",".join("?" for _ in mem_ids)
        message_ids = [
            int(item["message_id"])
            for item in conn.execute(
                f"SELECT DISTINCT message_id FROM memory_sources WHERE memory_id IN ({placeholders})",
                mem_ids,
            ).fetchall()
        ]
    messages: list[dict[str, Any]] = []
    if message_ids:
        placeholders = ",".join("?" for _ in message_ids)
        messages = [
            dict(item)
            for item in conn.execute(
                f"SELECT * FROM messages WHERE id IN ({placeholders}) ORDER BY id",
                message_ids,
            ).fetchall()
        ]
    try:
        output = json.loads(row["output_json"]) if row["output_json"] else None
    except (ValueError, TypeError):
        output = row["output_json"]
    return {
        "run": dict(row),
        "input": input_data,
        "output": output,
        "ops": operations,
        "memories": memories,
        "messages": messages,
        "window_recoverable": bool(messages),
    }


def cost_summary(conn: sqlite3.Connection, days: int) -> dict[str, Any]:
    rows = conn.execute(
        """SELECT kind, COUNT(*) calls, COALESCE(SUM(cost_usd),0) usd,
                  COALESCE(SUM(input_tokens),0) tin,
                  COALESCE(SUM(output_tokens),0) tout
             FROM judge_runs WHERE created_at >= strftime('%Y-%m-%dT%H:%M:%SZ','now',?)
            GROUP BY kind""",
        (f"-{days} days",),
    ).fetchall()
    errors = conn.execute(
        """SELECT COUNT(*) n FROM judge_runs
            WHERE error IS NOT NULL AND created_at >= strftime('%Y-%m-%dT%H:%M:%SZ','now',?)""",
        (f"-{days} days",),
    ).fetchone()["n"]
    settings = get_settings()
    return {
        "days": days,
        "total_usd": round(sum(float(row["usd"]) for row in rows), 6),
        "by_kind": {row["kind"]: round(float(row["usd"]), 6) for row in rows},
        "calls": sum(int(row["calls"]) for row in rows),
        "errors": int(errors),
        "input_tokens": sum(int(row["tin"]) for row in rows),
        "output_tokens": sum(int(row["tout"]) for row in rows),
        "month_spend_usd": round(judge.month_spend_usd(conn), 6),
        "monthly_limit_usd": settings.monthly_cost_limit_usd,
    }


def daily_activity(
    conn: sqlite3.Connection, *, owner_id: str, days: int
) -> list[dict[str, Any]]:
    """Return a zero-filled daily activity series for charts and heatmaps."""
    since = f"-{days - 1} days"
    memory_daily = {
        row["day"]: int(row["n"])
        for row in conn.execute(
            """SELECT substr(created_at,1,10) day, COUNT(*) n
                 FROM memories
                WHERE owner_id=? AND created_at >= strftime('%Y-%m-%dT%H:%M:%SZ','now',?)
                GROUP BY day""",
            (owner_id, since),
        ).fetchall()
    }
    memory_type_daily: dict[str, dict[str, int]] = {}
    for row in conn.execute(
        """SELECT substr(created_at,1,10) day, type, COUNT(*) n
             FROM memories
            WHERE owner_id=? AND created_at >= strftime('%Y-%m-%dT%H:%M:%SZ','now',?)
            GROUP BY day, type""",
        (owner_id, since),
    ).fetchall():
        memory_type_daily.setdefault(row["day"], {})[row["type"]] = int(row["n"])
    message_daily = {
        row["day"]: int(row["n"])
        for row in conn.execute(
            """SELECT substr(m.created_at,1,10) day, COUNT(*) n
                 FROM messages m JOIN sessions s ON s.id=m.session_id
                WHERE s.owner_id=? AND m.created_at >= strftime('%Y-%m-%dT%H:%M:%SZ','now',?)
                GROUP BY day""",
            (owner_id, since),
        ).fetchall()
    }
    judge_daily = {
        row["day"]: (int(row["n"]), round(float(row["usd"]), 6))
        for row in conn.execute(
            """SELECT substr(created_at,1,10) day, COUNT(*) n,
                      COALESCE(SUM(cost_usd),0) usd
                 FROM judge_runs
                WHERE created_at >= strftime('%Y-%m-%dT%H:%M:%SZ','now',?)
                GROUP BY day""",
            (since,),
        ).fetchall()
    }
    today = datetime.now(UTC).date()
    daily: list[dict[str, Any]] = []
    for delta in range(days - 1, -1, -1):
        day = str(today - timedelta(days=delta))
        calls, cost = judge_daily.get(day, (0, 0.0))
        daily.append(
            {
                "day": day,
                "memories": memory_daily.get(day, 0),
                "memory_types": memory_type_daily.get(day, {}),
                "messages": message_daily.get(day, 0),
                "judge_runs": calls,
                "cost_usd": cost,
            }
        )
    return daily


def analytics_summary(
    conn: sqlite3.Connection, *, owner_id: str, days: int
) -> dict[str, Any]:
    """Return chart-ready corpus analytics without requiring a warehouse."""
    confidence = {
        row["bucket"]: int(row["n"])
        for row in conn.execute(
            """SELECT CASE WHEN confidence<0.6 THEN 'low'
                           WHEN confidence<0.85 THEN 'medium' ELSE 'high' END bucket,
                      COUNT(*) n
                 FROM memories WHERE owner_id=? AND status='active'
                GROUP BY bucket""",
            (owner_id,),
        ).fetchall()
    }
    retrieval = {
        row["bucket"]: int(row["n"])
        for row in conn.execute(
            """SELECT CASE WHEN retrieval_count=0 THEN 'never'
                           WHEN retrieval_count<5 THEN '1–4'
                           WHEN retrieval_count<20 THEN '5–19' ELSE '20+' END bucket,
                      COUNT(*) n
                 FROM memories WHERE owner_id=? AND status='active'
                GROUP BY bucket""",
            (owner_id,),
        ).fetchall()
    }

    agent_rows = conn.execute(
        """SELECT s.agent_id, COUNT(DISTINCT s.id) sessions, COUNT(m.id) messages
             FROM sessions s LEFT JOIN messages m ON m.session_id=s.id
            WHERE s.owner_id=? GROUP BY s.agent_id
            ORDER BY messages DESC, s.agent_id ASC LIMIT 8""",
        (owner_id,),
    ).fetchall()
    memory_agents = {
        row["agent_id"]: int(row["n"])
        for row in conn.execute(
            """SELECT COALESCE(agent_id,'unassigned') agent_id, COUNT(*) n
                 FROM memories WHERE owner_id=? AND status='active'
                GROUP BY COALESCE(agent_id,'unassigned')""",
            (owner_id,),
        ).fetchall()
    }
    agents = [
        {
            "agent_id": row["agent_id"],
            "sessions": int(row["sessions"]),
            "messages": int(row["messages"]),
            "memories": memory_agents.get(row["agent_id"], 0),
        }
        for row in agent_rows
    ]
    if "unassigned" in memory_agents and not any(
        item["agent_id"] == "unassigned" for item in agents
    ):
        agents.append(
            {
                "agent_id": "unassigned",
                "sessions": 0,
                "messages": 0,
                "memories": memory_agents["unassigned"],
            }
        )

    return {
        "daily": daily_activity(conn, owner_id=owner_id, days=days),
        "confidence": confidence,
        "retrieval": retrieval,
        "agents": agents,
    }


@router.get("/v1/admin/activity")
def activity(
    request: Request,
    owner_id: str | None = None,
    days: int = Query(365, ge=7, le=730),
) -> dict[str, Any]:
    owner = owner_id or get_settings().owner_id
    return {
        "days": days,
        "items": daily_activity(request.app.state.db(), owner_id=owner, days=days),
    }


@router.get("/v1/admin/costs")
def costs(request: Request, days: int = Query(30, ge=1, le=3650)) -> dict[str, Any]:
    return cost_summary(request.app.state.db(), days)


@router.get("/v1/admin/costs/daily")
def costs_daily(
    request: Request, days: int = Query(30, ge=1, le=365)
) -> dict[str, Any]:
    rows = request.app.state.db().execute(
        """SELECT substr(created_at,1,10) day, kind, SUM(COALESCE(cost_usd,0)) usd
             FROM judge_runs WHERE created_at >= strftime('%Y-%m-%dT%H:%M:%SZ','now',?)
            GROUP BY day, kind""",
        (f"-{days - 1} days",),
    ).fetchall()
    indexed = {(row["day"], row["kind"]): float(row["usd"]) for row in rows}
    kinds = sorted({row["kind"] for row in rows})
    today = datetime.now(UTC).date()
    items = []
    for delta in range(days - 1, -1, -1):
        day = str(today - timedelta(days=delta))
        values = {kind: round(indexed.get((day, kind), 0), 6) for kind in kinds}
        items.append({"day": day, "total_usd": round(sum(values.values()), 6), **values})
    return {"items": items, "days": days}


@router.get("/v1/admin/facets")
def facets(request: Request, owner_id: str | None = None) -> dict[str, Any]:
    owner = owner_id or get_settings().owner_id
    out: dict[str, list[dict[str, Any]]] = {}
    for name, expression in {
        "type": "type",
        "status": "status",
        "scope": "scope",
        "scope_key": "scope_key",
        "agent_id": "agent_id",
    }.items():
        out[name] = [
            {"value": row["value"], "count": row["count"]}
            for row in request.app.state.db().execute(
                f"""SELECT {expression} value, COUNT(*) count FROM memories
                     WHERE owner_id=? GROUP BY {expression} ORDER BY count DESC""",
                (owner,),
            ).fetchall()
        ]
    return out


@router.get("/v1/admin/sessions")
def sessions(
    request: Request,
    owner_id: str | None = None,
    agent_id: str | None = None,
    project: str | None = None,
    state: Literal["all", "open", "closed"] = "all",
    has_unprocessed: bool | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    clauses = ["s.owner_id=?"]
    params: list[Any] = [owner_id or get_settings().owner_id]
    if agent_id:
        clauses.append("s.agent_id=?")
        params.append(agent_id)
    if project:
        clauses.append("json_extract(s.meta,'$.project')=?")
        params.append(project)
    if state == "open":
        clauses.append("s.ended_at IS NULL")
    elif state == "closed":
        clauses.append("s.ended_at IS NOT NULL")
    having = ""
    if has_unprocessed is True:
        having = "HAVING SUM(CASE WHEN m.processed=0 THEN 1 ELSE 0 END)>0"
    elif has_unprocessed is False:
        having = "HAVING SUM(CASE WHEN m.processed=0 THEN 1 ELSE 0 END)=0"
    where = " AND ".join(clauses)
    rows = request.app.state.db().execute(
        f"""SELECT s.*, COUNT(m.id) message_count,
                   SUM(CASE WHEN m.processed=0 THEN 1 ELSE 0 END) unprocessed_count
              FROM sessions s LEFT JOIN messages m ON m.session_id=s.id
             WHERE {where} GROUP BY s.id {having}
             ORDER BY s.started_at DESC, s.id ASC LIMIT ? OFFSET ?""",
        [*params, limit, offset],
    ).fetchall()
    items = [dict(row) for row in rows]
    session_ids = [item["id"] for item in items]
    memory_counts: dict[str, int] = {}
    if session_ids:
        placeholders = ",".join("?" for _ in session_ids)
        for row in request.app.state.db().execute(
            f"""SELECT m.session_id, COUNT(DISTINCT ms.memory_id) n
                  FROM messages m JOIN memory_sources ms ON ms.message_id=m.id
                 WHERE m.session_id IN ({placeholders}) GROUP BY m.session_id""",
            session_ids,
        ).fetchall():
            memory_counts[row["session_id"]] = int(row["n"])
    for item in items:
        item["memory_count"] = memory_counts.get(item["id"], 0)
        try:
            item["meta"] = json.loads(item["meta"]) if item["meta"] else {}
        except (ValueError, TypeError):
            item["meta"] = {}
    total = request.app.state.db().execute(
        f"SELECT COUNT(*) n FROM sessions s WHERE {where}", params
    ).fetchone()["n"]
    return {"items": items, "total": int(total), "limit": limit, "offset": offset}


@router.get("/v1/admin/sessions/{session_id}/messages")
def session_messages(
    session_id: str,
    request: Request,
    order: Literal["asc", "desc"] = "asc",
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    conn = request.app.state.db()
    session = conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
    if session is None:
        raise HTTPException(404, "unknown session")
    rows = conn.execute(
        f"""SELECT * FROM messages WHERE session_id=?
             ORDER BY id {order.upper()} LIMIT ? OFFSET ?""",
        (session_id, limit, offset),
    ).fetchall()
    items = [dict(row) for row in rows]
    ids = [item["id"] for item in items]
    sources: dict[int, list[str]] = {}
    if ids:
        placeholders = ",".join("?" for _ in ids)
        for row in conn.execute(
            f"SELECT message_id,memory_id FROM memory_sources WHERE message_id IN ({placeholders})",
            ids,
        ).fetchall():
            sources.setdefault(int(row["message_id"]), []).append(row["memory_id"])
    for item in items:
        item["indexed_raw"] = (
            item["role"] == "user" and len(item["content"]) >= store.MIN_INDEX_CHARS
        )
        item["memory_ids"] = sources.get(item["id"], [])
    total = conn.execute(
        "SELECT COUNT(*) n FROM messages WHERE session_id=?", (session_id,)
    ).fetchone()["n"]
    return {
        "session": dict(session),
        "items": items,
        "total": int(total),
        "limit": limit,
        "offset": offset,
    }


@router.get("/v1/admin/messages/{message_id}")
def message_detail(message_id: int, request: Request) -> dict[str, Any]:
    row = request.app.state.db().execute(
        """SELECT m.*,s.owner_id,s.agent_id,s.meta FROM messages m
             JOIN sessions s ON s.id=m.session_id WHERE m.id=?""",
        (message_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "unknown message")
    out = dict(row)
    out["memory_ids"] = [
        item["memory_id"]
        for item in request.app.state.db().execute(
            "SELECT memory_id FROM memory_sources WHERE message_id=?", (message_id,)
        ).fetchall()
    ]
    return out


class SearchPreviewIn(BaseModel):
    query: str
    owner_id: str | None = None
    scope_key: str | None = None
    task_key: str | None = None
    types: list[str] | None = None
    project: str | None = None
    budget_tokens: int = Field(800, ge=0, le=20000)
    limit: int = Field(30, ge=1, le=200)
    include_raw: bool = False
    explain: bool = True


@router.post("/v1/admin/search-preview")
def search_preview(body: SearchPreviewIn, request: Request) -> dict[str, Any]:
    started = time.perf_counter()
    owner = body.owner_id or get_settings().owner_id
    result = retrieval.explain(
        request.app.state.qdrant,
        request.app.state.embedder,
        query=body.query,
        owner_id=owner,
        project=body.scope_key or body.project,
        task=body.task_key,
        types=body.types,
        limit=body.limit,
        budget_tokens=body.budget_tokens,
        diagnostics=True,
    )
    raw = []
    if body.include_raw:
        raw = store.search_raw(
            request.app.state.qdrant,
            request.app.state.embedder,
            query=body.query,
            owner_id=owner,
            project=body.project,
            limit=body.limit,
        )
    return {
        **result.as_dict(),
        "raw": raw,
        "feedback_recorded": False,
        "took_ms": round((time.perf_counter() - started) * 1000, 1),
    }


@router.get("/v1/admin/stats")
def stats(
    request: Request,
    owner_id: str | None = None,
    days: int = Query(30, ge=1, le=3650),
) -> dict[str, Any]:
    conn = request.app.state.db()
    owner = owner_id or get_settings().owner_id

    def grouped(column: str) -> dict[str, int]:
        return {
            str(row["key"] if row["key"] is not None else "__none__"): int(row["n"])
            for row in conn.execute(
                f"SELECT {column} key,COUNT(*) n FROM memories WHERE owner_id=? GROUP BY {column}",
                (owner,),
            ).fetchall()
        }

    corpus = conn.execute(
        """SELECT COUNT(*) messages,
                  SUM(CASE WHEN processed=0 THEN 1 ELSE 0 END) unprocessed
             FROM messages m JOIN sessions s ON s.id=m.session_id WHERE s.owner_id=?""",
        (owner,),
    ).fetchone()
    active = conn.execute(
        "SELECT COUNT(*) n FROM memories WHERE owner_id=? AND status='active'", (owner,)
    ).fetchone()["n"]
    raw_eligible = conn.execute(
        """SELECT COUNT(*) n FROM messages m JOIN sessions s ON s.id=m.session_id
            WHERE s.owner_id=? AND m.role='user' AND length(m.content)>=?""",
        (owner, store.MIN_INDEX_CHARS),
    ).fetchone()["n"]
    q_mem = vectors.count(request.app.state.qdrant, vectors.MEMORIES)
    q_raw = vectors.count(request.app.state.qdrant, vectors.RAW)
    triage = conn.execute(
        """SELECT
             SUM(CASE WHEN status='active' AND retrieval_count=0 THEN 1 ELSE 0 END) never_retrieved,
             SUM(CASE WHEN status='active' AND confidence<0.6 THEN 1 ELSE 0 END) low_confidence,
             SUM(CASE WHEN status='active' AND valid_until IS NOT NULL
                       AND valid_until<=strftime('%Y-%m-%dT%H:%M:%SZ','now','+7 days') THEN 1 ELSE 0 END) expiring_7d,
             SUM(CASE WHEN status='superseded' THEN 1 ELSE 0 END) superseded,
             SUM(CASE WHEN status='expired' THEN 1 ELSE 0 END) expired,
             SUM(CASE WHEN status='active' AND updated_at<strftime('%Y-%m-%dT%H:%M:%SZ','now','-90 days')
                       THEN 1 ELSE 0 END) stale_90d
           FROM memories WHERE owner_id=?""",
        (owner,),
    ).fetchone()
    importance = {
        row["bucket"]: int(row["n"])
        for row in conn.execute(
            """SELECT CASE WHEN importance<0.4 THEN 'low'
                           WHEN importance<0.7 THEN 'medium' ELSE 'high' END bucket,
                      COUNT(*) n FROM memories WHERE owner_id=? GROUP BY bucket""",
            (owner,),
        ).fetchall()
    }
    return {
        "memories": {
            "total": sum(grouped("status").values()),
            "by_status": grouped("status"),
            "by_type": grouped("type"),
            "by_scope": grouped("scope"),
            "by_scope_key": grouped("scope_key"),
            "importance": importance,
            **{key: int(value or 0) for key, value in dict(triage).items()},
        },
        "corpus": {
            "messages": int(corpus["messages"] or 0),
            "unprocessed": int(corpus["unprocessed"] or 0),
            "sessions": conn.execute(
                "SELECT COUNT(*) n FROM sessions WHERE owner_id=?", (owner,)
            ).fetchone()["n"],
            "judge_runs": conn.execute("SELECT COUNT(*) n FROM judge_runs").fetchone()["n"],
        },
        "backlog": judge.estimate_backfill(conn, model=get_settings().judge_model),
        "cost": cost_summary(conn, days),
        "analytics": analytics_summary(conn, owner_id=owner, days=days),
        "health": {
            "sqlite_active": int(active),
            "qdrant_memories": q_mem,
            "index_drift": q_mem - int(active),
            "sqlite_raw_eligible": int(raw_eligible),
            "qdrant_raw": q_raw,
            "raw_drift": q_raw - int(raw_eligible),
            "index_dirty": bool(getattr(request.app.state, "index_dirty", False)),
        },
    }


def _run_reindex(app: Any) -> None:
    settings = get_settings()
    conn = connect(settings.db_path)
    try:
        def progress(phase: str, completed: int, total: int) -> None:
            with app.state.reindex_lock:
                app.state.reindex_job.update(
                    phase=phase, completed=completed, total=total
                )

        counts = store.reindex(
            conn, app.state.qdrant, app.state.embedder, progress=progress
        )
        with app.state.reindex_lock:
            app.state.reindex_job.update(
                status="complete", counts=counts, finished_at=datetime.now(UTC).isoformat()
            )
            app.state.index_dirty = False
    except Exception as exc:  # noqa: BLE001
        logger.exception("reindex failed")
        with app.state.reindex_lock:
            app.state.reindex_job.update(status="error", error=str(exc))
    finally:
        conn.close()


class ReextractIn(BaseModel):
    owner_id: str | None = None
    from_date: str | None = None
    prompt_version: str | None = None
    dry_run: bool = True
    max_calls: int = Field(default=0, ge=0)
    # Accepted so the documented body still validates, then rejected below. The doc
    # offers it at half price; this service does not implement Batch, and quietly
    # ignoring the flag would report a discount that was never applied.
    use_batch: bool = False


@router.post("/v1/admin/reextract")
def reextract(body: ReextractIn, request: Request) -> dict[str, Any]:
    """Replay history under another prompt version. `dry_run` defaults to true.

    Old facts are superseded rather than overwritten, and the response carries their
    ids so `POST /v1/admin/memories/bulk` with `op="restore"` is a full rollback.
    """
    from . import prompts
    from . import reextract as reextractor

    _guard_mutation(request)
    settings = get_settings()
    if body.use_batch:
        raise HTTPException(
            422,
            "use_batch is not implemented: Gemini's Batch API is not wired here. "
            "Re-run without it; a full replay of this corpus costs about $0.50.",
        )
    version = body.prompt_version or prompts.DEFAULT_VERSION
    if version not in prompts.REGISTRY:
        raise HTTPException(
            422,
            f"unknown prompt_version {version!r}; "
            f"known: {', '.join(sorted(prompts.REGISTRY))}",
        )

    conn = request.app.state.db()
    owner = body.owner_id or settings.owner_id
    started = time.perf_counter()
    model = settings.judge_model

    if body.dry_run:
        proposed = reextractor.plan(
            conn, owner_id=owner, from_date=body.from_date, model=model
        )
        return {
            **proposed.as_dict(),
            "dry_run": True,
            "prompt_version": version,
            "model": model,
            "took_ms": round((time.perf_counter() - started) * 1000),
        }

    with transaction(conn):
        outcome = reextractor.run(
            conn,
            request.app.state.qdrant,
            request.app.state.embedder,
            owner_id=owner,
            from_date=body.from_date,
            version=version,
            model=model,
            monthly_limit_usd=settings.monthly_cost_limit_usd,
            anthropic_api_key=settings.anthropic_api_key,
            gemini_api_key=settings.gemini_api_key,
            project=settings.vertex_project,
            location=settings.vertex_location,
            max_calls=body.max_calls,
        )
    return {
        **outcome.as_dict(),
        "dry_run": False,
        "prompt_version": version,
        "model": model,
        "took_ms": round((time.perf_counter() - started) * 1000),
    }


class ConsolidateIn(BaseModel):
    owner_id: str | None = None
    dry_run: bool = True
    # Exposed per-request so a threshold can be swept against the eval without a
    # restart. docs/05 measured 0.90 as barely catching paraphrases, so the right
    # value here is an empirical question, not a constant.
    threshold: float | None = Field(default=None, ge=0.5, le=1.0)


@router.post("/v1/admin/consolidate")
def consolidate(body: ConsolidateIn, request: Request) -> dict[str, Any]:
    """Stage 4, on demand. `dry_run` defaults to true.

    Documented in docs/03-api.md from the start and unimplemented until now. Always
    dry-run first: a merge supersedes its inputs, and while nothing is deleted, the
    active set it leaves behind is what every later search sees.
    """
    from . import consolidate as consolidator

    _guard_mutation(request)
    settings = get_settings()
    conn = request.app.state.db()
    owner = body.owner_id or settings.owner_id
    started = time.perf_counter()
    with transaction(conn):
        outcome = consolidator.run(
            conn,
            request.app.state.qdrant,
            request.app.state.embedder,
            owner_id=owner,
            threshold=body.threshold or settings.consolidate_cosine,
            stale_days=settings.consolidate_stale_days,
            demotion=settings.consolidate_demotion,
            model=settings.judge_model,
            monthly_limit_usd=settings.monthly_cost_limit_usd,
            anthropic_api_key=settings.anthropic_api_key,
            gemini_api_key=settings.gemini_api_key,
            project=settings.vertex_project,
            location=settings.vertex_location,
            dry_run=body.dry_run,
        )
    active = conn.execute(
        "SELECT COUNT(*) n FROM memories WHERE owner_id=? AND status='active'",
        (owner,),
    ).fetchone()["n"]
    return {
        **outcome.as_dict(),
        "dry_run": body.dry_run,
        "threshold": body.threshold or settings.consolidate_cosine,
        "active_after": int(active),
        "took_ms": round((time.perf_counter() - started) * 1000),
    }


@router.post("/v1/admin/reindex/start", status_code=status.HTTP_202_ACCEPTED)
def reindex_start(request: Request) -> dict[str, Any]:
    lock = getattr(request.app.state, "reindex_lock", None)
    if lock is None:
        request.app.state.reindex_lock = threading.Lock()
        lock = request.app.state.reindex_lock
    with lock:
        if _job_running(request):
            raise HTTPException(409, "reindex already running")
        request.app.state.reindex_job = {
            "status": "running",
            "phase": "starting",
            "completed": 0,
            "total": 0,
            "started_at": datetime.now(UTC).isoformat(),
        }
        thread = threading.Thread(
            target=_run_reindex, args=(request.app,), daemon=True, name="memkit-reindex"
        )
        thread.start()
    return request.app.state.reindex_job


@router.get("/v1/admin/reindex/status")
def reindex_status(request: Request) -> dict[str, Any]:
    return getattr(request.app.state, "reindex_job", {"status": "idle"})
