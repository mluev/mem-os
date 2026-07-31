"""SQLite access. This is the source of truth; Qdrant is derived from it.

Schema follows docs/02-data-model.md, with two documented deviations:

* ``messages.external_source`` / ``external_id`` are in the base schema rather
  than bolted on later as docs/07-hermes-adapter.md proposes. The stage-1
  transcript importer needs them for idempotency, so they cannot wait.
* ``memories.judge_run_id`` exists so that ``GET /v1/memories/{id}/sources``
  can actually return the judge run it promises. The docs describe that
  response without ever linking the two tables.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 3

SCHEMA = """
CREATE TABLE IF NOT EXISTS owners (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id          TEXT PRIMARY KEY,
    owner_id    TEXT NOT NULL REFERENCES owners(id),
    agent_id    TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    ended_at    TEXT,
    meta        TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessions_owner ON sessions(owner_id, agent_id);

-- Raw messages. Never deleted: every extractor prompt rewrite must be able to
-- replay the entire history.
CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT NOT NULL REFERENCES sessions(id),
    role            TEXT NOT NULL,
    content         TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    processed       INTEGER NOT NULL DEFAULT 0,
    external_source TEXT,
    external_id     TEXT
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);
CREATE INDEX IF NOT EXISTS idx_messages_unprocessed
    ON messages(processed) WHERE processed = 0;
-- Idempotency for every writer that can replay: the transcript importer, and
-- Hermes, which has three independent paths that deliver the same turn.
CREATE UNIQUE INDEX IF NOT EXISTS idx_messages_external
    ON messages(external_source, external_id) WHERE external_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS judge_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    kind            TEXT NOT NULL,
    model           TEXT NOT NULL,
    prompt_version  TEXT NOT NULL,
    input_json      TEXT NOT NULL,
    output_json     TEXT,
    error           TEXT,
    input_tokens    INTEGER,
    output_tokens   INTEGER,
    cost_usd        REAL,
    latency_ms      INTEGER,
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_judge_runs_created ON judge_runs(created_at);

CREATE TABLE IF NOT EXISTS memories (
    id                 TEXT PRIMARY KEY,
    owner_id           TEXT NOT NULL REFERENCES owners(id),
    agent_id           TEXT,
    scope              TEXT NOT NULL,
    scope_key          TEXT,
    type               TEXT NOT NULL,
    text               TEXT NOT NULL,
    importance         REAL NOT NULL,
    confidence         REAL NOT NULL,
    status             TEXT NOT NULL,
    superseded_by      TEXT REFERENCES memories(id),
    valid_from         TEXT NOT NULL,
    valid_until        TEXT,
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL,
    last_retrieved_at  TEXT,
    retrieval_count    INTEGER NOT NULL DEFAULT 0,
    extraction_version TEXT NOT NULL,
    judge_run_id       INTEGER REFERENCES judge_runs(id),
    -- Who the claim came from: the highest-authority role among the messages
    -- this fact cites, or 'manual' when it cites none and the caller asserted
    -- it. NOT NULL and CHECKed so no write path can leave the question open --
    -- that is the whole point, see provenance.py and decisions/0006.
    --
    -- Deliberately no DEFAULT. A default would make an INSERT that forgets this
    -- column succeed and label model-authored text as something a human typed,
    -- which is the precise failure the column exists to detect. Omitting it is
    -- an error, and it should read like one.
    source_role        TEXT NOT NULL
                       CHECK(source_role IN ('user','assistant','tool','manual'))
);
CREATE INDEX IF NOT EXISTS idx_memories_owner ON memories(owner_id, status);
CREATE INDEX IF NOT EXISTS idx_memories_scope
    ON memories(owner_id, scope, scope_key);

