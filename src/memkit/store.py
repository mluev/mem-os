"""Authoritative writes: evidence, memories, revisions, and index handoff.

Every write here is scope-addressed. A memory belongs to exactly one scope --
the entity whose space holds it -- and authorization is a predicate on that
column, never on configuration. Functions that mutate an existing row take the
set of scopes the caller may write to, so a handler cannot lose the check by
forgetting to pass an owner: with no scopes, nothing is writable.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import psycopg
from psycopg.types.json import Jsonb
from qdrant_client import QdrantClient

from . import eligibility, entities, filters, maintenance, outbox, provenance, security, vectors
from .db import Row, advisory_lock, as_datetime, iso, utcnow
from .embed import Embedder
from .limits import MAX_MEMORY_CHARS, MAX_MESSAGE_CHARS, MIN_INDEX_CHARS
from .principal import ScopeForbidden

REVIEW_STATUSES = frozenset({"pending", "confirmed", "declined"})


class _Unchanged:
    pass


_UNCHANGED = _Unchanged()


def memory_identity(row: Row | dict[str, Any]) -> tuple:
    """Fields that must agree before two claims can share an identity."""
    return (
        str(row["scope_id"]),
        str(row["subject_id"]) if row.get("subject_id") else None,
        str(row["kind"]),
        json.dumps(row.get("context") or {}, sort_keys=True),
        iso(row.get("valid_until")),
        str(row["source_role"]),
    )


class SessionNotAvailable(LookupError):
    """This session is not the caller's to write into.

    Deliberately not distinguished from "no such session" at the boundary: a
    different answer for a session that exists would let anyone enumerate other
    people's conversation ids.
    """


def require_scope_write(conn: psycopg.Connection, *, user_id: str, scope_id: str) -> None:
    """Reauthorize delayed/session writes and hold permission through commit.

    Call inside the write transaction. Shared row locks make concurrent disable,
    archive, membership removal or downgrade wait until this write completes.
    """
    scope = conn.execute(
        """SELECT e.user_id FROM entities e JOIN users u ON u.id=%s
             WHERE e.id=%s AND e.archived_at IS NULL AND u.disabled_at IS NULL
             FOR SHARE OF e,u""",
        (user_id, scope_id),
    ).fetchone()
    if scope is None:
        raise ScopeForbidden(scope_id)
    if str(scope["user_id"]) == user_id:
        return
    membership = conn.execute(
        """SELECT role FROM memberships WHERE entity_id=%s AND user_id=%s FOR SHARE""",
        (scope_id, user_id),
    ).fetchone()
    if membership is None or membership["role"] not in entities.WRITER_ROLES:
        raise ScopeForbidden(scope_id)


def content_hash(text: str) -> str:
    """Identity of a claim's wording, for exact-duplicate rejection.

    Case-folded with runs of whitespace collapsed, so the same sentence written
    twice with different spacing is one claim. Anything looser belongs to
    semantic dedup, which is a measured threshold rather than an equality.
    """
    return hashlib.sha256(re.sub(r"\s+", " ", text).strip().casefold().encode()).hexdigest()


def _returned(row: Row | None, what: str) -> Row:
    """Narrow a RETURNING result, which cannot be empty after a successful write.

    A helper rather than an assertion so the failure survives `python -O` and
    reads as what it is: the database not returning a row it was asked for.
    """
    if row is None:  # pragma: no cover - would mean the server broke its contract
        raise RuntimeError(f"{what} returned no row")
    return row


def _session(
    conn: psycopg.Connection,
    *,
    session_id: str,
    user_id: str,
    scope_id: str,
    agent_id: str,
    started_at: datetime,
    context: dict[str, Any] | None,
    strict_scope: bool = False,
) -> Row:
    """Create the session on first sight; never move it afterwards.

    User, scope and agent are fixed when a session begins. A later event
    claiming a different one is a bug or an attack, and silently re-pointing
    the session would move every fact extracted from it.
    """
    row = conn.execute(
        """INSERT INTO sessions (id,user_id,scope_id,agent_id,started_at,context)
           VALUES (%s,%s,%s,%s,%s,%s)
           ON CONFLICT (id) DO NOTHING
           RETURNING *""",
        (session_id, user_id, scope_id, agent_id, started_at, Jsonb(context or {})),
    ).fetchone()
    if row is not None:
        require_scope_write(conn, user_id=user_id, scope_id=str(row["scope_id"]))
        return row
    existing = conn.execute("SELECT * FROM sessions WHERE id=%s", (session_id,)).fetchone()
    if existing is None:  # pragma: no cover - only under concurrent deletion
        raise RuntimeError(f"session vanished during creation: {session_id}")
    if str(existing["user_id"]) != str(user_id):
        raise SessionNotAvailable(session_id)
    if existing["agent_id"] != agent_id:
        raise ValueError("session belongs to another agent")
    require_scope_write(conn, user_id=user_id, scope_id=str(existing["scope_id"]))
    if strict_scope and str(existing["scope_id"]) != scope_id:
        raise ValueError("session belongs to another scope")
    return existing


@maintenance.write_transaction
def add_message(
    conn: psycopg.Connection,
    *,
    session_id: str,
    user_id: str,
    scope_id: str,
    agent_id: str,
    role: str,
    content: str,
    created_at: datetime | str | None = None,
    external_source: str | None = None,
    external_id: str | None = None,
    context: dict[str, Any] | None = None,
    strict_scope: bool = False,
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
    now = as_datetime(created_at) or utcnow()
    session = _session(
        conn,
        session_id=session_id,
        user_id=user_id,
        scope_id=scope_id,
        agent_id=agent_id,
        started_at=now,
        context=context,
        strict_scope=strict_scope,
    )

    if external_id is not None:
        # Idempotency is per user: two people on one machine would otherwise
        # collide on the same transcript line ids.
        row = conn.execute(
            """SELECT m.*,s.scope_id,s.agent_id FROM messages m
                 JOIN sessions s ON s.id=m.session_id
                WHERE m.user_id=%s AND m.external_source IS NOT DISTINCT FROM %s
                  AND m.external_id=%s""",
            (user_id, external_source, external_id),
        ).fetchone()
        if row is not None:
            if row["role"] == "user" and len(str(row["content"])) >= MIN_INDEX_CHARS:
                outbox.ensure_pending(
                    conn,
                    collection=vectors.RAW,
                    entity_id=int(row["id"]),
                    operation="upsert",
                    payload=raw_payload(row),
                )
            return int(row["id"]), True, bool(row["redacted"])

    row = conn.execute(
        """INSERT INTO messages
           (session_id,user_id,role,content,created_at,external_source,external_id,
            context,redacted)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
           RETURNING *""",
        (
            session_id,
            user_id,
            role,
            cleaned.text,
            now,
            external_source,
            external_id,
            Jsonb(context),
            bool(cleaned.redacted or context_redactions > 0),
        ),
    ).fetchone()
    row = _returned(row, "message insert")
    message_id = int(row["id"])
    if role == "user" and len(cleaned.text) >= MIN_INDEX_CHARS:
        outbox.enqueue(
            conn,
            collection=vectors.RAW,
            entity_id=message_id,
            operation="upsert",
            payload=raw_payload(
                {**dict(row), "scope_id": session["scope_id"], "agent_id": agent_id}
            ),
        )
    return message_id, False, cleaned.redacted


def raw_payload(row: Row | dict[str, Any]) -> dict[str, Any]:
    data = dict(row)
    return {
        "user_id": str(data["user_id"]),
        "scope_id": str(data["scope_id"]) if data.get("scope_id") else None,
        "agent_id": data.get("agent_id"),
        "session_id": data["session_id"],
        "role": data["role"],
        "text": data["content"],
        "context": data.get("context") or {},
        "created_at": iso(data["created_at"]),
        "message_id": int(data["id"]),
        "redacted": bool(data.get("redacted", False)),
    }


@maintenance.write_transaction
def ensure_raw_outbox(conn: psycopg.Connection, message_ids: list[int]) -> int:
    if not message_ids:
        return 0
    rows = conn.execute(
        """SELECT m.*,s.scope_id,s.agent_id FROM messages m
             JOIN sessions s ON s.id=m.session_id
            WHERE m.id = ANY(%s) AND m.role='user' AND length(m.content) >= %s""",
        (list(message_ids), MIN_INDEX_CHARS),
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


def raw_search_rows(
    conn: psycopg.Connection,
    client: QdrantClient,
    *,
    vector: list[float],
    scope_ids: Sequence[str],
    limit: int,
    expression: dict[str, Any] | None = None,
    kinds: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Resolve raw index proposals to currently authorized evidence rows."""
    filters.validate(expression)
    if not scope_ids or (kinds and "evidence" not in kinds):
        return []
    predicate, parameters = eligibility.filter_sql(expression)
    scores: dict[int, float] = {}
    selected: dict[int, dict[str, Any]] = {}
    candidate_limit = max(50, limit * 3)
    for _ in range(4):
        hits = vectors.search(
            client,
            vectors.RAW,
            vector,
            limit=candidate_limit,
            must=[
                vectors.keyword("scope_id", list(scope_ids)),
                vectors.keyword("role", "user"),
                *eligibility.vector_filters(expression, raw=True),
            ],
            exclude_ids=list(scores) or None,
        )
        fresh = {}
        for hit in hits:
            try:
                message_id = int(hit.id)
            except (TypeError, ValueError):
                continue
            if message_id not in scores:
                fresh[message_id] = float(hit.score)
        if not fresh:
            break
        scores.update(fresh)
        rows = conn.execute(
            f"""SELECT * FROM (
                SELECT evidence.*,session.scope_id,session.agent_id,
                       scope.name AS scope_name,scope.slug AS scope_slug,
                       'evidence'::text AS kind,'[]'::jsonb AS tags,NULL::uuid AS subject_id
                  FROM messages evidence JOIN sessions session ON session.id=evidence.session_id
                  JOIN entities scope ON scope.id=session.scope_id
                 WHERE evidence.id=ANY(%s) AND session.scope_id=ANY(%s)
                   AND evidence.role='user'
            ) m WHERE {predicate}""",
            (list(fresh), [uuid.UUID(str(scope)) for scope in scope_ids], *parameters),
        ).fetchall()
        selected.update(
            (int(row["id"]), {**row, "similarity": scores[int(row["id"])]}) for row in rows
        )
        if len(hits) < candidate_limit or len(selected) >= limit:
            break
    return sorted(selected.values(), key=lambda row: (-row["similarity"], int(row["id"])))[:limit]


