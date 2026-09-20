"""Generation-based, validated Qdrant rebuild."""

from __future__ import annotations

import time
from collections.abc import Callable
from contextlib import nullcontext
from typing import Any

import psycopg
from qdrant_client import QdrantClient

from . import outbox, store, vectors
from .db import advisory_lock
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


def _replay(
    conn: psycopg.Connection,
    client: QdrantClient,
    embedder: Embedder,
    generations: dict[str, str],
    *,
    after_id: int,
) -> tuple[int, dict[str, set[str]]]:
    """Apply the outbox operations recorded since the snapshot.

    Each write takes the same per-scope barrier the index worker takes, so a
    concurrent delivery for a point cannot interleave with the replay of that
    same point once the aliases are live and both are writing to one collection.
    """
    rows = conn.execute(
        "SELECT * FROM index_outbox WHERE id>%s ORDER BY id", (after_id,)
    ).fetchall()
    changes: dict[str, set[str]] = {logical: set() for logical in generations}
    highwater = after_id
    for row in rows:
        highwater = max(highwater, int(row["id"]))
        logical = str(row["collection"])
        if logical not in generations:
            continue
        target = generations[logical]
        entity_id: str | int = (
            int(row["entity_id"]) if logical == vectors.RAW else str(row["entity_id"])
        )
        payload = dict(row["payload"] or {})
        scope_id = str(payload.get("scope_id") or "")
        barrier = outbox.scope_barrier(conn, scope_id) if scope_id else nullcontext()
        with barrier:
            if row["operation"] == "delete":
                vectors.delete_points(client, target, [entity_id])
            else:
                vector = embedder.encode_one(payload["text"])
                vectors.upsert(client, target, [(entity_id, vector, payload)])
        changes[logical].add(str(entity_id))
    return highwater, changes


def _snapshot(conn: psycopg.Connection) -> tuple[int, list[Any], list[Any]]:
    """The outbox highwater and every row to index, from one consistent read.

    REPEATABLE READ, so all three statements see the same instant: under READ
    COMMITTED a memory committed between the highwater query and the memories
    query would be both absent from the build and below the replay point, and
    the id-set validation at the end would fail on a row that is genuinely
    there.
    """
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


def rebuild(
    conn: psycopg.Connection,
    client: QdrantClient,
    embedder: Embedder,
    *,
    cancelled: Callable[[], bool] | None = None,
    activate: bool = True,
) -> dict[str, Any]:
    """Rebuild both collections from Postgres and activate validated aliases.

    A rebuild covers every scope at once, so the per-owner barriers this used to
    take -- one advisory lock per owner, held for the whole run -- collapse into
    one instance-wide `memkit:index` lock. That lock is taken around the alias
    swap rather than the build: a transaction spanning the embedding and Qdrant
    work would sit idle in transaction for minutes and be killed by
    `idle_in_transaction_session_timeout`. Two rebuilds may therefore build
    concurrently, and each generation is a complete snapshot, so the swap they
    serialise on is the only step where their order matters.
    """
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
        vectors.MEMORIES: {str(row["id"]) for row in indexable},
        vectors.RAW: {str(row["id"]) for row in raw_rows},
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

    for logical, generation in generations.items():
        actual = vectors.exact_ids(client, generation)
        if actual != expected[logical]:
            raise ReindexError(
                f"{logical} generation validation failed: "
                f"expected {len(expected[logical])} ids, got {len(actual)}"
            )

    highwater, _ = _replay(conn, client, embedder, generations, after_id=snapshot)
    if cancelled and cancelled():
        raise ReindexCancelled("reindex cancelled before activation")
    if not activate:
        return {
            "generation": generations,
            "snapshot_outbox_id": snapshot,
            "replayed_through": highwater,
            "memories": len(vectors.exact_ids(client, generations[vectors.MEMORIES])),
            "raw": len(vectors.exact_ids(client, generations[vectors.RAW])),
            "activated": False,
        }
    with conn.transaction():
        # One writer swaps aliases at a time, and the replay that closes the
        # final race runs under the same lock: operations completed against the
        # old alias between the last replay and the swap are applied to the
        # generation that is now live.
        advisory_lock(conn, "memkit:index")
        vectors.swap_aliases(client, generations)
        highwater, _ = _replay(conn, client, embedder, generations, after_id=highwater)
    return {
        "generation": generations,
        "snapshot_outbox_id": snapshot,
        "replayed_through": highwater,
        "memories": len(vectors.exact_ids(client, generations[vectors.MEMORIES])),
        "raw": len(vectors.exact_ids(client, generations[vectors.RAW])),
        "activated": True,
    }
