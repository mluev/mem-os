"""Durable SQLite-to-Qdrant delivery."""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from qdrant_client import QdrantClient

from . import vectors
from .db import transaction, utcnow
from .embed import Embedder

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DrainOutcome:
    applied: int = 0
    failed: int = 0


def enqueue(
    conn: sqlite3.Connection,
    *,
    collection: str,
    entity_id: str | int,
    operation: str,
    payload: dict[str, Any] | None = None,
) -> int:
    """Record one derived-index operation in the caller's transaction."""
    if operation not in {"upsert", "delete"}:
        raise ValueError(f"unsupported outbox operation: {operation}")
    now = utcnow()
    encoded = json.dumps(payload or {}, ensure_ascii=False, sort_keys=True)
    existing = conn.execute(
        """SELECT id FROM index_outbox
            WHERE collection=? AND entity_id=? AND operation=?
              AND status IN ('pending','processing')""",
        (collection, str(entity_id), operation),
    ).fetchone()
    if existing:
        conn.execute(
            """UPDATE index_outbox
                  SET payload_json=?, status='pending', available_at=?, updated_at=?
                WHERE id=?""",
            (encoded, now, now, existing["id"]),
        )
        return int(existing["id"])
    cur = conn.execute(
        """INSERT INTO index_outbox
           (collection,entity_id,operation,payload_json,status,attempts,
            available_at,created_at,updated_at)
           VALUES (?,?,?,?,'pending',0,?,?,?)""",
        (collection, str(entity_id), operation, encoded, now, now, now),
    )
    return int(cur.lastrowid)


def ensure_pending(
    conn: sqlite3.Connection,
    *,
    collection: str,
    entity_id: str | int,
    operation: str,
    payload: dict[str, Any],
) -> int:
    """Re-enqueue an idempotent delivery when no active operation remains."""
    return enqueue(
        conn,
        collection=collection,
        entity_id=entity_id,
        operation=operation,
        payload=payload,
    )


def drain(
    conn: sqlite3.Connection,
    client: QdrantClient,
    embedder: Embedder,
    *,
    limit: int = 100,
    max_attempts: int = 8,
    ignore_schedule: bool = False,
) -> DrainOutcome:
    """Apply pending operations idempotently and retain failures for retry."""
    now = utcnow()
    schedule_clause = "" if ignore_schedule else "AND available_at <= ?"
    params: tuple[Any, ...] = (limit,) if ignore_schedule else (now, limit)
    rows = conn.execute(
        f"""SELECT * FROM index_outbox
              WHERE status='pending' {schedule_clause}
              ORDER BY id LIMIT ?""",
        params,
    ).fetchall()
    applied = failed = 0
    for row in rows:
        with transaction(conn):
            claimed = conn.execute(
                """UPDATE index_outbox SET status='processing',updated_at=?
                    WHERE id=? AND status='pending'""",
                (now, row["id"]),
            ).rowcount
        if not claimed:
            continue
        try:
            if row["operation"] == "delete":
                point_id: str | int = (
                    int(row["entity_id"]) if row["collection"] == vectors.RAW else row["entity_id"]
                )
                vectors.delete_points(client, row["collection"], [point_id])
            else:
                payload = json.loads(row["payload_json"])
                text = str(payload.get("text") or "")
                if not text:
                    raise ValueError("outbox upsert payload has no text")
                vector = embedder.encode_one(text)
                point_id = (
                    int(row["entity_id"]) if row["collection"] == vectors.RAW else row["entity_id"]
                )
                vectors.upsert(client, row["collection"], [(point_id, vector, payload)])
        except Exception as exc:  # delivery must survive transient Qdrant failures
            attempts = int(row["attempts"]) + 1
            terminal = attempts >= max_attempts
            delay = min(300, 2 ** min(attempts, 8))
            available = (
                (datetime.now(UTC) + timedelta(seconds=delay))
                .isoformat(timespec="seconds")
                .replace("+00:00", "Z")
            )
            with transaction(conn):
                conn.execute(
                    """UPDATE index_outbox
                          SET status=?,attempts=?,available_at=?,last_error=?,updated_at=?
                        WHERE id=?""",
                    (
                        "failed" if terminal else "pending",
                        attempts,
                        available,
                        str(exc)[:1000],
                        utcnow(),
                        row["id"],
                    ),
                )
            logger.warning("index delivery %s failed: %s", row["id"], exc)
            failed += 1
        else:
            with transaction(conn):
                conn.execute(
                    """UPDATE index_outbox
                          SET status='done',last_error=NULL,updated_at=? WHERE id=?""",
                    (utcnow(), row["id"]),
                )
            applied += 1
    return DrainOutcome(applied=applied, failed=failed)


def pending_count(conn: sqlite3.Connection) -> int:
    return int(
        conn.execute(
            "SELECT COUNT(*) FROM index_outbox WHERE status IN ('pending','processing','failed')"
        ).fetchone()[0]
    )
