"""Write and read paths shared by the HTTP API and the CLI importer."""

from __future__ import annotations

import logging
import sqlite3
import uuid as uuidlib
from datetime import UTC, datetime
from typing import Any

from qdrant_client import QdrantClient

from . import vectors
from .db import ensure_owner, ensure_session, utcnow
from .embed import Embedder
from .importers.claude_code import MIN_INDEX_CHARS

logger = logging.getLogger(__name__)

# Re-exported: the importer decides indexability at classification time and the
# raw indexer and reindex must apply the identical floor, or reindex silently
# changes the size of the `raw` collection.
__all__ = ["MIN_INDEX_CHARS"]


def add_message(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    owner_id: str,
    agent_id: str,
    role: str,
    content: str,
    created_at: str | None = None,
    external_source: str | None = None,
    external_id: str | None = None,
) -> tuple[int, bool]:
    """Insert a message. Returns ``(message_id, deduplicated)``.

    Idempotent whenever the caller supplies an external id. Both writers that
    can replay -- the transcript importer and Hermes, which has three
    independent paths delivering the same turn -- depend on this.
    """
    ensure_owner(conn, owner_id, owner_id)
    ensure_session(conn, session_id, owner_id, agent_id, created_at)

    if external_id is not None:
        row = conn.execute(
            "SELECT id FROM messages WHERE external_source IS ? AND external_id = ?",
            (external_source, external_id),
        ).fetchone()
        if row is not None:
            return int(row["id"]), True

    cur = conn.execute(
        "INSERT INTO messages "
        "(session_id, role, content, created_at, external_source, external_id) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            session_id,
            role,
            content,
            created_at or utcnow(),
            external_source,
            external_id,
        ),
    )
    return int(cur.lastrowid), False


def raw_payload(row: sqlite3.Row, project: str | None = None) -> dict[str, Any]:
    return {
        "owner_id": row["owner_id"],
        "agent_id": row["agent_id"],
        "session_id": row["session_id"],
        "role": row["role"],
        "project": project,
        "text": row["content"],
        "created_at": row["created_at"],
        "message_id": row["id"],
    }


def index_raw(
    conn: sqlite3.Connection,
    client: QdrantClient,
    embedder: Embedder,
    message_ids: list[int],
    *,
    batch_size: int = 32,
) -> int:
    """Embed and upsert raw user turns into the ``raw`` collection.

    Only user turns above the length floor are indexed. Assistant text stays in
    SQLite because stage-2 extraction windows need it for pronoun resolution,
    but indexing the model's own words would pollute a search over the user's
    history.
    """
    if not message_ids:
        return 0
    placeholders = ",".join("?" * len(message_ids))
    rows = conn.execute(
        f"""SELECT m.id, m.session_id, m.role, m.content, m.created_at,
                   s.owner_id, s.agent_id, s.meta
              FROM messages m JOIN sessions s ON s.id = m.session_id
             WHERE m.id IN ({placeholders})""",
        message_ids,
    ).fetchall()

    eligible = [
        r for r in rows if r["role"] == "user" and len(r["content"]) >= MIN_INDEX_CHARS
    ]
    total = 0
    for i in range(0, len(eligible), batch_size):
        chunk = eligible[i : i + batch_size]
        vecs = embedder.encode([r["content"] for r in chunk])
        points: list[tuple[str | int, list[float], dict[str, Any]]] = []
        for row, vec in zip(chunk, vecs, strict=True):
            meta = row["meta"]
            project = None
            if meta:
                import json

                try:
                    project = (json.loads(meta) or {}).get("project")
                except (ValueError, TypeError):
                    project = None
            points.append((int(row["id"]), vec, raw_payload(row, project)))
        vectors.upsert(client, vectors.RAW, points)
        total += len(points)
    return total


def search_raw(
    client: QdrantClient,
    embedder: Embedder,
    *,
    query: str,
    owner_id: str,
    limit: int = 30,
    project: str | None = None,
) -> list[dict[str, Any]]:
    """Pure cosine search over raw turns. No reranking -- that is stage 3."""
    must = [vectors.keyword("owner_id", owner_id)]
    if project:
        must.append(vectors.keyword("project", project))
    vec = embedder.encode_one(query)
    hits = vectors.search(client, vectors.RAW, vec, limit=limit, must=must)
    return [
        {
            "message_id": h.payload.get("message_id"),
            "text": h.payload.get("text", ""),
            "similarity": round(float(h.score), 4),
            "project": h.payload.get("project"),
            "session_id": h.payload.get("session_id"),
            "created_at": h.payload.get("created_at"),
        }
        for h in hits
    ]