def search_raw(
    conn: psycopg.Connection,
    client: QdrantClient,
    embedder: Embedder,
    *,
    query: str,
    scope_ids: Sequence[str],
    limit: int = 30,
    vector: list[float] | None = None,
    expression: dict[str, Any] | None = None,
    kinds: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Semantic search over retained user turns, within the caller's scopes."""
    if not scope_ids or (kinds and "evidence" not in kinds):
        return []
    vector = vector if vector is not None else embedder.encode_one(query)
    return [
        {
            "message_id": int(row["id"]),
            "text": row["content"],
            "similarity": round(row["similarity"], 4),
            "context": dict(row["context"] or {}),
            "session_id": row["session_id"],
            "created_at": iso(row["created_at"]),
            "source_role": "user",
            "scope": row["scope_name"],
        }
        for row in raw_search_rows(
            conn,
            client,
            vector=vector,
            scope_ids=scope_ids,
            limit=limit,
            expression=expression,
            kinds=kinds,
        )
    ]


def evidence_rows(
    conn: psycopg.Connection,
    memory_ids: list[str],
    *,
    scope_ids: Sequence[str] | None = None,
) -> list[Row]:
    """Load citation lineage once for current context and historical inspection.

    Legacy spans remain unversioned. They can accompany unchanged legacy claims,
    but are never assigned to new wording after a correction.
    """
    return conn.execute(
        """SELECT e.memory_id,e.message_id,e.start_char,e.end_char,e.excerpt_sha256,
                  m.content,m.role,m.created_at, linked.revision,
                  ARRAY(SELECT lineage.revision FROM memory_revision_evidence lineage
                         WHERE lineage.memory_id=e.memory_id AND lineage.message_id=e.message_id
                           AND lineage.start_char=e.start_char AND lineage.end_char=e.end_char
                         ORDER BY lineage.revision) AS supported_revisions,
                  (linked.revision IS NOT NULL OR (
                      NOT EXISTS (SELECT 1 FROM memory_revision_evidence lineage
                                   WHERE lineage.memory_id=e.memory_id)
                      AND NOT EXISTS (SELECT 1 FROM memory_revisions old
                                       WHERE old.memory_id=e.memory_id AND old.text<>current.text)
                  )) AS current_evidence
             FROM memory_evidence e JOIN messages m ON m.id=e.message_id
             JOIN sessions s ON s.id=m.session_id
             JOIN memories current ON current.id=e.memory_id
             LEFT JOIN memory_revision_evidence linked
               ON linked.memory_id=e.memory_id AND linked.revision=current.revision
              AND linked.message_id=e.message_id AND linked.start_char=e.start_char
              AND linked.end_char=e.end_char
            WHERE e.memory_id = ANY(%s)
              AND (%s::uuid[] IS NULL OR s.scope_id=ANY(%s::uuid[]))
            ORDER BY e.memory_id,e.message_id DESC,e.start_char""",
        (
            [uuid.UUID(str(mid)) for mid in memory_ids],
            [uuid.UUID(str(s)) for s in scope_ids] if scope_ids is not None else None,
            [uuid.UUID(str(s)) for s in scope_ids] if scope_ids is not None else None,
        ),
    ).fetchall()


def evidence_excerpts(
    conn: psycopg.Connection,
    memory_ids: list[str],
    *,
    per_memory: int = 3,
    scope_ids: Sequence[str] | None = None,
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
    rows = evidence_rows(conn, memory_ids, scope_ids=scope_ids)
    excerpts: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if not row["current_evidence"]:
            continue
        bucket = excerpts.setdefault(str(row["memory_id"]), [])
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
                "created_at": iso(row["created_at"]),
                "revision": row["revision"],
                "evidence_status": "current" if row["revision"] else "legacy_unversioned",
            }
        )
    return excerpts


