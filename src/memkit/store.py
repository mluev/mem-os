"""Authoritative evidence/memory writes and derived-index plans."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import UTC, datetime
from typing import Any

from qdrant_client import QdrantClient

from . import outbox, provenance, security, vectors
from .db import ensure_owner, utcnow
from .embed import Embedder
from .limits import MAX_MEMORY_CHARS, MAX_MESSAGE_CHARS, MIN_INDEX_CHARS

__all__ = ["MIN_INDEX_CHARS"]


def _object(value: dict[str, Any] | None) -> str:
    return json.dumps(value or {}, ensure_ascii=False, sort_keys=True)


def _array(value: list[str] | None) -> str:
    return json.dumps(value or [], ensure_ascii=False)


def _session(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    owner_id: str,
    agent_id: str,
    started_at: str,
    context: dict[str, Any],
) -> None:
    row = conn.execute(
        "SELECT owner_id,agent_id FROM sessions WHERE id=?", (session_id,)
    ).fetchone()
    if row:
        if row["owner_id"] != owner_id or row["agent_id"] != agent_id:
            raise ValueError("session identity does not match its stored owner and agent")
        return
    conn.execute(
        """INSERT INTO sessions
           (id,owner_id,agent_id,started_at,context_json) VALUES (?,?,?,?,?)""",
        (session_id, owner_id, agent_id, started_at, _object(context)),
    )


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
    context: dict[str, Any] | None = None,
) -> tuple[int, bool, bool]:
    """Persist redacted evidence and enqueue raw indexing in one transaction."""
    content = content.strip()
    if not content:
        raise ValueError("message content is blank")
    if len(content) > MAX_MESSAGE_CHARS:
        raise ValueError(f"message content exceeds {MAX_MESSAGE_CHARS} characters")
    if role not in {"user", "assistant", "tool"}:
        raise ValueError("invalid message role")
    cleaned = security.redact(content)
    context, context_redactions = security.redact_value(context or {})
    now = created_at or utcnow()
    ensure_owner(conn, owner_id, owner_id)
    _session(
        conn,
        session_id=session_id,
        owner_id=owner_id,
        agent_id=agent_id,
        started_at=now,
        context=context,
    )

    if external_id is not None:
        row = conn.execute(
            """SELECT m.*,s.owner_id,s.agent_id FROM messages m
                 JOIN sessions s ON s.id=m.session_id
                WHERE external_source IS ? AND external_id=?""",
            (external_source, external_id),
        ).fetchone()
        if row is not None:
            if row["owner_id"] != owner_id:
                raise ValueError("idempotency key belongs to another owner")
            if row["role"] == "user" and len(row["content"]) >= MIN_INDEX_CHARS:
                outbox.ensure_pending(
                    conn,
                    collection=vectors.RAW,
                    entity_id=int(row["id"]),
                    operation="upsert",
                    payload=raw_payload(row),
                )
            return int(row["id"]), True, bool(row["redacted"])

    cur = conn.execute(
        """INSERT INTO messages
           (session_id,role,content,created_at,external_source,external_id,
            context_json,redacted)
           VALUES (?,?,?,?,?,?,?,?)""",
        (
            session_id,
            role,
            cleaned.text,
            now,
            external_source,
            external_id,
            _object(context),
            int(cleaned.redacted or context_redactions > 0),
        ),
    )
    message_id = int(cur.lastrowid)
    if role == "user" and len(cleaned.text) >= MIN_INDEX_CHARS:
        row = conn.execute(
            """SELECT m.*,s.owner_id,s.agent_id FROM messages m
                 JOIN sessions s ON s.id=m.session_id WHERE m.id=?""",
            (message_id,),
        ).fetchone()
        outbox.enqueue(
            conn,
            collection=vectors.RAW,
            entity_id=message_id,
            operation="upsert",
            payload=raw_payload(row),
        )
    return message_id, False, cleaned.redacted


def raw_payload(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    context = dict(row).get("context_json", "{}")
    return {
        "owner_id": row["owner_id"],
        "agent_id": row["agent_id"],
        "session_id": row["session_id"],
        "role": row["role"],
        "text": row["content"],
        "context": json.loads(context or "{}"),
        "created_at": row["created_at"],
        "message_id": int(row["id"]),
        "redacted": bool(row["redacted"]) if "redacted" in row else False,
    }


def ensure_raw_outbox(conn: sqlite3.Connection, message_ids: list[int]) -> int:
    if not message_ids:
        return 0
    placeholders = ",".join("?" for _ in message_ids)
    rows = conn.execute(
        f"""SELECT m.*,s.owner_id,s.agent_id FROM messages m
              JOIN sessions s ON s.id=m.session_id
             WHERE m.id IN ({placeholders}) AND m.role='user'
               AND length(m.content)>=?""",
        (*message_ids, MIN_INDEX_CHARS),
    ).fetchall()
    for row in rows:
        outbox.ensure_pending(
            conn,
            collection=vectors.RAW,
            entity_id=int(row["id"]),
            operation="upsert",
            payload=raw_payload(row),
        )
    return len(rows)


def search_raw(
    client: QdrantClient,
    embedder: Embedder,
    *,
    query: str,
    owner_id: str,
    limit: int = 30,
    vector: list[float] | None = None,
) -> list[dict[str, Any]]:
    # The memory search on the same request already embedded this query; pass
    # its vector rather than paying for the identical encode twice.
    vector = vector if vector is not None else embedder.encode_one(query)
    hits = vectors.search(
        client,
        vectors.RAW,
        vector,
        limit=limit,
        must=[vectors.keyword("owner_id", owner_id)],
    )
    return [
        {
            "message_id": hit.payload.get("message_id"),
            "text": hit.payload.get("text", ""),
            "similarity": round(float(hit.score), 4),
            "context": hit.payload.get("context") or {},
            "session_id": hit.payload.get("session_id"),
            "created_at": hit.payload.get("created_at"),
        }
        for hit in hits
    ]


def evidence_excerpts(
    conn: sqlite3.Connection,
    memory_ids: list[str],
    *,
    per_memory: int = 3,
) -> dict[str, list[dict[str, Any]]]:
    """Verbatim source spans for search results — search facts, return evidence.

    An atomic memory embeds precisely but is lossy; the cited span carries the
    detail. Every span is re-sliced from the retained message and verified
    against `excerpt_sha256` before leaving the store — the hash was written
    for exactly this moment, and a mismatch (edited row, drifted offset) drops
    the span rather than returning corrupted evidence as if it were verbatim.
    """
    if not memory_ids:
        return {}
    placeholders = ",".join("?" for _ in memory_ids)
    rows = conn.execute(
        f"""SELECT e.memory_id,e.message_id,e.start_char,e.end_char,e.excerpt_sha256,
                   m.content,m.role,m.created_at
              FROM memory_evidence e JOIN messages m ON m.id=e.message_id
             WHERE e.memory_id IN ({placeholders})
             ORDER BY e.memory_id,e.message_id,e.start_char""",
        memory_ids,
    ).fetchall()
    excerpts: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        bucket = excerpts.setdefault(row["memory_id"], [])
        if len(bucket) >= per_memory:
            continue
        excerpt = str(row["content"])[row["start_char"] : row["end_char"]]
        if hashlib.sha256(excerpt.encode()).hexdigest() != row["excerpt_sha256"]:
            continue
        bucket.append(
            {
                "message_id": int(row["message_id"]),
                "excerpt": excerpt,
                "role": row["role"],
                "created_at": row["created_at"],
            }
        )
    return excerpts


def record_retrieval(conn: sqlite3.Connection, memory_ids: list[str]) -> None:
    if not memory_ids:
        return
    now = utcnow()
    conn.executemany(
        """UPDATE memories SET last_retrieved_at=?,retrieval_count=retrieval_count+1
            WHERE id=?""",
        [(now, memory_id) for memory_id in memory_ids],
    )


def record_feedback(
    conn: sqlite3.Connection,
    *,
    memory_id: str,
    query_hash: str,
    useful: bool | None,
    correct: bool | None,
) -> None:
    conn.execute(
        """INSERT INTO retrieval_feedback
           (memory_id,query_hash,useful,correct,created_at) VALUES (?,?,?,?,?)""",
        (
            memory_id,
            query_hash,
            None if useful is None else int(useful),
            None if correct is None else int(correct),
            utcnow(),
        ),
    )


def add_memory(
    conn: sqlite3.Connection,
    *,
    owner_id: str,
    text: str,
    kind: str,
    context: dict[str, Any] | None = None,
    tags: list[str] | None = None,
    agent_id: str | None = None,
    importance: float = 0.6,
    confidence: float = 0.9,
    extraction_version: str = "manual",
    judge_run_id: int | None = None,
    valid_until: str | None = None,
    source_role: str = provenance.DEFAULT_ROLE,
    memory_id: str | None = None,
) -> str:
    """Insert one authoritative memory and enqueue its index operation."""
    text = text.strip()
    kind = kind.strip()
    if not text:
        raise ValueError("memory text is blank")
    if len(text) > MAX_MEMORY_CHARS:
        raise ValueError(f"memory text exceeds {MAX_MEMORY_CHARS} characters")
    if not kind or len(kind) > 64:
        raise ValueError("memory kind must contain 1–64 characters")
    provenance.validate(source_role)
    cleaned = security.redact(text)
    context, context_redactions = security.redact_value(context or {})
    tags, tag_redactions = security.redact_value(tags or [])
    ensure_owner(conn, owner_id, owner_id)
    memory_id = memory_id or str(uuid.uuid4())
    now = utcnow()
    conn.execute(
        """INSERT INTO memories
           (id,owner_id,agent_id,kind,text,importance,confidence,status,valid_from,
            valid_until,created_at,updated_at,extraction_version,judge_run_id,
            source_role,context_json,tags_json,redacted)
           VALUES (?,?,?,?,?,?,?,'active',?,?,?,?,?,?,?,?,?,?)""",
        (
            memory_id,
            owner_id,
            agent_id,
            kind,
            cleaned.text,
            importance,
            confidence,
            now,
            valid_until,
            now,
            now,
            extraction_version,
            judge_run_id,
            source_role,
            _object(context),
            _array(tags),
            int(cleaned.redacted or context_redactions > 0 or tag_redactions > 0),
        ),
    )
    row = conn.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
    append_memory_revision(conn, row)
    outbox.enqueue(
        conn,
        collection=vectors.MEMORIES,
        entity_id=memory_id,
        operation="upsert",
        payload=mem_payload(row),
    )
    return memory_id


def append_memory_revision(conn: sqlite3.Connection, row: sqlite3.Row) -> None:
    conn.execute(
        """INSERT INTO memory_revisions
           (memory_id,revision,kind,text,importance,confidence,status,superseded_by,
            valid_until,extraction_version,judge_run_id,source_role,context_json,
            tags_json,redacted,created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            row["id"],
            row["revision"],
            row["kind"],
            row["text"],
            row["importance"],
            row["confidence"],
            row["status"],
            row["superseded_by"],
            row["valid_until"],
            row["extraction_version"],
            row["judge_run_id"],
            row["source_role"],
            row["context_json"],
            row["tags_json"],
            row["redacted"],
            row["updated_at"],
        ),
    )