def search_memories(
    client: QdrantClient,
    embedder: Embedder,
    *,
    query: str,
    owner_id: str,
    limit: int = 30,
    scopes: list[str] | None = None,
    types: list[str] | None = None,
    scope_key: str | None = None,
) -> list[dict[str, Any]]:
    """Cosine search over extracted facts.

    Only `status='active'` points exist in the collection, but the filter is
    explicit so a stale point can never leak into a result.

    Stage 2 returns raw similarity. The score formula, per-type recency decay,
    scope_key filtering and dedup are stage 3 -- `score` is emitted now, equal to
    similarity, so the response shape does not change when they land.
    """
    must = [
        vectors.keyword("owner_id", owner_id),
        vectors.keyword("status", "active"),
    ]
    if scopes:
        must.append(vectors.keyword("scope", scopes))
    if types:
        must.append(vectors.keyword("type", types))
    if scope_key:
        must.append(vectors.keyword("scope_key", scope_key))

    vec = embedder.encode_one(query)
    hits = vectors.search(client, vectors.MEMORIES, vec, limit=limit, must=must)
    now = datetime.now(UTC)
    out = []
    for h in hits:
        updated = h.payload.get("updated_at") or ""
        out.append(
            {
                "id": str(h.id),
                "text": h.payload.get("text", ""),
                "type": h.payload.get("type"),
                "scope": h.payload.get("scope"),
                "scope_key": h.payload.get("scope_key"),
                "score": round(float(h.score), 4),
                "similarity": round(float(h.score), 4),
                "importance": h.payload.get("importance"),
                "age_days": _age_days(updated, now),
                "updated_at": updated,
            }
        )
    return out


def _age_days(iso: str, now: datetime) -> int | None:
    if not iso:
        return None
    try:
        when = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0, (now - when).days)


def record_retrieval(conn: sqlite3.Connection, memory_ids: list[str]) -> None:
    """Feedback loop from docs/05-retrieval.md.

    Two uses: the nightly pass can demote facts that have not surfaced in 90
    days, and a fact that is never retrieved at all is usually an extractor
    mistake worth reading by hand.

    Does not commit. It used to, unconditionally, which meant a search landing
    mid-write committed whatever that other unit of work had written so far.
    The caller owns the transaction boundary.
    """
    if not memory_ids:
        return
    now = utcnow()
    conn.executemany(
        """UPDATE memories
              SET last_retrieved_at = ?, retrieval_count = retrieval_count + 1
            WHERE id = ?""",
        [(now, mid) for mid in memory_ids],
    )


def add_memory(
    conn: sqlite3.Connection,
    client: QdrantClient,
    embedder: Embedder,
    *,
    owner_id: str,
    text: str,
    type: str,
    scope: str = "user",
    scope_key: str | None = None,
    agent_id: str | None = None,
    importance: float = 0.6,
    confidence: float = 0.9,
    extraction_version: str = "manual",
    judge_run_id: int | None = None,
    valid_until: str | None = None,
    task_status: str | None = None,
) -> str:
    """Insert a fact into SQLite and mirror it into Qdrant."""
    ensure_owner(conn, owner_id, owner_id)
    # A user-scoped fact has no key, the same normalisation mutate.update_memory
    # applies on the edit path. Both paths write the same column and only one
    # enforced it, so `POST /v1/memories` could create a `scope='user'` row
    # carrying a project key: harmless to retrieval, which ignores the key for
    # user scope, but it shows up under a project filter in the listing and the
    # facets, claiming the fact belongs to one repo when it belongs to all.
    if scope == "user":
        scope_key = None
    mem_id = str(uuidlib.uuid4())
    now = utcnow()
    conn.execute(
        """INSERT INTO memories
           (id, owner_id, agent_id, scope, scope_key, type, text, importance,
            confidence, status, valid_from, valid_until, created_at, updated_at,
            extraction_version, judge_run_id)
           VALUES (?,?,?,?,?,?,?,?,?,'active',?,?,?,?,?,?)""",
        (
            mem_id, owner_id, agent_id, scope, scope_key, type, text, importance,
            confidence, now, valid_until, now, now, extraction_version, judge_run_id,
        ),
    )
    workflow_status: str | None = None
    if type == "task":
        workflow_status = (
            task_status
            if task_status in {"unknown", "todo", "doing", "done"}
            else "unknown"
        )
        first = conn.execute(
            """SELECT MIN(tb.position) AS position
                 FROM task_board tb
                 JOIN memories m ON m.id = tb.memory_id
                WHERE m.owner_id = ? AND tb.workflow_status = ?""",
            (owner_id, workflow_status),
        ).fetchone()["position"]
        position = (float(first) if first is not None else 1024.0) - 1024.0
        conn.execute(
            """INSERT INTO task_board
               (memory_id, workflow_status, project_key, position, version,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, 1, ?, ?)""",
            (
                mem_id,
                workflow_status,
                (scope_key or "").strip() or None if scope != "user" else None,
                position,
                now,
                now,
            ),
        )
    vec = embedder.encode_one(text)
    vectors.upsert(client, vectors.MEMORIES, [(mem_id, vec, _mem_payload(
        mem_id, owner_id, agent_id, scope, scope_key, type, text, importance, now,
        task_status=workflow_status,
    ))])
    return mem_id


