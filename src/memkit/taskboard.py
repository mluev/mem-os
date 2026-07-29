"""Task-memory Kanban metadata and admin HTTP surface."""

from __future__ import annotations

import sqlite3
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from . import mutate, store, vectors
from .config import get_settings
from .db import transaction, utcnow

router = APIRouter()

WorkflowStatus = Literal["unknown", "todo", "doing", "done"]
WORKFLOW_STATUSES: tuple[WorkflowStatus, ...] = (
    "unknown",
    "todo",
    "doing",
    "done",
)
POSITION_STEP = 1024.0
POSITION_EPSILON = 1e-7


def normalize_project(value: str | None) -> str | None:
    return (value or "").strip() or None


def _first_position(
    conn: sqlite3.Connection, owner_id: str, workflow_status: str
) -> float:
    row = conn.execute(
        """SELECT MIN(tb.position) AS position
             FROM task_board tb
             JOIN memories m ON m.id = tb.memory_id
            WHERE m.owner_id = ? AND tb.workflow_status = ?""",
        (owner_id, workflow_status),
    ).fetchone()
    return (float(row["position"]) if row["position"] is not None else POSITION_STEP) - POSITION_STEP


def ensure_metadata(
    conn: sqlite3.Connection,
    memory_id: str,
    *,
    workflow_status: str = "unknown",
    project_key: str | None = None,
) -> sqlite3.Row:
    row = conn.execute(
        """SELECT m.owner_id, m.type, m.scope, m.scope_key, tb.*
             FROM memories m
             LEFT JOIN task_board tb ON tb.memory_id = m.id
            WHERE m.id = ?""",
        (memory_id,),
    ).fetchone()
    if row is None:
        raise mutate.MutationError("unknown memory", status_code=404)
    if row["type"] != "task":
        raise mutate.MutationError("memory is not a task")
    if row["memory_id"] is None:
        status = workflow_status if workflow_status in WORKFLOW_STATUSES else "unknown"
        project = (
            normalize_project(project_key)
            if project_key is not None
            else normalize_project(row["scope_key"]) if row["scope"] != "user" else None
        )
        now = utcnow()
        conn.execute(
            """INSERT INTO task_board
               (memory_id, workflow_status, project_key, position, version,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, 1, ?, ?)""",
            (
                memory_id,
                status,
                project,
                _first_position(conn, row["owner_id"], status),
                now,
                now,
            ),
        )
    return conn.execute(
        "SELECT * FROM task_board WHERE memory_id = ?", (memory_id,)
    ).fetchone()


def set_inferred_status(
    conn: sqlite3.Connection,
    memory_id: str,
    workflow_status: str | None,
    *,
    project_key: str | None = None,
) -> str:
    """Apply an explicit judge status, or preserve the current board state."""
    board = ensure_metadata(
        conn,
        memory_id,
        workflow_status=workflow_status or "unknown",
        project_key=project_key,
    )
    if workflow_status is None or workflow_status not in WORKFLOW_STATUSES:
        return str(board["workflow_status"])
    if workflow_status != board["workflow_status"]:
        now = utcnow()
        owner_id = conn.execute(
            "SELECT owner_id FROM memories WHERE id = ?", (memory_id,)
        ).fetchone()["owner_id"]
        conn.execute(
            """UPDATE task_board
                  SET workflow_status=?, position=?, version=version+1,
                      updated_at=?
                WHERE memory_id=?""",
            (
                workflow_status,
                _first_position(conn, owner_id, workflow_status),
                now,
                memory_id,
            ),
        )
    return workflow_status


def status_for(conn: sqlite3.Connection, memory_id: str) -> str | None:
    row = conn.execute(
        "SELECT workflow_status FROM task_board WHERE memory_id = ?", (memory_id,)
    ).fetchone()
    return str(row["workflow_status"]) if row else None


def _task_row(conn: sqlite3.Connection, memory_id: str) -> sqlite3.Row:
    row = conn.execute(
        """SELECT m.*, tb.workflow_status, tb.project_key, tb.position,
                  tb.version AS board_version,
                  tb.updated_at AS board_updated_at
             FROM memories m
             JOIN task_board tb ON tb.memory_id = m.id
            WHERE m.id = ? AND m.type = 'task'""",
        (memory_id,),
    ).fetchone()
    if row is None:
        raise mutate.MutationError("unknown task", status_code=404)
    return row


