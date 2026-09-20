"""Durable Postgres-to-Qdrant delivery."""

from __future__ import annotations

import logging
import uuid
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import psycopg
from psycopg.types.json import Jsonb
from qdrant_client import QdrantClient

from . import maintenance, vectors
from .db import Row, advisory_lock, utcnow
from .embed import Embedder

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DrainOutcome:
    applied: int = 0
    failed: int = 0


def enqueue(
    conn: psycopg.Connection,
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
    row = conn.execute(
        """INSERT INTO index_outbox
           (collection,entity_id,operation,payload,status,attempts,
            available_at,created_at,updated_at)
           VALUES (%s,%s,%s,%s,'pending',0,%s,%s,%s)
           RETURNING id""",
        (collection, str(entity_id), operation, Jsonb(payload or {}), now, now, now),
    ).fetchone()
    if row is None:  # pragma: no cover - RETURNING cannot be empty here
        raise RuntimeError("outbox insert returned no row")
    return int(row["id"])


def index_lock_name(scope_id: str) -> str:
    """The advisory lock guarding index writes for one scope.

    Exported because erasure has to take the same one; when the two names drifted
    apart, each held a lock nobody else wanted and a queued delivery could put
    back a vector that erasure had just removed.
    """
    return f"memkit:index:{scope_id}"


@contextmanager
def scope_barrier(conn: psycopg.Connection, scope_id: str):
    """Cross-process barrier shared by erasure and external index writes.

    A late delivery must not resurrect a vector that erasure just removed. The
    SQLite build coordinated that with a lock file beside the database, which
    only worked because every process shared a filesystem; an advisory lock is
    held by the database itself, so it also holds between containers.
    """
    with conn.transaction():
        advisory_lock(conn, index_lock_name(scope_id))
        yield


def _claim_next(
    conn: psycopg.Connection,
    *,
    ignore_schedule: bool,
    lease_seconds: int,
) -> Row | None:
    """Lease the next deliverable operation, or None.

    Ordering per entity is the invariant: an upsert must never overtake an
    earlier delete for the same point, or the index ends up holding a row the
    store has dropped. That is why a candidate is only eligible when no earlier
    operation for the same entity is still outstanding.

    One statement, so two workers cannot lease the same row: the subquery takes
    a row lock with SKIP LOCKED, which replaces the whole-database write lock
    that BEGIN IMMEDIATE used to provide.
    """
    now = utcnow()
    with conn.transaction():
        # Reclaim leases whose holder died before finishing.
        conn.execute(
            """UPDATE index_outbox
                  SET status='pending',claim_token=NULL,lease_expires_at=NULL,updated_at=%s
                WHERE status='processing' AND lease_expires_at IS NOT NULL
                  AND lease_expires_at <= %s""",
            (now, now),
        )
        schedule = "" if ignore_schedule else "AND candidate.available_at <= %(now)s"
        row = conn.execute(
            f"""UPDATE index_outbox SET
                    status='processing',
                    claim_token=%(token)s,
                    lease_expires_at=%(expires)s,
                    updated_at=%(now)s
                WHERE id = (
                    SELECT candidate.id FROM index_outbox candidate
                     WHERE candidate.status='pending' {schedule}
                       AND NOT EXISTS (
                           SELECT 1 FROM index_outbox earlier
                            WHERE earlier.collection=candidate.collection
                              AND earlier.entity_id=candidate.entity_id
                              AND earlier.id < candidate.id
                              AND earlier.status IN ('pending','processing')
                       )
                     ORDER BY candidate.id
                     FOR UPDATE SKIP LOCKED
                     LIMIT 1
                )
                RETURNING *""",
            {
                "token": str(uuid.uuid4()),
                "expires": now + timedelta(seconds=lease_seconds),
                "now": now,
            },
        ).fetchone()
    return row


def _authoritative_payload(
    conn: psycopg.Connection, collection: str, entity_id: str
) -> dict[str, Any] | None:
    from . import store
    from .limits import MIN_INDEX_CHARS

    if collection == vectors.MEMORIES:
        current = conn.execute("SELECT * FROM memories WHERE id=%s", (entity_id,)).fetchone()
        return store.mem_payload(current) if current and store.memory_active(current) else None
    if collection == vectors.RAW:
        current = conn.execute(
            """SELECT m.*,s.scope_id,s.agent_id FROM messages m
               JOIN sessions s ON s.id=m.session_id
               WHERE m.id=%s AND m.role='user' AND length(m.content)>=%s""",
            (int(entity_id), MIN_INDEX_CHARS),
        ).fetchone()
        return store.raw_payload(current) if current else None
    raise ValueError(f"unknown index collection: {collection}")


def ensure_pending(
    conn: psycopg.Connection,
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


def _precompute_vectors(rows: list[Row], embedder: Embedder) -> dict[int, list[float]]:
    """Embed every upsert in one call.

    Delivery used to embed one row at a time, each acquiring the embedder lock.
    A hundred-event batch therefore serialised a hundred model calls, and the
    evidence endpoints drained inline, so the HTTP response waited for all of
    them. `reindex` already batched; this is the same shape.

    Returns what it managed to embed. A batch failure is not fatal: the caller
    falls back to a single-text call per row, so one unembeddable text cannot
    poison the rest of the batch.
    """
    pending: list[tuple[int, str]] = []
    for row in rows:
        if row["operation"] != "upsert":
            continue
        text = str((row["payload"] or {}).get("text") or "")
        if text:
            pending.append((int(row["id"]), text))
    if not pending:
        return {}
    try:
        encoded = embedder.encode([text for _, text in pending])
    except Exception as exc:
        logger.warning("batch embedding failed; falling back per row: %s", exc)
        return {}
    return {row_id: vector for (row_id, _), vector in zip(pending, encoded, strict=True)}


def _deliver(
    conn: psycopg.Connection,
    client: QdrantClient,
    embedder: Embedder,
    row: Row,
    *,
    vector: list[float] | None,
    max_attempts: int,
) -> bool:
    """Deliver one claimed operation. True when applied, False when retained."""
    token = row["claim_token"]
    try:
        payload = dict(row["payload"] or {})
        scope_id = str(payload.get("scope_id") or "")
        barrier = scope_barrier(conn, scope_id) if scope_id else nullcontext()
        with conn.transaction():
            maintenance.require_write(conn)
            with barrier:
                # Fence before an external side effect, and keep the row locked
                # until it finishes so a reclaimer cannot steal this delivery.
                claim = conn.execute(
                    """SELECT 1 FROM index_outbox WHERE id=%s AND status='processing'
                       AND claim_token=%s AND lease_expires_at>now() FOR UPDATE""",
                    (row["id"], token),
                ).fetchone()
                if claim is None:
                    return False
                point_id: str | int = (
                    int(row["entity_id"]) if row["collection"] == vectors.RAW else row["entity_id"]
                )
                current = (
                    _authoritative_payload(conn, row["collection"], str(row["entity_id"]))
                    if scope_id
                    else payload
                )
                if current is not None and row["operation"] == "upsert" and not payload.get("text"):
                    raise ValueError("outbox upsert payload has no text")
                if current is None or (not scope_id and row["operation"] == "delete"):
                    vectors.delete_points(client, row["collection"], [point_id])
                elif row["operation"] == "delete" or current != payload:
                    # A newer transaction owns the next event. In particular an
                    # old archive event cannot delete a now-restored memory.
                    logger.info("skipping obsolete index delivery %s", row["id"])
                else:
                    text = str(payload.get("text") or "")
                    if not text:
                        raise ValueError("outbox upsert payload has no text")
                    point_vector = vector if vector is not None else embedder.encode_one(text)
                    vectors.upsert(client, row["collection"], [(point_id, point_vector, payload)])
                conn.execute(
                    """UPDATE index_outbox SET status='done',last_error=NULL,updated_at=%s,
                       claim_token=NULL,lease_expires_at=NULL WHERE id=%s AND claim_token=%s""",
                    (utcnow(), row["id"], token),
                )
    except maintenance.MaintenanceBusy:
        conn.execute(
            """UPDATE index_outbox SET status='pending',claim_token=NULL,lease_expires_at=NULL
               WHERE id=%s AND status='processing' AND claim_token=%s""",
            (row["id"], token),
        )
        raise
    except Exception as exc:  # delivery must survive transient Qdrant failures
        attempts = int(row["attempts"]) + 1
        terminal = attempts >= max_attempts
        delay = min(300, 2 ** min(attempts, 8))
        conn.execute(
            """UPDATE index_outbox
                  SET status=%s,attempts=%s,available_at=%s,last_error=%s,updated_at=%s,
                      claim_token=NULL,lease_expires_at=NULL
                WHERE id=%s AND status='processing' AND claim_token=%s""",
            (
                "failed" if terminal else "pending",
                attempts,
                utcnow() + timedelta(seconds=delay),
                str(exc)[:1000],
                utcnow(),
                row["id"],
                token,
            ),
        )
        logger.warning("index delivery %s failed: %s", row["id"], exc)
        return False
    return True


def drain(
    conn: psycopg.Connection,
    client: QdrantClient,
    embedder: Embedder,
    *,
    limit: int = 100,
    max_attempts: int = 8,
    ignore_schedule: bool = False,
    claim_lease_seconds: int = 300,
    batch_size: int = 32,
) -> DrainOutcome:
    """Apply pending operations idempotently and retain failures for retry.

    Claims in batches so the embedder is called once per batch rather than once
    per row; each row is still delivered and marked individually, so a poison
    row fails alone.
    """
    applied = failed = 0
    remaining = limit
    while remaining > 0:
        rows: list[Row] = []
        for _ in range(min(batch_size, remaining)):
            row = _claim_next(
                conn,
                ignore_schedule=ignore_schedule,
                lease_seconds=claim_lease_seconds,
            )
            if row is None:
                break
            rows.append(row)
        if not rows:
            break
        precomputed = _precompute_vectors(rows, embedder)
        for row in rows:
            if _deliver(
                conn,
                client,
                embedder,
                row,
                vector=precomputed.get(int(row["id"])),
                max_attempts=max_attempts,
            ):
                applied += 1
            else:
                failed += 1
        remaining -= len(rows)
    return DrainOutcome(applied=applied, failed=failed)


def pending_count(conn: psycopg.Connection) -> int:
    return int(
        conn.execute(
            "SELECT COUNT(*) AS n FROM index_outbox\n"
            "             WHERE status IN ('pending','processing','failed')"
        ).fetchone()[0]
    )