def _mem_payload(
    mem_id: str, owner_id: str, agent_id: str | None, scope: str,
    scope_key: str | None, type: str, text: str, importance: float, now: str,
    task_status: str | None = None,
) -> dict[str, Any]:
    # text is duplicated into the payload on purpose: without it every search
    # result would need a follow-up SQLite read.
    payload = {
        "owner_id": owner_id,
        "agent_id": agent_id,
        "scope": scope,
        "scope_key": scope_key,
        "type": type,
        "text": text,
        "importance": importance,
        "status": "active",
        "created_at": now,
        "updated_at": now,
    }
    if type == "task":
        payload["task_status"] = task_status or "unknown"
    return payload


def mem_payload(
    row: sqlite3.Row | dict[str, Any], *, task_status: str | None = None
) -> dict[str, Any]:
    """Canonical Qdrant payload for a committed memory row."""
    payload = {
        "owner_id": row["owner_id"],
        "agent_id": row["agent_id"],
        "scope": row["scope"],
        "scope_key": row["scope_key"],
        "type": row["type"],
        "text": row["text"],
        "importance": row["importance"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
    if row["type"] == "task":
        if task_status is None:
            keys = row.keys() if isinstance(row, sqlite3.Row) else row.keys()
            task_status = row["task_status"] if "task_status" in keys else None
        payload["task_status"] = task_status or "unknown"
    return payload


def reindex(
    conn: sqlite3.Connection,
    client: QdrantClient,
    embedder: Embedder,
    *,
    batch_size: int = 64,
    progress: Any | None = None,
) -> dict[str, int]:
    """Rebuild both Qdrant collections from SQLite.

    Loads only ``status='active'`` facts. A soft delete keeps the SQLite row, so
    reindexing everything would silently resurrect every fact ever deleted --
    the docs specify "reload from SQLite" without stating the filter.
    """
    vectors.drop_collection(client, vectors.MEMORIES)
    vectors.drop_collection(client, vectors.RAW)
    vectors.ensure_collections(client)

    mem_rows = conn.execute(
        """SELECT m.id, m.owner_id, m.agent_id, m.scope, m.scope_key, m.type,
                  m.text, m.importance, m.status, m.created_at, m.updated_at,
                  tb.workflow_status AS task_status
             FROM memories m
             LEFT JOIN task_board tb ON tb.memory_id = m.id
            WHERE m.status = 'active'"""
    ).fetchall()
    n_mem = 0
    for i in range(0, len(mem_rows), batch_size):
        chunk = mem_rows[i : i + batch_size]
        vecs = embedder.encode([r["text"] for r in chunk])
        points = [
            (
                r["id"],
                v,
                mem_payload(r),
            )
            for r, v in zip(chunk, vecs, strict=True)
        ]
        vectors.upsert(client, vectors.MEMORIES, points)
        n_mem += len(points)
        if progress:
            progress("memories", n_mem, len(mem_rows))

    raw_ids = [
        int(r["id"])
        for r in conn.execute(
            "SELECT id FROM messages WHERE role = 'user' AND length(content) >= ?",
            (MIN_INDEX_CHARS,),
        ).fetchall()
    ]
    n_raw = 0
    for i in range(0, len(raw_ids), 512):
        n_raw += index_raw(conn, client, embedder, raw_ids[i : i + 512])
        if progress:
            progress("raw", n_raw, len(raw_ids))

    return {"memories": n_mem, "raw": n_raw}
