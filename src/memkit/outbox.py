"""Durable SQLite-to-Qdrant delivery."""

from __future__ import annotations

import fcntl
import json
import logging
import sqlite3
import uuid
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
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
    cur = conn.execute(
        """INSERT INTO index_outbox
           (collection,entity_id,operation,payload_json,status,attempts,
            available_at,created_at,updated_at)
           VALUES (?,?,?,?,'pending',0,?,?,?)""",
        (collection, str(entity_id), operation, encoded, now, now, now),
    )
    return int(cur.lastrowid)


def _database_path(conn: sqlite3.Connection) -> Path:
    path = str(conn.execute("PRAGMA database_list").fetchone()[2])
    if not path:
        raise RuntimeError("index delivery barrier requires a file-backed SQLite database")
    return Path(path)


@contextmanager
def owner_barrier(conn: sqlite3.Connection, owner_id: str):
    """Cross-process barrier shared by owner erasure and external index writes."""
    digest = sha256(owner_id.encode()).hexdigest()[:16]
    lock_path = _database_path(conn).with_suffix(f".owner-{digest}.index.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _claim_next(
    conn: sqlite3.Connection,
    *,
    ignore_schedule: bool,
    lease_seconds: int,
) -> sqlite3.Row | None:
    now = utcnow()
    expires = (
        (datetime.now(UTC) + timedelta(seconds=lease_seconds))
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )
    conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            """UPDATE index_outbox
                  SET status='pending',claim_token=NULL,lease_expires_at=NULL,updated_at=?
                WHERE status='processing' AND lease_expires_at IS NOT NULL
                  AND lease_expires_at<=?""",
            (now, now),
        )
        schedule = "" if ignore_schedule else "AND candidate.available_at<=?"
        params: tuple[Any, ...] = () if ignore_schedule else (now,)
        row = conn.execute(
            f"""SELECT candidate.* FROM index_outbox candidate
                  WHERE candidate.status='pending' {schedule}
                    AND NOT EXISTS (
                        SELECT 1 FROM index_outbox earlier
                         WHERE earlier.collection=candidate.collection
                           AND earlier.entity_id=candidate.entity_id
                           AND earlier.id<candidate.id
                           AND earlier.status IN ('pending','processing')
                    )
                  ORDER BY candidate.id LIMIT 1""",
            params,
        ).fetchone()
        if row is None:
            conn.execute("COMMIT")
            return None
        token = str(uuid.uuid4())
        changed = conn.execute(
            """UPDATE index_outbox
                  SET status='processing',claim_token=?,lease_expires_at=?,updated_at=?
                WHERE id=? AND status='pending'""",
            (token, expires, now, row["id"]),
        ).rowcount
        conn.execute("COMMIT")
        if not changed:
            return None
        return conn.execute("SELECT * FROM index_outbox WHERE id=?", (row["id"],)).fetchone()
    except Exception:
        conn.execute("ROLLBACK")
        raise


def _authoritative_upsert_exists(
    conn: sqlite3.Connection,
    *,
    collection: str,
    entity_id: str,
    owner_id: str,
) -> bool:
    if collection == vectors.MEMORIES:
        row = conn.execute(
            "SELECT * FROM memories WHERE id=? AND owner_id=?",
            (entity_id, owner_id),
        ).fetchone()
        return bool(row and store_memory_active(row))
    if collection == vectors.RAW:
        row = conn.execute(
            """SELECT 1 FROM messages m JOIN sessions s ON s.id=m.session_id
                 WHERE m.id=? AND s.owner_id=?""",
            (entity_id, owner_id),
        ).fetchone()
        return row is not None
    return True


def store_memory_active(row: sqlite3.Row) -> bool:
    if row["status"] != "active":
        return False
    expiry = row["valid_until"]
    return not expiry or str(expiry) > utcnow()


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
    claim_lease_seconds: int = 300,
) -> DrainOutcome:
    """Apply pending operations idempotently and retain failures for retry."""
    applied = failed = 0
    for _ in range(limit):
        row = _claim_next(
            conn,
            ignore_schedule=ignore_schedule,
            lease_seconds=claim_lease_seconds,
        )
        if row is None:
            break
        token = row["claim_token"]
        try:
            payload = json.loads(row["payload_json"])
            owner_id = str(payload.get("owner_id") or "")
            barrier = owner_barrier(conn, owner_id) if owner_id else nullcontext()
            with barrier:
                point_id: str | int = (
                    int(row["entity_id"]) if row["collection"] == vectors.RAW else row["entity_id"]
                )
                if row["operation"] == "delete":
                    vectors.delete_points(client, row["collection"], [point_id])
                elif owner_id and not _authoritative_upsert_exists(
                    conn,
                    collection=row["collection"],
                    entity_id=str(row["entity_id"]),
                    owner_id=owner_id,
                ):
                    logger.info("skipping obsolete index delivery %s", row["id"])
                else:
                    text = str(payload.get("text") or "")
                    if not text:
                        raise ValueError("outbox upsert payload has no text")
                    vector = embedder.encode_one(text)
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
                          SET status=?,attempts=?,available_at=?,last_error=?,updated_at=?,
                              claim_token=NULL,lease_expires_at=NULL
                        WHERE id=? AND status='processing' AND claim_token=?""",
                    (
                        "failed" if terminal else "pending",
                        attempts,
                        available,
                        str(exc)[:1000],
                        utcnow(),
                        row["id"],
                        token,
                    ),
                )
            logger.warning("index delivery %s failed: %s", row["id"], exc)
            failed += 1
        else:
            with transaction(conn):
                conn.execute(
                    """UPDATE index_outbox
                          SET status='done',last_error=NULL,updated_at=?,claim_token=NULL,
                              lease_expires_at=NULL
                        WHERE id=? AND status='processing' AND claim_token=?""",
                    (utcnow(), row["id"], token),
                )
            applied += 1
    return DrainOutcome(applied=applied, failed=failed)


def pending_count(conn: sqlite3.Connection) -> int:
    return int(
        conn.execute(
            "SELECT COUNT(*) FROM index_outbox WHERE status IN ('pending','processing','failed')"
        ).fetchone()[0]
    )