def record_retrieval(conn: psycopg.Connection, memory_ids: list[str]) -> None:
    if not memory_ids:
        return
    conn.execute(
        """UPDATE memories SET last_retrieved_at=now(),retrieval_count=retrieval_count+1
            WHERE id = ANY(%s)""",
        ([uuid.UUID(str(mid)) for mid in memory_ids],),
    )


def record_feedback(
    conn: psycopg.Connection,
    *,
    memory_id: str,
    query_hash: str,
    useful: bool | None,
    correct: bool | None,
) -> None:
    conn.execute(
        """INSERT INTO retrieval_feedback (memory_id,query_hash,useful,correct)
           VALUES (%s,%s,%s,%s)""",
        (memory_id, query_hash, useful, correct),
    )


@maintenance.write_transaction
def find_duplicate(
    conn: psycopg.Connection,
    *,
    scope_id: str,
    text: str,
    kind: str,
    context: dict[str, Any] | None = None,
    subject_id: str | None = None,
    valid_until: datetime | str | None = None,
    source_role: str = provenance.DEFAULT_ROLE,
) -> Row | None:
    """An active memory in this scope that already says exactly this.

    Exact identity only, and scoped: the same sentence in two scopes is two
    facts, because one may be shared and the other private.
    """
    cleaned_context = security.redact_value(context or {})[0]
    hashed = content_hash(security.redact(text).text)
    identity = memory_identity(
        {
            "scope_id": scope_id,
            "subject_id": subject_id,
            "kind": kind.strip(),
            "context": cleaned_context,
            "valid_until": valid_until,
            "source_role": source_role,
        }
    )
    advisory_lock(
        conn,
        "memory-identity:"
        + hashlib.sha256(json.dumps([identity, hashed], sort_keys=True).encode()).hexdigest(),
    )
    return conn.execute(
        """SELECT * FROM memories
            WHERE scope_id=%s AND status='active' AND content_hash=%s
              AND kind=%s AND context=%s
              AND subject_id IS NOT DISTINCT FROM %s::uuid
              AND valid_until IS NOT DISTINCT FROM %s::timestamptz
              AND (valid_until IS NULL OR valid_until > now())
              AND source_role=%s
            ORDER BY created_at LIMIT 1""",
        (
            scope_id,
            hashed,
            kind.strip(),
            Jsonb(cleaned_context),
            subject_id,
            as_datetime(valid_until),
            source_role,
        ),
    ).fetchone()


