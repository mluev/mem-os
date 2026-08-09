"""Short-transaction, evidence-precise memory extraction."""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from dataclasses import dataclass
from typing import Any

from . import judge, outbox, provenance, store, vectors
from .db import transaction, utcnow

logger = logging.getLogger(__name__)
WINDOW_SIZE = 10


@dataclass
class ExtractionOutcome:
    added: int = 0
    updated: int = 0
    deleted: int = 0
    skipped: int = 0
    rejected: int = 0
    cost_usd: float = 0.0
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
            "rejected": self.rejected,
            "cost_usd": round(self.cost_usd, 6),
            "judge_run_id": self.judge_run_id,
            "error": self.error,
        }


def messages_since_last(conn: sqlite3.Connection, session_id: str) -> int:
    return int(
        conn.execute(
            "SELECT COUNT(*) FROM messages WHERE session_id=? AND processed=0",
            (session_id,),
        ).fetchone()[0]
    )


def unprocessed_window(conn: sqlite3.Connection, session_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT * FROM messages WHERE session_id=? AND processed=0
            ORDER BY id LIMIT ?""",
        (session_id, WINDOW_SIZE),
    ).fetchall()


def session_context(conn: sqlite3.Connection, session_id: str) -> dict[str, Any]:
    row = conn.execute("SELECT context_json FROM sessions WHERE id=?", (session_id,)).fetchone()
    if row is None:
        raise ValueError("unknown session")
    return json.loads(row["context_json"] or "{}")


def find_candidates(
    conn: sqlite3.Connection,
    *,
    owner_id: str,
    context: dict[str, Any],
    limit: int = 8,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT * FROM memories
            WHERE owner_id=? AND status='active' AND context_json=?
            ORDER BY updated_at DESC,id LIMIT ?""",
        (owner_id, json.dumps(context, ensure_ascii=False, sort_keys=True), limit),
    ).fetchall()
    return [
        {
            "id": row["id"],
            "kind": row["kind"],
            "text": row["text"],
            "importance": row["importance"],
            "context": context,
        }
        for row in rows
    ]


def _validated_evidence(
    conn: sqlite3.Connection,
    op: judge.Op,
    *,
    allowed_message_ids: set[int],
) -> tuple[list[dict[str, Any]], set[str]] | None:
    citations = op.evidence or []
    if op.op in {"ADD", "UPDATE"} and not citations:
        return None
    evidence: list[dict[str, Any]] = []
    roles: set[str] = set()
    for citation in citations:
        message_id = citation["message_id"]
        if message_id not in allowed_message_ids:
            return None
        row = conn.execute("SELECT role,content FROM messages WHERE id=?", (message_id,)).fetchone()
        if row is None:
            return None
        start = citation["start_char"]
        end = citation["end_char"]
        if end > len(row["content"]):
            return None
        excerpt = row["content"][start:end]
        if not excerpt.strip():
            return None
        roles.add(row["role"])
        evidence.append(
            {
                "message_id": message_id,
                "start_char": start,
                "end_char": end,
                "excerpt_sha256": hashlib.sha256(excerpt.encode()).hexdigest(),
            }
        )
    return evidence, roles


def _context_allowed(operation: dict[str, str], session: dict[str, Any]) -> bool:
    return all(key in session and str(session[key]) == value for key, value in operation.items())


def _link_evidence(
    conn: sqlite3.Connection, memory_id: str, evidence: list[dict[str, Any]]
) -> None:
    conn.executemany(
        "INSERT OR IGNORE INTO memory_sources(memory_id,message_id) VALUES (?,?)",
        [(memory_id, item["message_id"]) for item in evidence],
    )
    conn.executemany(
        """INSERT OR IGNORE INTO memory_evidence
           (memory_id,message_id,start_char,end_char,excerpt_sha256)
           VALUES (?,?,?,?,?)""",
        [
            (
                memory_id,
                item["message_id"],
                item["start_char"],
                item["end_char"],
                item["excerpt_sha256"],
            )
            for item in evidence
        ],
    )