def _as_item(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


def _ensure_all(conn: sqlite3.Connection) -> None:
    missing = conn.execute(
        """SELECT m.id
             FROM memories m
             LEFT JOIN task_board tb ON tb.memory_id = m.id
            WHERE m.type = 'task' AND tb.memory_id IS NULL"""
    ).fetchall()
    for row in missing:
        ensure_metadata(conn, row["id"])


def board_data(
    conn: sqlite3.Connection, *, owner_id: str, include_archived: bool = False
) -> dict[str, Any]:
    _ensure_all(conn)
    lifecycle = "" if include_archived else "AND m.status = 'active'"
    rows = conn.execute(
        f"""SELECT m.*, tb.workflow_status, tb.project_key, tb.position,
                   tb.version AS board_version,
                   tb.updated_at AS board_updated_at
              FROM memories m
              JOIN task_board tb ON tb.memory_id = m.id
             WHERE m.owner_id = ? AND m.type = 'task' {lifecycle}
             ORDER BY CASE tb.workflow_status
                        WHEN 'unknown' THEN 0 WHEN 'todo' THEN 1
                        WHEN 'doing' THEN 2 ELSE 3 END,
                      tb.position ASC, m.id ASC""",
        (owner_id,),
    ).fetchall()
    counts = {status: 0 for status in WORKFLOW_STATUSES}
    projects: dict[str | None, int] = {}
    for row in rows:
        counts[row["workflow_status"]] += 1
        projects[row["project_key"]] = projects.get(row["project_key"], 0) + 1
    project_items = [
        {"key": key, "label": key or "Unknown project", "count": count}
        for key, count in sorted(
            projects.items(), key=lambda item: (item[0] is None, item[0] or "")
        )
    ]
    return {
        "items": [_as_item(row) for row in rows],
        "counts": counts,
        "projects": project_items,
        "total": len(rows),
        "include_archived": include_archived,
    }


class TaskCreate(BaseModel):
    text: str = Field(min_length=1, max_length=200)
    workflow_status: WorkflowStatus = "unknown"
    project_key: str | None = Field(default=None, max_length=160)
    importance: float = Field(default=0.6, ge=0, le=1)
    valid_until: str | None = None

    @field_validator("text")
    @classmethod
    def clean_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("text cannot be empty")
        return value

    @field_validator("project_key")
    @classmethod
    def clean_project(cls, value: str | None) -> str | None:
        return normalize_project(value)


class TaskPatch(BaseModel):
    text: str | None = Field(default=None, min_length=1, max_length=200)
    workflow_status: WorkflowStatus | None = None
    project_key: str | None = Field(default=None, max_length=160)
    importance: float | None = Field(default=None, ge=0, le=1)
    valid_until: str | None = None
    before_id: str | None = None
    after_id: str | None = None
    expected_board_version: int = Field(ge=1)
    expected_memory_updated_at: str | None = None

    @field_validator("text")
    @classmethod
    def clean_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("text cannot be empty")
        return value

    @field_validator("project_key")
    @classmethod
    def clean_project(cls, value: str | None) -> str | None:
        return normalize_project(value)


def _anchor(
    conn: sqlite3.Connection,
    *,
    memory_id: str | None,
    moving_id: str,
    owner_id: str,
    workflow_status: str,
) -> float | None:
    if memory_id is None:
        return None
    if memory_id == moving_id:
        raise mutate.MutationError("a task cannot be its own ordering anchor")
    row = conn.execute(
        """SELECT tb.position, tb.workflow_status, m.owner_id, m.status
             FROM task_board tb
             JOIN memories m ON m.id = tb.memory_id
            WHERE tb.memory_id = ? AND m.type = 'task'""",
        (memory_id,),
    ).fetchone()
    if row is None:
        raise mutate.MutationError("unknown ordering anchor")
    if (
        row["owner_id"] != owner_id
        or row["workflow_status"] != workflow_status
        or row["status"] != "active"
    ):
        raise mutate.MutationError("ordering anchor is outside the target column")
    return float(row["position"])


def _rebalance(conn: sqlite3.Connection, owner_id: str, workflow_status: str) -> None:
    rows = conn.execute(
        """SELECT tb.memory_id
             FROM task_board tb
             JOIN memories m ON m.id = tb.memory_id
            WHERE m.owner_id = ? AND tb.workflow_status = ?
            ORDER BY tb.position ASC, tb.memory_id ASC""",
        (owner_id, workflow_status),
    ).fetchall()
    conn.executemany(
        "UPDATE task_board SET position=? WHERE memory_id=?",
        [(float(index * POSITION_STEP), row["memory_id"]) for index, row in enumerate(rows)],
    )


def _move_position(
    conn: sqlite3.Connection,
    *,
    moving_id: str,
    owner_id: str,
    workflow_status: str,
    before_id: str | None,
    after_id: str | None,
) -> float:
    before = _anchor(
        conn,
        memory_id=before_id,
        moving_id=moving_id,
        owner_id=owner_id,
        workflow_status=workflow_status,
    )
    after = _anchor(
        conn,
        memory_id=after_id,
        moving_id=moving_id,
        owner_id=owner_id,
        workflow_status=workflow_status,
    )
    if before is not None and after is not None:
        if before >= after:
            raise mutate.MutationError("ordering anchors are reversed")
        if after - before <= POSITION_EPSILON:
            _rebalance(conn, owner_id, workflow_status)
            return _move_position(
                conn,
                moving_id=moving_id,
                owner_id=owner_id,
                workflow_status=workflow_status,
                before_id=before_id,
                after_id=after_id,
            )
        return (before + after) / 2
    if before is not None:
        return before + POSITION_STEP
    if after is not None:
        return after - POSITION_STEP
    return _first_position(conn, owner_id, workflow_status)


def _apply_index(request: Request, result: mutate.MutationResult | None, item: dict[str, Any]) -> bool:
    try:
        if result is not None:
            result.apply_index(request.app.state.qdrant)
        vectors.set_payload(
            request.app.state.qdrant,
            vectors.MEMORIES,
            [item["id"]],
            {"task_status": item["workflow_status"]},
        )
        return False
    except Exception:
        request.app.state.index_dirty = True
        return True


@router.get("/v1/admin/tasks/board")
def get_board(request: Request, include_archived: bool = False) -> dict[str, Any]:
    settings = get_settings()
    return board_data(
        request.app.state.conn,
        owner_id=settings.owner_id,
        include_archived=include_archived,
    )


@router.post("/v1/admin/tasks", status_code=201)
def create_task(body: TaskCreate, request: Request) -> dict[str, Any]:
    settings = get_settings()
    project = normalize_project(body.project_key)
    with transaction(request.app.state.conn):
        memory_id = store.add_memory(
            request.app.state.conn,
            request.app.state.qdrant,
            request.app.state.embedder,
            owner_id=settings.owner_id,
            text=body.text,
            type="task",
            scope="project" if project else "user",
            scope_key=project,
            importance=body.importance,
            confidence=0.9,
            valid_until=body.valid_until,
            task_status=body.workflow_status,
        )
        item = _as_item(_task_row(request.app.state.conn, memory_id))
    return {"task": item, "index_stale": _apply_index(request, None, item)}


@router.patch("/v1/admin/tasks/{memory_id}")
def patch_task(
    memory_id: str, body: TaskPatch, request: Request
) -> dict[str, Any]:
    fields = body.model_fields_set
    index_result: mutate.MutationResult | None = None
    try:
        with transaction(request.app.state.conn):
            before = _task_row(request.app.state.conn, memory_id)
            if before["status"] != "active":
                raise mutate.MutationError(
                    "archived tasks must be restored before editing", status_code=409
                )
            if before["board_version"] != body.expected_board_version:
                raise mutate.MutationError(
                    "task board changed since it was opened", status_code=409
                )

            memory_changes: dict[str, Any] = {}
            for field in ("text", "importance", "valid_until"):
                if field in fields:
                    memory_changes[field] = getattr(body, field)
            if "project_key" in fields:
                project = normalize_project(body.project_key)
                memory_changes.update(
                    {
                        "scope": "project" if project else "user",
                        "scope_key": project,
                    }
                )
            if memory_changes:
                if body.expected_memory_updated_at is None:
                    raise mutate.MutationError(
                        "expected_memory_updated_at is required for memory edits"
                    )
                index_result = mutate.update_memory(
                    request.app.state.conn,
                    request.app.state.qdrant,
                    request.app.state.embedder,
                    memory_id=memory_id,
                    changes=memory_changes,
                    expected_updated_at=body.expected_memory_updated_at,
                )

            target_status = body.workflow_status or before["workflow_status"]
            reorder = (
                target_status != before["workflow_status"]
                or "before_id" in fields
                or "after_id" in fields
            )
            position = (
                _move_position(
                    request.app.state.conn,
                    moving_id=memory_id,
                    owner_id=before["owner_id"],
                    workflow_status=target_status,
                    before_id=body.before_id,
                    after_id=body.after_id,
                )
                if reorder
                else float(before["position"])
            )
            project_key = (
                normalize_project(body.project_key)
                if "project_key" in fields
                else before["project_key"]
            )
            board_changed = (
                target_status != before["workflow_status"]
                or project_key != before["project_key"]
                or position != float(before["position"])
            )
            if board_changed:
                now = utcnow()
                cur = request.app.state.conn.execute(
                    """UPDATE task_board
                          SET workflow_status=?, project_key=?, position=?,
                              version=version+1, updated_at=?
                        WHERE memory_id=? AND version=?""",
                    (
                        target_status,
                        project_key,
                        position,
                        now,
                        memory_id,
                        body.expected_board_version,
                    ),
                )
                if cur.rowcount != 1:
                    raise mutate.MutationError(
                        "task board changed concurrently", status_code=409
                    )
            item = _as_item(_task_row(request.app.state.conn, memory_id))
    except mutate.MutationError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc

    stale = _apply_index(request, index_result, item)
    return {"task": item, "index_stale": stale}
