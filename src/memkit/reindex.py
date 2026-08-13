"""Generation-based, validated Qdrant rebuild."""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Callable
from contextlib import ExitStack
from typing import Any

from qdrant_client import QdrantClient

from . import outbox, store, vectors
from .embed import Embedder


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
    conn: sqlite3.Connection,
    client: QdrantClient,
    embedder: Embedder,
    generations: dict[str, str],
    *,
    after_id: int,
) -> tuple[int, dict[str, set[str]]]:
    rows = conn.execute("SELECT * FROM index_outbox WHERE id>? ORDER BY id", (after_id,)).fetchall()
    changes = {logical: set() for logical in generations}
    highwater = after_id
    for row in rows:
        highwater = max(highwater, int(row["id"]))
        logical = row["collection"]
        if logical not in generations:
            continue
        target = generations[logical]
        entity_id: str | int = int(row["entity_id"]) if logical == vectors.RAW else row["entity_id"]
        if row["operation"] == "delete":
            vectors.delete_points(client, target, [entity_id])
        else:
            payload = json.loads(row["payload_json"])
            vector = embedder.encode_one(payload["text"])
            vectors.upsert(client, target, [(entity_id, vector, payload)])
        changes[logical].add(str(entity_id))
    return highwater, changes


def rebuild(
    conn: sqlite3.Connection,
    client: QdrantClient,
    embedder: Embedder,
    *,
    cancelled: Callable[[], bool] | None = None,
    activate: bool = True,
) -> dict[str, Any]:
    """Serialize a full generation swap against owner erasure."""
    owners = [str(row[0]) for row in conn.execute("SELECT id FROM owners ORDER BY id")]
    with ExitStack() as stack:
        for owner_id in owners:
            stack.enter_context(outbox.owner_barrier(conn, owner_id))
        return _rebuild(conn, client, embedder, cancelled=cancelled, activate=activate)


def _rebuild(
    conn: sqlite3.Connection,
    client: QdrantClient,
    embedder: Embedder,
    *,
    cancelled: Callable[[], bool] | None = None,
    activate: bool = True,
) -> dict[str, Any]:
    """Build from one SQLite snapshot and atomically activate validated aliases."""
    # Reindex owns its snapshot boundary; never inherit an incidental caller
    # transaction that could hold locks across embedding or Qdrant calls.
    conn.commit()
    conn.execute("BEGIN")
    try:
        snapshot = int(conn.execute("SELECT COALESCE(MAX(id),0) FROM index_outbox").fetchone()[0])
        memory_rows = conn.execute("SELECT * FROM memories WHERE status='active'").fetchall()
        raw_rows = conn.execute(
            """SELECT m.*,s.owner_id,s.agent_id FROM messages m
                 JOIN sessions s ON s.id=m.session_id
                WHERE m.role='user' AND length(m.content)>=?""",
            (store.MIN_INDEX_CHARS,),
        ).fetchall()
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    generations = {
        vectors.MEMORIES: _generation(vectors.MEMORIES),
        vectors.RAW: _generation(vectors.RAW),
    }
    if cancelled and cancelled():
        raise ReindexCancelled("reindex cancelled before generation build")
    for generation in generations.values():
        vectors.create_empty_collection(client, generation)

    expected = {
        vectors.MEMORIES: {row["id"] for row in memory_rows if store.memory_active(row)},
        vectors.RAW: {str(row["id"]) for row in raw_rows},
    }
    _write_rows(
        client,
        embedder,
        generations[vectors.MEMORIES],
        [(row["id"], store.mem_payload(row)) for row in memory_rows if store.memory_active(row)],
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
    vectors.swap_aliases(client, generations)
    # Close the final race: operations completed against the old alias between
    # the last replay and the atomic swap are now applied to the active generation.
    highwater, _ = _replay(conn, client, embedder, generations, after_id=highwater)
    return {
        "generation": generations,
        "snapshot_outbox_id": snapshot,
        "replayed_through": highwater,
        "memories": len(vectors.exact_ids(client, generations[vectors.MEMORIES])),
        "raw": len(vectors.exact_ids(client, generations[vectors.RAW])),
        "activated": True,
    }
