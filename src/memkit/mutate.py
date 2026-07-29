"""Connection-level memory mutations.

SQLite is committed by the caller. Qdrant work is returned and must be applied
only after that commit, so the vector index can never contain an uncommitted
memory revision.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from qdrant_client import QdrantClient

from . import store, vectors
from .db import utcnow
from .embed import Embedder

QdrantOp = Literal["none", "upsert", "payload", "delete"]


class MutationError(ValueError):
    def __init__(self, message: str, *, status_code: int = 422) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass
class MutationResult:
    row: dict[str, Any] | None
    qdrant_op: QdrantOp = "none"
    point: tuple[str, list[float], dict[str, Any]] | None = None
    payload: dict[str, Any] | None = None
    point_ids: list[str] = field(default_factory=list)
    reembedded: bool = False
    skipped_reason: str | None = None
    sources_unlinked: int = 0
    successors_unlinked: int = 0

    def apply_index(self, client: QdrantClient) -> None:
        if self.qdrant_op == "upsert" and self.point:
            vectors.upsert(client, vectors.MEMORIES, [self.point])
        elif self.qdrant_op == "payload" and self.payload:
            vectors.set_payload(
                client, vectors.MEMORIES, self.point_ids, self.payload
            )
        elif self.qdrant_op == "delete":
            vectors.delete_points(client, vectors.MEMORIES, self.point_ids)


@dataclass
class BulkResult:
    requested: int
    results: list[MutationResult]
    skipped: list[dict[str, str]]

    @property
    def applied(self) -> int:
        return len(self.results)

    def apply_index(self, client: QdrantClient) -> None:
        upserts = [result.point for result in self.results if result.point]
        deletes = [
            point_id
            for result in self.results
            if result.qdrant_op == "delete"
            for point_id in result.point_ids
        ]
        if upserts:
            vectors.upsert(client, vectors.MEMORIES, upserts)
        if deletes:
            vectors.delete_points(client, vectors.MEMORIES, deletes)
        payload_groups: dict[tuple[tuple[str, Any], ...], list[str]] = {}
        for result in self.results:
            if result.qdrant_op == "payload" and result.payload:
                key = tuple(sorted(result.payload.items()))
                payload_groups.setdefault(key, []).extend(result.point_ids)
        for items, point_ids in payload_groups.items():
            vectors.set_payload(
                client, vectors.MEMORIES, point_ids, dict(items)
            )


def _row(conn: sqlite3.Connection, memory_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
    if row is None:
        raise MutationError("unknown memory", status_code=404)
    return row


def _next_timestamp(previous: str) -> str:
    now = utcnow()
    if now != previous:
        return now
    try:
        parsed = datetime.fromisoformat(previous.replace("Z", "+00:00"))
        return (parsed + timedelta(seconds=1)).astimezone(UTC).isoformat(
            timespec="seconds"
        ).replace("+00:00", "Z")
    except ValueError:
        return now


def _ensure_task_board(conn: sqlite3.Connection, row: dict[str, Any]) -> str | None:
    if row["type"] != "task":
        return None
    existing = conn.execute(
        "SELECT workflow_status FROM task_board WHERE memory_id = ?",
        (row["id"],),
    ).fetchone()
    if existing is not None:
        return str(existing["workflow_status"])
    first = conn.execute(
        """SELECT MIN(tb.position) AS position
             FROM task_board tb
             JOIN memories m ON m.id = tb.memory_id
            WHERE m.owner_id = ? AND tb.workflow_status = 'unknown'""",
        (row["owner_id"],),
    ).fetchone()["position"]
    now = utcnow()
    conn.execute(
        """INSERT INTO task_board
           (memory_id, workflow_status, project_key, position, version,
            created_at, updated_at)
           VALUES (?, 'unknown', ?, ?, 1, ?, ?)""",
        (
            row["id"],
            (row["scope_key"] or "").strip() or None
            if row["scope"] != "user"
            else None,
            (float(first) if first is not None else 1024.0) - 1024.0,
            now,
            now,
        ),
    )
    return "unknown"


def _vector_payload(
    conn: sqlite3.Connection, row: sqlite3.Row | dict[str, Any]
) -> dict[str, Any]:
    saved = dict(row)
    return store.mem_payload(saved, task_status=_ensure_task_board(conn, saved))


def update_memory(
    conn: sqlite3.Connection,
    client: QdrantClient,
    embedder: Embedder,
    *,
    memory_id: str,
    changes: dict[str, Any],
    expected_updated_at: str | None = None,
) -> MutationResult:
    """Update one row without committing or touching Qdrant."""
    before = _row(conn, memory_id)
    if expected_updated_at is not None and expected_updated_at != before["updated_at"]:
        raise MutationError(
            "memory changed since it was opened", status_code=409
        )

    allowed = {
        "text",
        "type",
        "scope",
        "scope_key",
        "agent_id",
        "importance",
        "confidence",
        "valid_until",
        "status",
        "judge_run_id",
    }
    unknown = set(changes) - allowed
    if unknown:
        raise MutationError(f"unsupported fields: {', '.join(sorted(unknown))}")
    if not changes:
        return MutationResult(row=dict(before))

    after = dict(before)
    after.update(changes)
    if after["scope"] == "user":
        after["scope_key"] = None
    if after["status"] not in ("active", "expired", "superseded"):
        raise MutationError("invalid status")
    if before["status"] == "superseded" and after["status"] == "active":
        after["superseded_by"] = None

    text_changed = after["text"] != before["text"]
    restoring = before["status"] != "active" and after["status"] == "active"
    expiring = before["status"] == "active" and after["status"] != "active"
    vector: list[float] | None = None
    if text_changed or restoring:
        vector = embedder.encode_one(after["text"])

    after["updated_at"] = _next_timestamp(before["updated_at"])
    cur = conn.execute(
        """UPDATE memories
              SET text=?, type=?, scope=?, scope_key=?, agent_id=?,
                  importance=?, confidence=?, valid_until=?, status=?,
                  superseded_by=?, judge_run_id=?, updated_at=?
            WHERE id=? AND updated_at=?""",
        (
            after["text"],
            after["type"],
            after["scope"],
            after["scope_key"],
            after["agent_id"],
            after["importance"],
            after["confidence"],
            after["valid_until"],
            after["status"],
            after["superseded_by"],
            after["judge_run_id"],
            after["updated_at"],
            memory_id,
            before["updated_at"],
        ),
    )
    if cur.rowcount != 1:
        raise MutationError("memory changed concurrently", status_code=409)

    saved = dict(_row(conn, memory_id))
    _ensure_task_board(conn, saved)
    if expiring:
        return MutationResult(
            saved, qdrant_op="delete", point_ids=[memory_id]
        )
    if text_changed or restoring:
        assert vector is not None
        return MutationResult(
            saved,
            qdrant_op="upsert",
            point=(memory_id, vector, _vector_payload(conn, saved)),
            point_ids=[memory_id],
            reembedded=True,
        )

    payload_fields = {"type", "scope", "scope_key", "agent_id", "importance"}
    payload_changes = {
        key: saved[key] for key in payload_fields if key in changes
    }
    if payload_changes:
        payload_changes["updated_at"] = saved["updated_at"]
        return MutationResult(
            saved,
            qdrant_op="payload",
            payload=payload_changes,
            point_ids=[memory_id],
        )
    return MutationResult(saved)


def set_status(
    conn: sqlite3.Connection,
    client: QdrantClient,
    embedder: Embedder,
    *,
    memory_id: str,
    status: str,
) -> MutationResult:
    return update_memory(
        conn,
        client,
        embedder,
        memory_id=memory_id,
        changes={"status": status},
    )


def supersede(
    conn: sqlite3.Connection,
    client: QdrantClient,
    *,
    memory_id: str,
    by_id: str,
) -> MutationResult:
    if memory_id == by_id:
        raise MutationError("a memory cannot supersede itself")
    source = _row(conn, memory_id)
    target = _row(conn, by_id)
    if source["status"] != "active":
        raise MutationError("only an active memory can be superseded")
    if source["owner_id"] != target["owner_id"]:
        raise MutationError("memories must have the same owner")
    if target["status"] != "active":
        raise MutationError("successor must be active")

    cursor = target
    seen = {memory_id}
    while cursor["superseded_by"]:
        next_id = cursor["superseded_by"]
        if next_id in seen:
            raise MutationError("supersede would create a cycle")
        seen.add(next_id)
        cursor = _row(conn, next_id)

    updated = _next_timestamp(source["updated_at"])
    conn.execute(
        """UPDATE memories
              SET status='superseded', superseded_by=?, updated_at=?
            WHERE id=?""",
        (by_id, updated, memory_id),
    )
    return MutationResult(
        row=dict(_row(conn, memory_id)),
        qdrant_op="delete",
        point_ids=[memory_id],
    )


def hard_delete(
    conn: sqlite3.Connection,
    client: QdrantClient,
    *,
    memory_id: str,
) -> MutationResult:
    row = _row(conn, memory_id)
    successor_cur = conn.execute(
        "UPDATE memories SET superseded_by=NULL WHERE superseded_by=?",
        (memory_id,),
    )
    sources_cur = conn.execute(
        "DELETE FROM memory_sources WHERE memory_id=?", (memory_id,)
    )
    conn.execute("DELETE FROM memories WHERE id=?", (memory_id,))
    return MutationResult(
        row=dict(row),
        qdrant_op="delete",
        point_ids=[memory_id],
        sources_unlinked=sources_cur.rowcount,
        successors_unlinked=successor_cur.rowcount,
    )


def bulk(
    conn: sqlite3.Connection,
    client: QdrantClient,
    embedder: Embedder,
    *,
    ids: list[str],
    op: str,
    value: Any = None,
) -> BulkResult:
    results: list[MutationResult] = []
    skipped: list[dict[str, str]] = []
    unique_ids = list(dict.fromkeys(ids))
    if op == "restore":
        placeholders = ",".join("?" for _ in unique_ids)
        rows = conn.execute(
            f"SELECT * FROM memories WHERE id IN ({placeholders}) ORDER BY id",
            unique_ids,
        ).fetchall()
        found = {row["id"] for row in rows}
        skipped.extend(
            {"id": memory_id, "reason": "unknown memory"}
            for memory_id in unique_ids
            if memory_id not in found
        )
        vectors_batch = embedder.encode([row["text"] for row in rows])
        for row, vector in zip(rows, vectors_batch, strict=True):
            updated = _next_timestamp(row["updated_at"])
            conn.execute(
                """UPDATE memories SET status='active', superseded_by=NULL,
                       updated_at=? WHERE id=?""",
                (updated, row["id"]),
            )
            saved = dict(_row(conn, row["id"]))
            results.append(
                MutationResult(
                    saved,
                    qdrant_op="upsert",
                    point=(row["id"], vector, _vector_payload(conn, saved)),
                    point_ids=[row["id"]],
                    reembedded=True,
                )
            )
        return BulkResult(requested=len(ids), results=results, skipped=skipped)

    for memory_id in unique_ids:
        try:
            if op == "expire":
                result = set_status(
                    conn, client, embedder, memory_id=memory_id, status="expired"
                )
            elif op == "hard_delete":
                result = hard_delete(conn, client, memory_id=memory_id)
            elif op == "set_type":
                result = update_memory(
                    conn, client, embedder,
                    memory_id=memory_id, changes={"type": value},
                )
            elif op == "set_importance":
                result = update_memory(
                    conn, client, embedder,
                    memory_id=memory_id, changes={"importance": value},
                )
            elif op == "set_scope":
                if not isinstance(value, dict) or "scope" not in value:
                    raise MutationError("set_scope value must contain scope")
                result = update_memory(
                    conn, client, embedder,
                    memory_id=memory_id, changes=value,
                )
            else:
                raise MutationError("unknown bulk operation")
            results.append(result)
        except MutationError as exc:
            skipped.append({"id": memory_id, "reason": str(exc)})
    return BulkResult(requested=len(ids), results=results, skipped=skipped)
