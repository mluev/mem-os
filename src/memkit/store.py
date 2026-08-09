"""Authoritative evidence/memory writes and derived-index plans."""

from __future__ import annotations

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
) -> list[dict[str, Any]]:
    vector = embedder.encode_one(query)
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
    memory_id = str(uuid.uuid4())
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
    outbox.enqueue(
        conn,
        collection=vectors.MEMORIES,
        entity_id=memory_id,
        operation="upsert",
        payload=mem_payload(row),
    )
    return memory_id


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
