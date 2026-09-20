"""Generation-based, validated Qdrant rebuild."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import psycopg
from qdrant_client import QdrantClient

from . import maintenance, store, vectors
from .embed import Embedder
from .limits import MIN_INDEX_CHARS


class ReindexError(RuntimeError):
    pass


class ReindexCancelled(ReindexError):
    pass


def _generation(logical: str) -> str:
    return f"{logical}__g{time.time_ns()}"


def _write_rows(
    client: QdrantClient,
    embedder: Embedder,
    collection: str,
    rows: list[tuple[str | int, dict[str, Any]]],
    *,
    batch_size: int = 64,
) -> None:
    for offset in range(0, len(rows), batch_size):
        chunk = rows[offset : offset + batch_size]
        vectors_values = embedder.encode([payload["text"] for _, payload in chunk])
        vectors.upsert(
            client,
            collection,
            [
                (entity_id, vector, payload)
                for (entity_id, payload), vector in zip(chunk, vectors_values, strict=True)
            ],
        )


def _snapshot(conn: psycopg.Connection) -> tuple[int, list[Any], list[Any]]:
    """One stable read; the outbox ID is compatibility metadata, not a replay cursor."""
    previous = conn.isolation_level
    conn.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
    try:
        with conn.transaction():
            highwater = conn.execute(
                "SELECT COALESCE(MAX(id),0) AS id FROM index_outbox"
            ).fetchone()
            memory_rows = conn.execute("SELECT * FROM memories WHERE status='active'").fetchall()
            raw_rows = conn.execute(
                """SELECT m.*,s.scope_id,s.agent_id FROM messages m
                     JOIN sessions s ON s.id=m.session_id
                    WHERE m.role='user' AND length(m.content)>=%s""",
                (MIN_INDEX_CHARS,),
            ).fetchall()
    finally:
        conn.isolation_level = previous
    return int(highwater["id"]) if highwater else 0, memory_rows, raw_rows


def _rebuild_locked(
    conn: psycopg.Connection,
    client: QdrantClient,
    embedder: Embedder,
    *,
    cancelled: Callable[[], bool] | None = None,
    guard: Callable[[], None] | None = None,
    activate: bool = True,
) -> dict[str, Any]:
    """Build while the caller holds the exclusive memory gate."""
    snapshot, memory_rows, raw_rows = _snapshot(conn)
    generations = {
        vectors.MEMORIES: _generation(vectors.MEMORIES),
        vectors.RAW: _generation(vectors.RAW),
    }
    if cancelled and cancelled():
        raise ReindexCancelled("reindex cancelled before generation build")
    for generation in generations.values():
        vectors.create_empty_collection(client, generation)

    # ADR 0020: only active memories are indexed, so the collection holds
    # exactly one point per retrievable fact.
    indexable = [row for row in memory_rows if store.memory_active(row)]
    expected = {
        vectors.MEMORIES: {str(row["id"]): store.mem_payload(row) for row in indexable},
        vectors.RAW: {str(row["id"]): store.raw_payload(row) for row in raw_rows},
    }
    _write_rows(
        client,
        embedder,
        generations[vectors.MEMORIES],
        [(str(row["id"]), store.mem_payload(row)) for row in indexable],
    )
    if cancelled and cancelled():
        raise ReindexCancelled("reindex cancelled before activation")
    _write_rows(
        client,
        embedder,
        generations[vectors.RAW],
        [(int(row["id"]), store.raw_payload(row)) for row in raw_rows],
    )

    # Expiration is clock-driven even while writes are frozen.
    expired = {str(row["id"]) for row in indexable if not store.memory_active(row)}
    if expired:
        vectors.delete_points(client, generations[vectors.MEMORIES], sorted(expired))
        for memory_id in expired:
            expected[vectors.MEMORIES].pop(memory_id)
    for logical, generation in generations.items():
        if vectors.exact_payloads(client, generation) != expected[logical]:
            raise ReindexError(f"{logical} generation payload validation failed")
    if cancelled and cancelled():
        raise ReindexCancelled("reindex cancelled before activation")
    if activate:
        with conn.transaction():
            if guard is not None:
                guard()
            vectors.swap_aliases(client, generations)
    return {
        "generation": generations,
        "snapshot_outbox_id": snapshot,
        "replayed_through": snapshot,
        "memories": len(vectors.exact_ids(client, generations[vectors.MEMORIES])),
        "raw": len(vectors.exact_ids(client, generations[vectors.RAW])),
        "activated": activate,
    }


def rebuild(
    conn: psycopg.Connection,
    client: QdrantClient,
    embedder: Embedder,
    *,
    cancelled: Callable[[], bool] | None = None,
    guard: Callable[[], None] | None = None,
    activate: bool = True,
) -> dict[str, Any]:
    """Freeze memory writes, build a consistent generation, then switch once.

    Existing aliases keep serving readers throughout. The gate is also used by
    CLI imports, deliveries and erasure, so a process-local maintenance flag is
    unnecessary. Sequence IDs are not commit watermarks and are never replayed.
    """
    with maintenance.exclusive(conn):
        return _rebuild_locked(
            conn, client, embedder, cancelled=cancelled, guard=guard, activate=activate
        )