@maintenance.write_transaction
def add_memory(
    conn: psycopg.Connection,
    *,
    scope_id: str,
    author_id: str,
    text: str,
    kind: str,
    subject_id: str | None = None,
    context: dict[str, Any] | None = None,
    tags: list[str] | None = None,
    agent_id: str | None = None,
    importance: float = 0.6,
    confidence: float = 0.9,
    extraction_version: str = "manual",
    judge_run_id: int | None = None,
    valid_until: datetime | str | None = None,
    source_role: str = provenance.DEFAULT_ROLE,
    review_status: str = "pending",
    memory_id: str | None = None,
) -> str:
    """Insert one authoritative memory and enqueue its index operation.

    `review_status` defaults to pending because most writes are automatic: the
    fact is usable immediately and a human confirms or deletes it later. A
    caller storing a user's own explicit statement passes `confirmed`.
    """
    text = text.strip()
    kind = kind.strip()
    if not text:
        raise ValueError("memory text is blank")
    if len(text) > MAX_MEMORY_CHARS:
        raise ValueError(f"memory text exceeds {MAX_MEMORY_CHARS} characters")
    if not kind or len(kind) > 64:
        raise ValueError("memory kind must contain 1–64 characters")
    if review_status not in REVIEW_STATUSES:
        raise ValueError(f"unknown review status: {review_status!r}")
    provenance.validate(source_role)
    cleaned = security.redact(text)
    context, context_redactions = security.redact_value(context or {})
    tags, tag_redactions = security.redact_value(tags or [])
    memory_id = memory_id or str(uuid.uuid4())
    now = utcnow()
    row = conn.execute(
        """INSERT INTO memories
           (id,scope_id,subject_id,author_id,agent_id,kind,text,importance,confidence,
            status,valid_from,valid_until,created_at,updated_at,extraction_version,
            judge_run_id,source_role,review_status,content_hash,context,tags,redacted)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'active',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
           RETURNING *""",
        (
            memory_id,
            scope_id,
            subject_id,
            author_id,
            agent_id,
            kind,
            cleaned.text,
            importance,
            confidence,
            now,
            as_datetime(valid_until),
            now,
            now,
            extraction_version,
            judge_run_id,
            source_role,
            review_status,
            content_hash(cleaned.text),
            Jsonb(context),
            Jsonb(tags),
            bool(cleaned.redacted or context_redactions > 0 or tag_redactions > 0),
        ),
    ).fetchone()
    row = _returned(row, "memory insert")
    append_memory_revision(conn, row)
    outbox.enqueue(
        conn,
        collection=vectors.MEMORIES,
        entity_id=memory_id,
        operation="upsert",
        payload=mem_payload(row),
    )
    return memory_id


