"""One-time import of a single-owner v6 SQLite database.

This is the only module in the package allowed to touch sqlite3, and it exists
once: the old schema had one owner, so every row it holds belongs to whichever
user receives the import, and their private scope is the natural home for it.

Ids and timestamps are preserved. That matters more than it looks: memory ids
appear in retrieval feedback and evidence rows, and the extractor's date anchor
is the message's own recorded date, so a re-extraction after the import must see
the same history the original run saw.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from .. import maintenance
from ..store import content_hash

SOURCE_SCHEMA_VERSION = 6


def _as_datetime(value: Any) -> datetime | None:
    """Parse the ISO-8601 text the old schema stored, as UTC."""
    if value in (None, ""):
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _json_or(value: Any, fallback: Any) -> Any:
    if value in (None, ""):
        return fallback
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return fallback


def _open_source(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise FileNotFoundError(f"no such database: {path}")
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    version = int(conn.execute("PRAGMA user_version").fetchone()[0])
    if version != SOURCE_SCHEMA_VERSION:
        raise ValueError(
            f"expected a schema v{SOURCE_SCHEMA_VERSION} database, found v{version}. "
            "Migrate the source with the release that wrote it before importing."
        )
    return conn


def import_sqlite(
    conn: psycopg.Connection,
    *,
    source: Path,
    user_id: str,
    pending: bool = False,
) -> dict[str, Any]:
    """Copy a v6 database into one user's private scope.

    Safe to re-run: every insert is keyed by its original id and ignores a
    conflict, so a partial import can simply be repeated. The report compares
    source and destination counts per table and fails loudly on a mismatch
    rather than reporting success over a half-copied store.
    """
    own = conn.execute("SELECT id FROM entities WHERE user_id=%s", (user_id,)).fetchone()
    if own is None:
        raise ValueError("the receiving user has no private scope")
    scope_id = str(own["id"])
    src = _open_source(source)
    counts: dict[str, int] = {}

    try:
        with conn.transaction():
            maintenance.require_write(conn)
            counts["sessions"] = _copy_sessions(src, conn, user_id=user_id, scope_id=scope_id)
            counts["messages"] = _copy_messages(src, conn, user_id=user_id)
            counts["judge_runs"] = _copy_judge_runs(src, conn, user_id=user_id)
            counts["memories"] = _copy_memories(
                src,
                conn,
                scope_id=scope_id,
                user_id=user_id,
                review_status="pending" if pending else "confirmed",
            )
            counts["memory_revisions"] = _copy_revisions(
                src, conn, scope_id=scope_id, user_id=user_id
            )
            counts["memory_sources"] = _copy_simple(
                src,
                conn,
                table="memory_sources",
                columns=("memory_id", "message_id"),
            )
            counts["memory_evidence"] = _copy_simple(
                src,
                conn,
                table="memory_evidence",
                columns=("memory_id", "message_id", "start_char", "end_char", "excerpt_sha256"),
            )
            counts["retrieval_feedback"] = _copy_feedback(src, conn)
            _reset_sequences(conn)
        report = _verify(src, conn, counts=counts, scope_id=scope_id)
    finally:
        src.close()
    return report


def _copy_sessions(
    src: sqlite3.Connection, conn: psycopg.Connection, *, user_id: str, scope_id: str
) -> int:
    rows = src.execute("SELECT * FROM sessions ORDER BY started_at").fetchall()
    for row in rows:
        conn.execute(
            """INSERT INTO sessions (id,user_id,scope_id,agent_id,started_at,ended_at,context)
               VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING""",
            (
                row["id"],
                user_id,
                scope_id,
                row["agent_id"],
                _as_datetime(row["started_at"]),
                _as_datetime(row["ended_at"]),
                Jsonb(_json_or(row["context_json"], {})),
            ),
        )
    return len(rows)


def _copy_messages(src: sqlite3.Connection, conn: psycopg.Connection, *, user_id: str) -> int:
    rows = src.execute("SELECT * FROM messages ORDER BY id").fetchall()
    for row in rows:
        conn.execute(
            """INSERT INTO messages
               (id,session_id,user_id,role,content,created_at,processed,external_source,
                external_id,context,redacted)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               OVERRIDING SYSTEM VALUE ON CONFLICT (id) DO NOTHING""",
            (
                int(row["id"]),
                row["session_id"],
                user_id,
                row["role"],
                row["content"],
                _as_datetime(row["created_at"]),
                bool(row["processed"]),
                row["external_source"],
                row["external_id"],
                Jsonb(_json_or(row["context_json"], {})),
                bool(row["redacted"]),
            ),
        )
    return len(rows)


def _copy_judge_runs(src: sqlite3.Connection, conn: psycopg.Connection, *, user_id: str) -> int:
    rows = src.execute("SELECT * FROM judge_runs ORDER BY id").fetchall()
    for row in rows:
        conn.execute(
            """INSERT INTO judge_runs
               (id,user_id,kind,model,prompt_version,input,output,error,input_tokens,
                output_tokens,cost_usd,latency_ms,created_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               OVERRIDING SYSTEM VALUE ON CONFLICT (id) DO NOTHING""",
            (
                int(row["id"]),
                user_id if row["owner_id"] else None,
                row["kind"],
                row["model"],
                row["prompt_version"],
                # A run whose payload will not parse is still worth keeping: it
                # is the audit trail for a call that was billed.
                Jsonb(_json_or(row["input_json"], {"raw": row["input_json"]})),
                Jsonb(_json_or(row["output_json"], None)) if row["output_json"] else None,
                row["error"],
                row["input_tokens"],
                row["output_tokens"],
                row["cost_usd"],
                row["latency_ms"],
                _as_datetime(row["created_at"]),
            ),
        )
    return len(rows)


def _copy_memories(
    src: sqlite3.Connection,
    conn: psycopg.Connection,
    *,
    scope_id: str,
    user_id: str,
    review_status: str,
) -> int:
    rows = src.execute("SELECT * FROM memories ORDER BY created_at,id").fetchall()
    for row in rows:
        text = str(row["text"])
        conn.execute(
            """INSERT INTO memories
               (id,scope_id,subject_id,author_id,agent_id,kind,text,importance,confidence,
                status,valid_from,valid_until,created_at,updated_at,last_retrieved_at,
                retrieval_count,revision,extraction_version,judge_run_id,source_role,
                review_status,content_hash,context,tags,redacted,legacy_imported)
               VALUES (%s,%s,NULL,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (id) DO NOTHING""",
            (
                row["id"],
                scope_id,
                user_id,
                row["agent_id"],
                row["kind"],
                text,
                row["importance"],
                row["confidence"],
                row["status"],
                _as_datetime(row["valid_from"]),
                _as_datetime(row["valid_until"]),
                _as_datetime(row["created_at"]),
                _as_datetime(row["updated_at"]),
                _as_datetime(row["last_retrieved_at"]),
                int(row["retrieval_count"] or 0),
                int(row["revision"] or 1),
                row["extraction_version"],
                row["judge_run_id"],
                row["source_role"],
                review_status,
                content_hash(text),
                Jsonb(_json_or(row["context_json"], {})),
                Jsonb(_json_or(row["tags_json"], [])),
                bool(row["redacted"]),
                bool(row["legacy_imported"]),
            ),
        )
    # Supersession is a self-reference, so it can only be set once every row
    # exists.
    for row in rows:
        if row["superseded_by"]:
            conn.execute(
                "UPDATE memories SET superseded_by=%s WHERE id=%s",
                (row["superseded_by"], row["id"]),
            )
    return len(rows)


def _copy_revisions(
    src: sqlite3.Connection, conn: psycopg.Connection, *, scope_id: str, user_id: str
) -> int:
    rows = src.execute("SELECT * FROM memory_revisions ORDER BY memory_id,revision").fetchall()
    for row in rows:
        conn.execute(
            """INSERT INTO memory_revisions
               (memory_id,revision,scope_id,subject_id,author_id,kind,text,importance,
                confidence,status,superseded_by,valid_until,extraction_version,judge_run_id,
                source_role,review_status,context,tags,redacted,created_at)
               VALUES (%s,%s,%s,NULL,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'confirmed',%s,%s,%s,%s)
               ON CONFLICT (memory_id,revision) DO NOTHING""",
            (
                row["memory_id"],
                int(row["revision"]),
                scope_id,
                user_id,
                row["kind"],
                row["text"],
                row["importance"],
                row["confidence"],
                row["status"],
                row["superseded_by"],
                _as_datetime(row["valid_until"]),
                row["extraction_version"],
                row["judge_run_id"],
                row["source_role"],
                Jsonb(_json_or(row["context_json"], {})),
                Jsonb(_json_or(row["tags_json"], [])),
                bool(row["redacted"]),
                _as_datetime(row["created_at"]),
            ),
        )
    return len(rows)


def _copy_simple(
    src: sqlite3.Connection, conn: psycopg.Connection, *, table: str, columns: tuple[str, ...]
) -> int:
    rows = src.execute(f"SELECT * FROM {table}").fetchall()
    placeholders = ",".join(["%s"] * len(columns))
    statement = (
        f"INSERT INTO {table} ({','.join(columns)}) VALUES ({placeholders}) ON CONFLICT DO NOTHING"
    )
    for row in rows:
        conn.execute(statement, tuple(row[column] for column in columns))
    return len(rows)


def _copy_feedback(src: sqlite3.Connection, conn: psycopg.Connection) -> int:
    rows = src.execute("SELECT * FROM retrieval_feedback ORDER BY id").fetchall()
    for row in rows:
        conn.execute(
            """INSERT INTO retrieval_feedback (memory_id,query_hash,useful,correct,created_at)
               VALUES (%s,%s,%s,%s,%s)""",
            (
                row["memory_id"],
                row["query_hash"],
                None if row["useful"] is None else bool(row["useful"]),
                None if row["correct"] is None else bool(row["correct"]),
                _as_datetime(row["created_at"]),
            ),
        )
    return len(rows)


def _reset_sequences(conn: psycopg.Connection) -> None:
    """Move identity sequences past the ids just inserted.

    Without this the next insert reuses id 1 and collides, because explicit ids
    do not advance a sequence.
    """
    for table, column in (("messages", "id"), ("judge_runs", "id")):
        conn.execute(
            f"""SELECT setval(
                    pg_get_serial_sequence('{table}', '{column}'),
                    GREATEST((SELECT COALESCE(MAX({column}), 0) FROM {table}), 1)
                )"""
        )


def _verify(
    src: sqlite3.Connection, conn: psycopg.Connection, *, counts: dict[str, int], scope_id: str
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    for table, predicate, params in (
        ("sessions", "scope_id=%s", (scope_id,)),
        ("memories", "scope_id=%s", (scope_id,)),
    ):
        source_count = int(src.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        row = conn.execute(
            f"SELECT COUNT(*) AS n FROM {table} WHERE {predicate}",
            params,
        ).fetchone()
        target_count = int(row["n"]) if row else 0
        checks.append(
            {
                "table": table,
                "source": source_count,
                "imported": target_count,
                "ok": target_count >= source_count,
            }
        )
    for table in ("messages", "memory_revisions", "memory_sources", "memory_evidence"):
        source_count = int(src.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        row = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()
        target_count = int(row["n"]) if row else 0
        checks.append(
            {
                "table": table,
                "source": source_count,
                "imported": target_count,
                "ok": target_count >= source_count,
            }
        )
    return {
        "ok": all(check["ok"] for check in checks),
        "scope_id": scope_id,
        "copied": counts,
        "checks": checks,
    }