-- Workflow metadata stays separate from memory lifecycle. Moving a card must
-- not refresh memories.updated_at: retrieval uses that timestamp for recency.
CREATE TABLE IF NOT EXISTS task_board (
    memory_id        TEXT PRIMARY KEY REFERENCES memories(id) ON DELETE CASCADE,
    workflow_status  TEXT NOT NULL
                     CHECK(workflow_status IN ('unknown','todo','doing','done')),
    project_key      TEXT,
    position         REAL NOT NULL,
    version          INTEGER NOT NULL DEFAULT 1,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_task_board_order
    ON task_board(workflow_status, project_key, position, memory_id);

CREATE TABLE IF NOT EXISTS memory_sources (
    memory_id   TEXT NOT NULL REFERENCES memories(id),
    message_id  INTEGER NOT NULL REFERENCES messages(id),
    PRIMARY KEY (memory_id, message_id)
);
"""


def utcnow() -> str:
    """ISO8601 UTC. Stored as TEXT so SQLite comparisons stay lexicographic."""
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # WAL lets the importer write while the API reads. Without it, a long
    # import blocks every search.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    # SQLite's built-in lower()/NOCASE only handle ASCII. Admin substring
    # search must case-fold Russian text too.
    conn.create_function(
        "lowerx", 1, lambda value: value.lower() if value else value, deterministic=True
    )
    return conn


def init_db(db_path: Path) -> None:
    with connect(db_path) as conn:
        current = int(conn.execute("PRAGMA user_version").fetchone()[0])
        if current > SCHEMA_VERSION:
            raise RuntimeError(
                f"database schema {current} is newer than supported {SCHEMA_VERSION}"
            )
        conn.executescript(SCHEMA)
        if current < 2:
            _backfill_task_board(conn)
        if current < 3:
            _migrate_source_role(conn)
        conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")


# The authority order from provenance.py, inlined as SQL. Kept in sync by
# tests/test_provenance.py rather than by importing -- db.py deliberately has no
# imports from the rest of the package.
_SOURCE_ROLE_FROM_SOURCES = """
    SELECT CASE
             WHEN SUM(msg.role = 'user')      > 0 THEN 'user'
             WHEN SUM(msg.role = 'tool')      > 0 THEN 'tool'
             WHEN SUM(msg.role = 'assistant') > 0 THEN 'assistant'
           END
      FROM memory_sources ms
      JOIN messages msg ON msg.id = ms.message_id
     WHERE ms.memory_id = memories.id
"""

_MEMORIES_V3_REBUILD: tuple[str, ...] = (
    """
CREATE TABLE memories_v3 (
    id                 TEXT PRIMARY KEY,
    owner_id           TEXT NOT NULL REFERENCES owners(id),
    agent_id           TEXT,
    scope              TEXT NOT NULL,
    scope_key          TEXT,
    type               TEXT NOT NULL,
    text               TEXT NOT NULL,
    importance         REAL NOT NULL,
    confidence         REAL NOT NULL,
    status             TEXT NOT NULL,
    superseded_by      TEXT REFERENCES memories(id),
    valid_from         TEXT NOT NULL,
    valid_until        TEXT,
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL,
    last_retrieved_at  TEXT,
    retrieval_count    INTEGER NOT NULL DEFAULT 0,
    extraction_version TEXT NOT NULL,
    judge_run_id       INTEGER REFERENCES judge_runs(id),
    source_role        TEXT NOT NULL
                       CHECK(source_role IN ('user','assistant','tool','manual'))
)""",
    # Derived from the evidence, not from extraction_version: that column cannot
    # tell a human POST /v1/memories from a Hermes on_memory_write, since both
    # land as 'manual'. The join is the only honest answer available
    # retrospectively.
    f"""
INSERT INTO memories_v3
SELECT id, owner_id, agent_id, scope, scope_key, type, text, importance,
       confidence, status, superseded_by, valid_from, valid_until, created_at,
       updated_at, last_retrieved_at, retrieval_count, extraction_version,
       judge_run_id,
       COALESCE(({_SOURCE_ROLE_FROM_SOURCES}), 'manual')
  FROM memories""",
    "DROP TABLE memories",
    "ALTER TABLE memories_v3 RENAME TO memories",
    "CREATE INDEX IF NOT EXISTS idx_memories_owner ON memories(owner_id, status)",
    "CREATE INDEX IF NOT EXISTS idx_memories_scope "
    "ON memories(owner_id, scope, scope_key)",
)


def _migrate_source_role(conn: sqlite3.Connection) -> None:
    """Add memories.source_role by rebuilding the table. Idempotent.

    A rebuild rather than ``ALTER TABLE ADD COLUMN`` because SQLite cannot add a
    NOT NULL column without a DEFAULT, and cannot add a CHECK at all -- and the
    DEFAULT is exactly what must not exist here (see the schema comment).

    Three things have to be right, in this order:

    * ``PRAGMA foreign_keys`` is a no-op inside a transaction, so it is set after
      committing whatever the caller had open, and the rebuild runs in its own
      explicit BEGIN/COMMIT. Python's legacy sqlite3 only auto-begins on DML, so
      the DROP and RENAME would otherwise autocommit halfway through.
    * The statements are executed one at a time and NOT through
      ``executescript``, which issues its own COMMIT before running and would
      silently end the transaction opened just above -- leaving the DROP and
      RENAME running in autocommit with no rollback. The first version of this
      function did exactly that, and the migration test is what caught it.
    * Foreign keys must be OFF for the DROP. ``task_board`` references
      ``memories(id)`` ON DELETE CASCADE -- with them on, dropping the old table
      deletes the entire kanban board. This is the one reason the pragma dance is
      not optional.
    * ``PRAGMA foreign_key_check`` inside the transaction proves the RENAME
      restored every reference before anything is committed, which is what makes
      the rollback path safe.
    """
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(memories)")}
    if "source_role" in columns:
        return  # fresh database: the schema script already created the column

    conn.commit()
    conn.execute("PRAGMA foreign_keys=OFF")
    try:
        conn.execute("BEGIN")
        for statement in _MEMORIES_V3_REBUILD:
            conn.execute(statement)
        broken = conn.execute("PRAGMA foreign_key_check").fetchall()
        if broken:
            raise RuntimeError(
                f"source_role migration left {len(broken)} dangling references; "
                "rolled back, database unchanged"
            )
        migrated = conn.execute("SELECT COUNT(*) n FROM memories").fetchone()["n"]
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.execute("PRAGMA foreign_keys=ON")
    logger.info("migrated %d memories to schema 3 (source_role)", migrated)


def _backfill_task_board(conn: sqlite3.Connection) -> None:
    """Give pre-v2 task memories stable board metadata, idempotently."""
    now = utcnow()
    rows = conn.execute(
        """SELECT m.id, m.scope_key
             FROM memories m
             LEFT JOIN task_board tb ON tb.memory_id = m.id
            WHERE m.type = 'task' AND tb.memory_id IS NULL
            ORDER BY m.updated_at DESC, m.id ASC"""
    ).fetchall()
    conn.executemany(
        """INSERT INTO task_board
           (memory_id, workflow_status, project_key, position, version,
            created_at, updated_at)
           VALUES (?, 'unknown', ?, ?, 1, ?, ?)""",
        [
            (
                row["id"],
                (row["scope_key"] or "").strip() or None,
                float(index * 1024),
                now,
                now,
            )
            for index, row in enumerate(rows)
        ],
    )


def ensure_owner(conn: sqlite3.Connection, owner_id: str, name: str) -> None:
    conn.execute(
        "INSERT INTO owners (id, name, created_at) VALUES (?, ?, ?) "
        "ON CONFLICT(id) DO NOTHING",
        (owner_id, name, utcnow()),
    )


def ensure_session(
    conn: sqlite3.Connection,
    session_id: str,
    owner_id: str,
    agent_id: str,
    started_at: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO sessions (id, owner_id, agent_id, started_at) "
        "VALUES (?, ?, ?, ?) ON CONFLICT(id) DO NOTHING",
        (session_id, owner_id, agent_id, started_at or utcnow()),
    )


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Commit on success, roll back on failure.

    Note that COMMIT and ROLLBACK act on the *connection*, not on the block. That
    is why a connection must never be shared between threads that write — see
    ``ConnectionPool``.
    """
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


class ConnectionPool:
    """One SQLite connection per thread, opened on first use.

    A single shared connection cannot be used with manual transactions from more
    than one thread: ``transaction()`` commits the connection, not the caller's
    unit of work, so one thread's COMMIT persists another thread's half-finished
    write and one thread's ROLLBACK discards it. FastAPI runs every ``def``
    endpoint in a threadpool and runs background tasks alongside them, so two
    concurrent writers is the normal case here, not an edge case — an extraction
    backfill with the dashboard open hits it immediately.

    Connections are cheap (same file, WAL, no handshake) and the threadpool reuses
    threads, so this opens a handful in practice. WAL allows one writer plus many
    concurrent readers; a second writer waits out ``busy_timeout`` and then fails
    loudly, which is the outcome we want instead of silent interleaving.
    """

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._local = threading.local()
        self._opened: list[sqlite3.Connection] = []
        self._lock = threading.Lock()

    def __call__(self) -> sqlite3.Connection:
        conn: sqlite3.Connection | None = getattr(self._local, "conn", None)
        if conn is None:
            conn = connect(self.db_path)
            self._local.conn = conn
            with self._lock:
                self._opened.append(conn)
        return conn

    def close_all(self) -> None:
        """Close every connection this pool handed out. Shutdown only."""
        with self._lock:
            for conn in self._opened:
                try:
                    conn.close()
                except sqlite3.Error:
                    # Best effort: shutdown must not fail because a connection
                    # from a dead thread was already closed.
                    pass
            self._opened.clear()
        self._local = threading.local()
