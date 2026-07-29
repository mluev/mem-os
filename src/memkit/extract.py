"""Extraction pipeline: window -> candidates -> judge -> applied operations.

This is steps 3-7 of the write path in docs/01-architecture.md. It runs behind
the ingest endpoint so the agent never waits on the judge.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid as uuidlib
from dataclasses import dataclass
from typing import Any

from qdrant_client import QdrantClient

from . import judge, mutate, taskboard, vectors
from .db import utcnow
from .embed import Embedder

logger = logging.getLogger(__name__)

WINDOW_SIZE = 10
CANDIDATE_COUNT = 8

# Assistant turns kept as lead-in before the first user turn of a window, so
# "it" and "that project" still resolve after a fast-forward.
CONTEXT_LEAD = 3


@dataclass
class ExtractionOutcome:
    added: int = 0
    updated: int = 0
    deleted: int = 0
    skipped: int = 0
    fast_forwarded: int = 0
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    judge_run_id: int | None = None
    error: str | None = None

    @property
    def applied(self) -> int:
        return self.added + self.updated + self.deleted

    def as_dict(self) -> dict[str, Any]:
        return {
            "added": self.added,
            "updated": self.updated,
            "deleted": self.deleted,
            "skipped": self.skipped,
            "fast_forwarded": self.fast_forwarded,
            "cost_usd": round(self.cost_usd, 6),
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "judge_run_id": self.judge_run_id,
            "error": self.error,
        }


def unprocessed_window(
    conn: sqlite3.Connection, session_id: str, limit: int = WINDOW_SIZE
) -> list[sqlite3.Row]:
    """Oldest unprocessed messages in a session, in spoken order.

    Assistant turns are included: they are what let the judge resolve "it" and
    "that project". Rule 3 of the prompt is what stops their content becoming
    facts about the user.
    """
    rows = conn.execute(
        """SELECT id, role, content, created_at FROM messages
            WHERE session_id = ? AND processed = 0
            ORDER BY id LIMIT ?""",
        (session_id, limit),
    ).fetchall()
    return list(rows)


def fast_forward_to_user_turn(conn: sqlite3.Connection, session_id: str) -> int:
    """Mark leading assistant-only messages processed without calling the judge.

    A window containing no user turn cannot yield a fact about the user -- prompt
    rule 3 forbids storing what the assistant said -- so paying for it is pure
    waste. It is not a rare case: this corpus runs 3854 assistant turns against
    389 user turns, because a long autonomous coding session emits hundreds of
    consecutive assistant messages. Measured before this fix, 207 of 466 windows
    (44%) were assistant-only, about $1.03 of a $2.31 backfill.

    ``CONTEXT_LEAD`` assistant turns immediately before the first user turn are
    preserved, so the judge still has the context that resolves "it" and "that
    project".

    Returns the number of messages skipped.
    """
    first_user = conn.execute(
        """SELECT MIN(id) i FROM messages
            WHERE session_id = ? AND processed = 0 AND role = 'user'""",
        (session_id,),
    ).fetchone()["i"]

    if first_user is None:
        # No user turns left anywhere in this session: everything remaining is
        # assistant narration that can never produce a memory.
        cur = conn.execute(
            "UPDATE messages SET processed = 1 WHERE session_id = ? AND processed = 0",
            (session_id,),
        )
        return cur.rowcount

    lead = conn.execute(
        """SELECT MIN(id) i FROM (
               SELECT id FROM messages
                WHERE session_id = ? AND processed = 0 AND id < ?
                ORDER BY id DESC LIMIT ?)""",
        (session_id, first_user, CONTEXT_LEAD),
    ).fetchone()["i"]
    boundary = lead if lead is not None else first_user

    cur = conn.execute(
        """UPDATE messages SET processed = 1
            WHERE session_id = ? AND processed = 0 AND id < ?""",
        (session_id, boundary),
    )
    return cur.rowcount


def messages_since_last(conn: sqlite3.Connection, session_id: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) n FROM messages WHERE session_id = ? AND processed = 0",
        (session_id,),
    ).fetchone()
    return int(row["n"])


def find_candidates(
    client: QdrantClient,
    embedder: Embedder,
    *,
    window: list[sqlite3.Row],
    owner_id: str,
    limit: int = CANDIDATE_COUNT,
) -> list[dict[str, Any]]:
    """Top-N existing facts similar to the window, for UPDATE detection.

    Without these the judge cannot know a fact already exists, and a month later
    the store holds three contradictory rows about the same subject.
    """
    text = "\n".join(r["content"] for r in window)
    if not text.strip():
        return []
    vec = embedder.encode_one(text)
    hits = vectors.search(
        client,
        vectors.MEMORIES,
        vec,
        limit=limit,
        must=[
            vectors.keyword("owner_id", owner_id),
            vectors.keyword("status", "active"),
        ],
    )
    return [
        {
            "id": str(h.id),
            "text": h.payload.get("text", ""),
            "type": h.payload.get("type"),
            "importance": h.payload.get("importance"),
            "task_status": h.payload.get("task_status"),
        }
        for h in hits
    ]


def _payload(
    row: dict[str, Any], *, task_status: str | None = None
) -> dict[str, Any]:
    payload = {
        "owner_id": row["owner_id"],
        "agent_id": row["agent_id"],
        "scope": row["scope"],
        "scope_key": row["scope_key"],
        "type": row["type"],
        "text": row["text"],
        "importance": row["importance"],
        "status": "active",
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
    if row["type"] == "task":
        payload["task_status"] = task_status or "unknown"
    return payload


def apply_ops(
    conn: sqlite3.Connection,
    client: QdrantClient,
    embedder: Embedder,
    *,
    ops: list[judge.Op],
    owner_id: str,
    agent_id: str | None,
    scope_key: str | None,
    judge_run_id: int | None,
    source_message_ids: list[int],
) -> ExtractionOutcome:
    out = ExtractionOutcome(judge_run_id=judge_run_id)
    now = utcnow()

    for op in ops:
        if op.op == "ADD":
            mem_id = str(uuidlib.uuid4())
            row = {
                "id": mem_id, "owner_id": owner_id, "agent_id": agent_id,
                "scope": op.scope or "user",
                "scope_key": scope_key if (op.scope or "user") != "user" else None,
                "type": op.type, "text": op.text,
                "importance": op.importance, "created_at": now, "updated_at": now,
            }
            conn.execute(
                """INSERT INTO memories
                   (id, owner_id, agent_id, scope, scope_key, type, text,
                    importance, confidence, status, valid_from, valid_until,
                    created_at, updated_at, extraction_version, judge_run_id)
                   VALUES (?,?,?,?,?,?,?,?,?,'active',?,?,?,?,?,?)""",
                (
                    mem_id, owner_id, agent_id, row["scope"], row["scope_key"],
                    op.type, op.text, op.importance, op.confidence, now,
                    op.valid_until, now, now, judge.PROMPT_VERSION, judge_run_id,
                ),
            )
            workflow_status = None
            if op.type == "task":
                workflow_status = taskboard.set_inferred_status(
                    conn,
                    mem_id,
                    op.task_status,
                    project_key=row["scope_key"],
                )
            _link_sources(conn, mem_id, source_message_ids)
            vectors.upsert(
                client, vectors.MEMORIES,
                [
                    (
                        mem_id,
                        embedder.encode_one(op.text or ""),
                        _payload(row, task_status=workflow_status),
                    )
                ],
            )
            out.added += 1

        elif op.op == "UPDATE":
            existing = conn.execute(
                "SELECT * FROM memories WHERE id = ? AND status = 'active'",
                (op.id,),
            ).fetchone()
            if existing is None:
                # The judge referenced a candidate that no longer exists (or was
                # never real). Dropping it is correct; a hallucinated id must not
                # silently become a new fact.
                out.skipped += 1
                continue
            changes = {
                "text": op.text or existing["text"],
                "type": op.type or existing["type"],
                "importance": op.importance
                if op.importance is not None else existing["importance"],
                "confidence": op.confidence
                if op.confidence is not None else existing["confidence"],
                "valid_until": op.valid_until or existing["valid_until"],
                "judge_run_id": judge_run_id,
            }
            result = mutate.update_memory(
                conn,
                client,
                embedder,
                memory_id=existing["id"],
                changes=changes,
            )
            saved = result.row or dict(existing)
            workflow_status = None
            if saved["type"] == "task":
                workflow_status = taskboard.set_inferred_status(
                    conn,
                    existing["id"],
                    op.task_status,
                    project_key=scope_key,
                )
            _link_sources(conn, existing["id"], source_message_ids)
            # updated_at moves forward on purpose: docs/05-retrieval.md ages
            # facts from updated_at, so a fact confirmed today is fresh again.
            result.apply_index(client)
            if workflow_status is not None:
                vectors.set_payload(
                    client,
                    vectors.MEMORIES,
                    [existing["id"]],
                    {"task_status": workflow_status},
                )
            out.updated += 1

        elif op.op == "DELETE":
            existing = conn.execute(
                "SELECT id FROM memories WHERE id = ? AND status = 'active'",
                (op.id,),
            ).fetchone()
            if existing is None:
                out.skipped += 1
                continue
            # Soft delete: the row stays, the point goes. reindex filters on
            # status='active' so this does not come back.
            result = mutate.set_status(
                conn,
                client,
                embedder,
                memory_id=existing["id"],
                status="expired",
            )
            try:
                result.apply_index(client)
            except Exception:  # noqa: BLE001 - SQLite is the truth; reindex repairs
                logger.warning("could not remove point %s from qdrant", existing["id"])
            out.deleted += 1

    return out


def _link_sources(
    conn: sqlite3.Connection, memory_id: str, message_ids: list[int]
) -> None:
    conn.executemany(
        "INSERT INTO memory_sources (memory_id, message_id) VALUES (?, ?) "
        "ON CONFLICT DO NOTHING",
        [(memory_id, mid) for mid in message_ids],
    )


def run_extraction(
    conn: sqlite3.Connection,
    client: QdrantClient,
    embedder: Embedder,
    *,
    session_id: str,
    owner_id: str,
    monthly_limit_usd: float,
    api_key: str = "",
    gemini_api_key: str = "",
    project: str = "",
    location: str = "",
    agent_id: str | None = None,
    force: bool = False,
    model: str | None = None,
) -> ExtractionOutcome:
    """One extraction pass over a session's unprocessed tail."""
    # Skip past assistant-only stretches first — free, and it is 44% of windows
    # on this corpus.
    skipped_free = fast_forward_to_user_turn(conn, session_id)

    window = unprocessed_window(conn, session_id)
    if not window:
        return ExtractionOutcome(fast_forwarded=skipped_free)
    if not force and len(window) < judge.MESSAGES_PER_EXTRACTION:
        return ExtractionOutcome(fast_forwarded=skipped_free)
    if not any(r["role"] == "user" for r in window):
        # Belt and braces: the fast-forward should have handled this, but never
        # pay for a window that cannot contain a fact about the user.
        conn.executemany(
            "UPDATE messages SET processed = 1 WHERE id = ?",
            [(int(r["id"]),) for r in window],
        )
        return ExtractionOutcome(fast_forwarded=skipped_free + len(window))

    scope_key = _session_project(conn, session_id)
    candidates = find_candidates(
        client, embedder, window=window, owner_id=owner_id
    )
    result = judge.extract(
        conn,
        window=window,
        candidates=candidates,
        api_key=api_key,
        gemini_api_key=gemini_api_key,
        project=project,
        location=location,
        monthly_limit_usd=monthly_limit_usd,
        model=model or judge.DEFAULT_MODEL,
    )

    if result.error == "monthly_cost_limit_reached":
        # Leave the messages unprocessed so they are picked up once the budget
        # rolls over or the limit is raised.
        return ExtractionOutcome(error=result.error)

    ids = [int(r["id"]) for r in window]
    outcome = apply_ops(
        conn, client, embedder,
        ops=result.ops, owner_id=owner_id, agent_id=agent_id,
        scope_key=scope_key, judge_run_id=result.judge_run_id,
        source_message_ids=ids,
    )
    outcome.cost_usd = result.cost_usd
    outcome.input_tokens = result.input_tokens
    outcome.output_tokens = result.output_tokens
    outcome.judge_run_id = result.judge_run_id
    outcome.error = result.error
    outcome.fast_forwarded = skipped_free

    # Mark processed even when the judge returned nothing: an empty operations
    # list is a correct and common answer, and re-reading the same window would
    # just pay for it again.
    if result.error is None:
        conn.executemany(
            "UPDATE messages SET processed = 1 WHERE id = ?", [(i,) for i in ids]
        )
    return outcome


def _session_project(conn: sqlite3.Connection, session_id: str) -> str | None:
    row = conn.execute(
        "SELECT meta FROM sessions WHERE id = ?", (session_id,)
    ).fetchone()
    if row is None or not row["meta"]:
        return None
    try:
        return (json.loads(row["meta"]) or {}).get("project")
    except (ValueError, TypeError):
        return None