def append_memory_revision(conn: psycopg.Connection, row: Row) -> None:
    conn.execute(
        """INSERT INTO memory_revisions
           (memory_id,revision,scope_id,subject_id,author_id,kind,text,importance,
            confidence,status,superseded_by,valid_until,extraction_version,judge_run_id,
            source_role,review_status,context,tags,redacted,created_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
           ON CONFLICT (memory_id,revision) DO NOTHING""",
        (
            row["id"],
            row["revision"],
            row["scope_id"],
            row["subject_id"],
            row["author_id"],
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
            row["review_status"],
            Jsonb(row["context"]),
            Jsonb(row["tags"]),
            row["redacted"],
            row["updated_at"],
        ),
    )
    # Metadata-only revisions retain the evidence of the unchanged wording.
    # A rewritten claim must receive its own supporting citations.
    if int(row["revision"]) > 1:
        conn.execute(
            """INSERT INTO memory_revision_evidence
               (memory_id,revision,message_id,start_char,end_char)
               SELECT e.memory_id,%s,e.message_id,e.start_char,e.end_char
                 FROM memory_revision_evidence e
                 JOIN memory_revisions previous
                   ON previous.memory_id=e.memory_id AND previous.revision=e.revision
                WHERE e.memory_id=%s AND e.revision=%s AND previous.text=%s
               ON CONFLICT DO NOTHING""",
            (row["revision"], row["id"], int(row["revision"]) - 1, row["text"]),
        )