def update_memory(
    conn: sqlite3.Connection,
    *,
    memory_id: str,
    owner_id: str,
    expected_revision: int,
    text: str,
    kind: str,
    context: dict[str, Any],
    tags: list[str],
    importance: float,
    confidence: float,
    valid_until: str | None,
    extraction_version: str | None = None,
    judge_run_id: int | None = None,
    source_role: str | None = None,
) -> sqlite3.Row:
    """Atomically replace mutable memory fields and append one immutable revision."""
    text = text.strip()
    kind = kind.strip()
    if not text or len(text) > MAX_MEMORY_CHARS:
        raise ValueError("memory text must contain 1–2000 characters")
    if not kind or len(kind) > 64:
        raise ValueError("memory kind must contain 1–64 characters")
    cleaned = security.redact(text)
    context, context_redactions = security.redact_value(context)
    tags, tag_redactions = security.redact_value(tags)
    now = utcnow()
    current = conn.execute(
        "SELECT * FROM memories WHERE id=? AND owner_id=?",
        (memory_id, owner_id),
    ).fetchone()
    if current is None:
        raise KeyError(memory_id)
    next_source_role = source_role or current["source_role"]
    provenance.validate(next_source_role)
    changed = conn.execute(
        """UPDATE memories
              SET text=?,kind=?,importance=?,confidence=?,context_json=?,tags_json=?,
                  valid_until=?,updated_at=?,revision=revision+1,extraction_version=?,
                  judge_run_id=?,source_role=?,redacted=?
            WHERE id=? AND owner_id=? AND revision=?""",
        (
            cleaned.text,
            kind,
            importance,
            confidence,
            _object(context),
            _array(tags),
            valid_until,
            now,
            extraction_version or current["extraction_version"],
            judge_run_id if judge_run_id is not None else current["judge_run_id"],
            next_source_role,
            int(
                cleaned.redacted
                or context_redactions > 0
                or tag_redactions > 0
                or (bool(current["redacted"]) and cleaned.text == current["text"])
            ),
            memory_id,
            owner_id,
            expected_revision,
        ),
    ).rowcount
    if not changed:
        raise RuntimeError("memory revision conflict")
    saved = conn.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
    append_memory_revision(conn, saved)
    outbox.enqueue(
        conn,
        collection=vectors.MEMORIES,
        entity_id=memory_id,
        operation="upsert",
        payload=mem_payload(saved),
    )
    return saved