def apply_ops(
    conn: sqlite3.Connection,
    *,
    ops: list[judge.Op],
    owner_id: str,
    agent_id: str,
    context: dict[str, Any],
    judge_run_id: int,
    source_message_ids: list[int],
    extraction_version: str = judge.PROMPT_VERSION,
) -> ExtractionOutcome:
    outcome = ExtractionOutcome(judge_run_id=judge_run_id)
    allowed = set(source_message_ids)
    for op in ops:
        validated = _validated_evidence(conn, op, allowed_message_ids=allowed)
        if validated is None:
            outcome.rejected += 1
            continue
        evidence, roles = validated
        if not provenance.may_write(op=op.op, roles=roles):
            outcome.rejected += 1
            continue
        if not _context_allowed(op.context or {}, context):
            outcome.rejected += 1
            continue
        source_role = provenance.source_role_for(roles)
        if op.op == "ADD":
            memory_id = store.add_memory(
                conn,
                owner_id=owner_id,
                text=op.text or "",
                kind=op.kind or "fact",
                context=op.context or {},
                tags=op.tags or [],
                agent_id=agent_id,
                importance=op.importance or 0.6,
                confidence=op.confidence or 0.9,
                valid_until=op.valid_until,
                extraction_version=extraction_version,
                judge_run_id=judge_run_id,
                source_role=source_role,
            )
            _link_evidence(conn, memory_id, evidence)
            outcome.added += 1
            continue

        existing = conn.execute(
            "SELECT * FROM memories WHERE id=? AND owner_id=? AND status='active'",
            (op.id, owner_id),
        ).fetchone()
        if existing is None:
            outcome.skipped += 1
            continue
        existing_context = json.loads(existing["context_json"] or "{}")
        if existing_context != (op.context or {}):
            outcome.rejected += 1
            continue
        if op.op == "DELETE":
            conn.execute(
                "UPDATE memories SET status='archived',updated_at=? WHERE id=?",
                (utcnow(), existing["id"]),
            )
            outbox.enqueue(
                conn,
                collection=vectors.MEMORIES,
                entity_id=existing["id"],
                operation="delete",
            )
            outcome.deleted += 1
            continue

        now = utcnow()
        conn.execute(
            """UPDATE memories
                  SET text=?,kind=?,importance=?,confidence=?,valid_until=?,
                      updated_at=?,extraction_version=?,judge_run_id=?
                WHERE id=?""",
            (
                op.text,
                op.kind or existing["kind"],
                op.importance if op.importance is not None else existing["importance"],
                op.confidence if op.confidence is not None else existing["confidence"],
                op.valid_until,
                now,
                extraction_version,
                judge_run_id,
                existing["id"],
            ),
        )
        _link_evidence(conn, existing["id"], evidence)
        saved = conn.execute("SELECT * FROM memories WHERE id=?", (existing["id"],)).fetchone()
        outbox.enqueue(
            conn,
            collection=vectors.MEMORIES,
            entity_id=existing["id"],
            operation="upsert",
            payload=store.mem_payload(saved),
        )
        outcome.updated += 1
    return outcome


def run_extraction(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    owner_id: str,
    agent_id: str,
    api_key: str,
    gemini_api_key: str,
    project: str,
    location: str,
    monthly_limit_usd: float,
    model: str,
    job_id: str | None = None,
    force: bool = False,
) -> ExtractionOutcome:
    session = conn.execute(
        "SELECT owner_id,agent_id FROM sessions WHERE id=?", (session_id,)
    ).fetchone()
    if session is None:
        return ExtractionOutcome(error="unknown_session")
    if session["owner_id"] != owner_id or session["agent_id"] != agent_id:
        return ExtractionOutcome(error="session_identity_mismatch")
    window = unprocessed_window(conn, session_id)
    if not window:
        return ExtractionOutcome()
    if not force and not judge.should_extract(
        messages_since_last=len(window), session_closed=False, text=window[-1]["content"]
    ):
        return ExtractionOutcome()
    if not any(row["role"] == "user" for row in window):
        with transaction(conn):
            conn.executemany(
                "UPDATE messages SET processed=1 WHERE id=?",
                [(row["id"],) for row in window],
            )
        return ExtractionOutcome(skipped=len(window))
    context = session_context(conn, session_id)
    candidates = find_candidates(conn, owner_id=owner_id, context=context)

    # This call performs only short reservation/log transactions internally.
    result = judge.extract(
        conn,
        window=window,
        candidates=candidates,
        monthly_limit_usd=monthly_limit_usd,
        api_key=api_key,
        gemini_api_key=gemini_api_key,
        project=project,
        location=location,
        model=model,
        context=context,
        agent_id=agent_id,
        owner_id=owner_id,
        job_id=job_id,
    )
    outcome = ExtractionOutcome(
        judge_run_id=result.judge_run_id,
        cost_usd=result.cost_usd,
        error=result.error,
    )
    if result.error or result.judge_run_id is None:
        return outcome
    with transaction(conn):
        applied = apply_ops(
            conn,
            ops=result.ops,
            owner_id=owner_id,
            agent_id=agent_id,
            context=context,
            judge_run_id=result.judge_run_id,
            source_message_ids=[int(row["id"]) for row in window],
        )
        conn.executemany(
            "UPDATE messages SET processed=1 WHERE id=?",
            [(row["id"],) for row in window],
        )
    applied.cost_usd = result.cost_usd
    return applied