def _load_for_write(conn: psycopg.Connection, *, memory_id: str, scopes: Sequence[str]) -> Row:
    """The row, if the caller may write to its scope. KeyError otherwise.

    KeyError rather than a distinct permission error on purpose: a memory in a
    scope the caller cannot reach must be indistinguishable from one that does
    not exist, or the API becomes an existence oracle for other people's facts.
    A scope named *explicitly* in a request is a 403 instead -- see principal.
    """
    row = conn.execute(
        "SELECT * FROM memories WHERE id=%s AND scope_id = ANY(%s)",
        (memory_id, [uuid.UUID(str(scope)) for scope in scopes]),
    ).fetchone()
    if row is None:
        raise KeyError(memory_id)
    return row


@maintenance.write_transaction
def update_memory(
    conn: psycopg.Connection,
    *,
    memory_id: str,
    scopes: Sequence[str],
    expected_revision: int,
    text: str,
    kind: str,
    context: dict[str, Any],
    tags: list[str],
    importance: float,
    confidence: float,
    valid_until: datetime | str | None,
    subject_id: str | object | None = _UNCHANGED,
    scope_id: str | None = None,
    extraction_version: str | None = None,
    judge_run_id: int | None = None,
    source_role: str | None = None,
    review_status: str | None = None,
) -> Row:
    """Atomically replace mutable memory fields and append one immutable revision."""
    text = text.strip()
    kind = kind.strip()
    if not text or len(text) > MAX_MEMORY_CHARS:
        raise ValueError("memory text must contain 1–2000 characters")
    if not kind or len(kind) > 64:
        raise ValueError("memory kind must contain 1–64 characters")
    if review_status is not None and review_status not in REVIEW_STATUSES:
        raise ValueError(f"unknown review status: {review_status!r}")
    cleaned = security.redact(text)
    context, context_redactions = security.redact_value(context)
    tags, tag_redactions = security.redact_value(tags)
    current = _load_for_write(conn, memory_id=memory_id, scopes=scopes)
    next_source_role = source_role or str(current["source_role"])
    provenance.validate(next_source_role)
    changed = conn.execute(
        """UPDATE memories
              SET text=%s,kind=%s,importance=%s,confidence=%s,context=%s,tags=%s,
                  valid_until=%s,updated_at=%s,revision=revision+1,extraction_version=%s,
                  judge_run_id=%s,source_role=%s,review_status=%s,content_hash=%s,
                  subject_id=%s,scope_id=%s,redacted=%s
            WHERE id=%s AND revision=%s""",
        (
            cleaned.text,
            kind,
            importance,
            confidence,
            Jsonb(context),
            Jsonb(tags),
            as_datetime(valid_until),
            utcnow(),
            extraction_version or current["extraction_version"],
            judge_run_id if judge_run_id is not None else current["judge_run_id"],
            next_source_role,
            review_status or current["review_status"],
            content_hash(cleaned.text),
            current["subject_id"] if subject_id is _UNCHANGED else subject_id,
            scope_id or current["scope_id"],
            bool(
                cleaned.redacted
                or context_redactions > 0
                or tag_redactions > 0
                or (bool(current["redacted"]) and cleaned.text == current["text"])
            ),
            memory_id,
            expected_revision,
        ),
    ).rowcount
    if not changed:
        raise RuntimeError("memory revision conflict")
    saved = _returned(
        conn.execute("SELECT * FROM memories WHERE id=%s", (memory_id,)).fetchone(),
        "memory reload",
    )
    append_memory_revision(conn, saved)
    outbox.enqueue(
        conn,
        collection=vectors.MEMORIES,
        entity_id=memory_id,
        operation="upsert",
        payload=mem_payload(saved),
    )
    return saved