def set_memory_status(
    conn: sqlite3.Connection,
    *,
    memory_id: str,
    owner_id: str,
    status: str,
    expected_revision: int | None = None,
    superseded_by: str | None = None,
) -> sqlite3.Row:
    current = conn.execute(
        "SELECT * FROM memories WHERE id=? AND owner_id=?", (memory_id, owner_id)
    ).fetchone()
    if current is None:
        raise KeyError(memory_id)
    revision = int(current["revision"])
    if expected_revision is not None and revision != expected_revision:
        raise RuntimeError("memory revision conflict")
    changed = conn.execute(
        """UPDATE memories SET status=?,superseded_by=?,updated_at=?,revision=revision+1
             WHERE id=? AND owner_id=? AND revision=?""",
        (status, superseded_by, utcnow(), memory_id, owner_id, revision),
    ).rowcount
    if not changed:
        raise RuntimeError("memory revision conflict")
    saved = conn.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
    append_memory_revision(conn, saved)
    outbox.enqueue(
        conn,
        collection=vectors.MEMORIES,
        entity_id=memory_id,
        operation="delete" if status != "active" else "upsert",
        payload={"owner_id": owner_id} if status != "active" else mem_payload(saved),
    )
    return saved


def mem_payload(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    keys = row.keys()
    return {
        "owner_id": row["owner_id"],
        "agent_id": row["agent_id"],
        "kind": row["kind"],
        "text": row["text"],
        "importance": float(row["importance"]),
        "confidence": float(row["confidence"]),
        "status": row["status"],
        "source_role": row["source_role"],
        "context": json.loads(row["context_json"] or "{}"),
        "tags": json.loads(row["tags_json"] or "[]"),
        "valid_until": row["valid_until"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "revision": int(row["revision"]) if "revision" in keys else 1,
        "redacted": bool(row["redacted"]) if "redacted" in keys else False,
    }


def memory_active(row: sqlite3.Row | dict[str, Any], *, now: datetime | None = None) -> bool:
    if row["status"] != "active":
        return False
    valid_until = row["valid_until"]
    if not valid_until:
        return True
    now = now or datetime.now(UTC)
    try:
        expiry = datetime.fromisoformat(str(valid_until).replace("Z", "+00:00"))
    except ValueError:
        return False
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=UTC)
    return expiry > now