@maintenance.write_transaction
def set_memory_status(
    conn: psycopg.Connection,
    *,
    memory_id: str,
    scopes: Sequence[str],
    status: str,
    expected_revision: int | None = None,
    superseded_by: str | None = None,
) -> Row:
    current = _load_for_write(conn, memory_id=memory_id, scopes=scopes)
    revision = int(current["revision"])
    if expected_revision is not None and revision != expected_revision:
        raise RuntimeError("memory revision conflict")
    changed = conn.execute(
        """UPDATE memories SET status=%s,superseded_by=%s,updated_at=%s,revision=revision+1
             WHERE id=%s AND revision=%s""",
        (status, superseded_by, utcnow(), memory_id, revision),
    ).rowcount
    if not changed:
        raise RuntimeError("memory revision conflict")
    saved = _returned(
        conn.execute("SELECT * FROM memories WHERE id=%s", (memory_id,)).fetchone(),
        "memory reload",
    )
    append_memory_revision(conn, saved)
    outbox.enqueue(
        conn,
        collection=vectors.MEMORIES,
        entity_id=memory_id,
        operation="delete" if status != "active" else "upsert",
        payload=(
            {"scope_id": str(saved["scope_id"])} if status != "active" else mem_payload(saved)
        ),
    )
    return saved


@maintenance.write_transaction
def set_review_status(
    conn: psycopg.Connection,
    *,
    memory_id: str,
    scopes: Sequence[str],
    review_status: str,
    reviewed_by: str,
    expected_revision: int | None = None,
) -> Row:
    """Confirm or decline a memory.

    Declining archives it in the same step: a fact a human has rejected must
    stop being retrieved, and keeping it active with a label would mean the
    label had no effect. Confirming re-activates, so a decline is reversible
    from the dashboard rather than only from the revision history.
    """
    if review_status not in REVIEW_STATUSES:
        raise ValueError(f"unknown review status: {review_status!r}")
    current = _load_for_write(conn, memory_id=memory_id, scopes=scopes)
    revision = int(current["revision"])
    if expected_revision is not None and revision != expected_revision:
        raise RuntimeError("memory revision conflict")
    status = "archived" if review_status == "declined" else "active"
    changed = conn.execute(
        """UPDATE memories
              SET review_status=%s,reviewed_by=%s,reviewed_at=now(),status=%s,
                  updated_at=%s,revision=revision+1
            WHERE id=%s AND revision=%s""",
        (review_status, reviewed_by, status, utcnow(), memory_id, revision),
    ).rowcount
    if not changed:
        raise RuntimeError("memory revision conflict")
    saved = _returned(
        conn.execute("SELECT * FROM memories WHERE id=%s", (memory_id,)).fetchone(),
        "memory reload",
    )
    append_memory_revision(conn, saved)
    outbox.enqueue(
        conn,
        collection=vectors.MEMORIES,
        entity_id=memory_id,
        operation="upsert" if status == "active" else "delete",
        payload=(
            mem_payload(saved) if status == "active" else {"scope_id": str(saved["scope_id"])}
        ),
    )
    return saved


def mem_payload(row: Row | dict[str, Any]) -> dict[str, Any]:
    data = dict(row)
    return {
        "scope_id": str(data["scope_id"]),
        "subject_id": str(data["subject_id"]) if data.get("subject_id") else None,
        "author_id": str(data["author_id"]),
        "agent_id": data.get("agent_id"),
        "kind": data["kind"],
        "text": data["text"],
        "importance": float(data["importance"]),
        "confidence": float(data["confidence"]),
        "status": data["status"],
        "source_role": data["source_role"],
        "review_status": data.get("review_status", "pending"),
        "context": data.get("context") or {},
        "tags": data.get("tags") or [],
        "valid_until": iso(data.get("valid_until")),
        "created_at": iso(data.get("created_at")),
        "updated_at": iso(data.get("updated_at")),
        "revision": int(data.get("revision", 1)),
        "redacted": bool(data.get("redacted", False)),
    }


def memory_active(row: Row | dict[str, Any], *, now: datetime | None = None) -> bool:
    """Active and not expired.

    Review status is deliberately not part of this: an unconfirmed memory is
    live and retrievable, because a fact nobody has got round to confirming is
    still the best thing we know.
    """
    data = dict(row)
    if data["status"] != "active":
        return False
    valid_until = data.get("valid_until")
    if not valid_until:
        return True
    expiry = as_datetime(valid_until)
    if expiry is None:
        return False
    return expiry > (now or datetime.now(UTC))
