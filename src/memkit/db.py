"""SQLite access. This is the source of truth; Qdrant is derived from it.

The schema is documented in docs/02-data-model.md, which generates its table
listing from this module rather than restating it.

Two columns exist here that an early draft of the design left out, and both are
load-bearing rather than conveniences:

* ``messages.external_source`` / ``external_id`` are in the base schema, not
  bolted on later. The transcript importer needs them for idempotency from the
  first import, so they cannot wait for a migration.
* ``memories.judge_run_id`` is what lets ``GET /v1/memories/{id}/sources``
  return the judge run it advertises. Without it the endpoint cannot answer the
  one question it exists for.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 6

MIGRATION_V6 = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     INTEGER PRIMARY KEY,
    checksum    TEXT NOT NULL,
    applied_at  TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    memory_id UNINDEXED,
    owner_id UNINDEXED,
    text,
    kind,
    tags,
    tokenize='unicode61 remove_diacritics 2'
);

CREATE TRIGGER IF NOT EXISTS memories_fts_insert AFTER INSERT ON memories
WHEN NEW.status='active'
BEGIN
    INSERT INTO memories_fts(memory_id,owner_id,text,kind,tags)
    VALUES (NEW.id,NEW.owner_id,NEW.text,NEW.kind,NEW.tags_json);
END;

CREATE TRIGGER IF NOT EXISTS memories_fts_update
AFTER UPDATE OF text,kind,tags_json,status,owner_id ON memories
BEGIN
    DELETE FROM memories_fts WHERE memory_id=OLD.id;
    INSERT INTO memories_fts(memory_id,owner_id,text,kind,tags)
    SELECT NEW.id,NEW.owner_id,NEW.text,NEW.kind,NEW.tags_json
    WHERE NEW.status='active';
END;

CREATE TRIGGER IF NOT EXISTS memories_fts_delete AFTER DELETE ON memories
BEGIN
    DELETE FROM memories_fts WHERE memory_id=OLD.id;
END;

CREATE TABLE IF NOT EXISTS retrieval_runs (
    id            TEXT PRIMARY KEY,
    owner_id      TEXT NOT NULL REFERENCES owners(id) ON DELETE CASCADE,
    query_hash    TEXT NOT NULL,
    policy_id     TEXT NOT NULL,
    result_json   TEXT NOT NULL CHECK(json_valid(result_json)),
    timings_json  TEXT NOT NULL CHECK(json_valid(timings_json)),
    used_tokens   INTEGER NOT NULL CHECK(used_tokens >= 0),
    abstained     INTEGER NOT NULL CHECK(abstained IN (0,1)),
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_retrieval_runs_owner_created
    ON retrieval_runs(owner_id,created_at);

CREATE TABLE IF NOT EXISTS retrieval_run_feedback (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    retrieval_run_id  TEXT NOT NULL REFERENCES retrieval_runs(id) ON DELETE CASCADE,
    memory_id         TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
    useful            INTEGER CHECK(useful IN (0,1)),
    correct           INTEGER CHECK(correct IN (0,1)),
    created_at        TEXT NOT NULL,
    UNIQUE(retrieval_run_id,memory_id)
);

CREATE TABLE IF NOT EXISTS replay_batches (
    id                 TEXT PRIMARY KEY,
    owner_id           TEXT NOT NULL REFERENCES owners(id) ON DELETE CASCADE,
    job_id             TEXT REFERENCES jobs(id) ON DELETE SET NULL,
    status             TEXT NOT NULL CHECK(status IN (
                           'queued','running','review','validated','approved',
                           'promoting','promoted','failed','cancelled')),
    model              TEXT NOT NULL,
    prompt_version     TEXT NOT NULL,
    source_checksum    TEXT NOT NULL,
    shadow_path        TEXT,
    stats_json         TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(stats_json)),
    approval_checksum  TEXT,
    error              TEXT,
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_replay_batches_owner_created
    ON replay_batches(owner_id,created_at);

CREATE TABLE IF NOT EXISTS replay_items (
    id                 TEXT PRIMARY KEY,
    batch_id           TEXT NOT NULL REFERENCES replay_batches(id) ON DELETE CASCADE,
    sequence           INTEGER NOT NULL CHECK(sequence >= 0),
    action             TEXT NOT NULL CHECK(action IN ('ADD','UPDATE','DELETE')),
    target_memory_id   TEXT,
    source_revision    INTEGER,
    before_json        TEXT CHECK(before_json IS NULL OR json_valid(before_json)),
    proposed_json      TEXT CHECK(proposed_json IS NULL OR json_valid(proposed_json)),
    evidence_json      TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(evidence_json)),
    source_role        TEXT NOT NULL CHECK(source_role IN ('user','assistant','tool','manual','agent')),
    decision           TEXT NOT NULL DEFAULT 'pending'
                       CHECK(decision IN ('pending','accepted','rejected','edited')),
    reviewed_json      TEXT CHECK(reviewed_json IS NULL OR json_valid(reviewed_json)),
    reviewed_at        TEXT,
    created_at         TEXT NOT NULL,
    UNIQUE(batch_id,sequence)
);
CREATE INDEX IF NOT EXISTS idx_replay_items_batch_decision
    ON replay_items(batch_id,decision,sequence);

CREATE TABLE IF NOT EXISTS evaluation_runs (
    id            TEXT PRIMARY KEY,
    status        TEXT NOT NULL CHECK(status IN ('draft','ready','reviewing','complete','failed')),
    model         TEXT NOT NULL,
    rubric_json   TEXT NOT NULL CHECK(json_valid(rubric_json)),
    summary_json  TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(summary_json)),
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS evaluation_cases (
    id              TEXT PRIMARY KEY,
    evaluation_id   TEXT NOT NULL REFERENCES evaluation_runs(id) ON DELETE CASCADE,
    case_key        TEXT NOT NULL,
    prompt          TEXT NOT NULL,
    arms_json       TEXT NOT NULL CHECK(json_valid(arms_json)),
    order_json      TEXT NOT NULL CHECK(json_valid(order_json)),
    review_json     TEXT CHECK(review_json IS NULL OR json_valid(review_json)),
    reviewed_at     TEXT,
    UNIQUE(evaluation_id,case_key)
);

CREATE TABLE IF NOT EXISTS backup_artifacts (
    id            TEXT PRIMARY KEY,
    kind          TEXT NOT NULL CHECK(kind IN ('daily','weekly','pre-migration','pre-promotion','emergency')),
    path          TEXT NOT NULL UNIQUE,
    sha256        TEXT NOT NULL,
    size_bytes    INTEGER NOT NULL CHECK(size_bytes >= 0),
    verified_at   TEXT NOT NULL,
    protected     INTEGER NOT NULL DEFAULT 0 CHECK(protected IN (0,1)),
    created_at    TEXT NOT NULL
);
"""

MIGRATION_CHECKSUMS = {6: sha256(MIGRATION_V6.encode()).hexdigest()}

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
    meta        TEXT,
    context_json TEXT NOT NULL DEFAULT '{}'
                 CHECK(json_valid(context_json))
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
    external_id     TEXT,
    context_json    TEXT NOT NULL DEFAULT '{}'
                    CHECK(json_valid(context_json)),
    redacted        INTEGER NOT NULL DEFAULT 0 CHECK(redacted IN (0,1)),
    claim_token     TEXT,
    claim_expires_at TEXT
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
    owner_id        TEXT REFERENCES owners(id),
    job_id          TEXT,
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
    kind               TEXT NOT NULL CHECK(length(trim(kind)) BETWEEN 1 AND 64),
    text               TEXT NOT NULL,
    importance         REAL NOT NULL CHECK(importance BETWEEN 0.0 AND 1.0),
    confidence         REAL NOT NULL CHECK(confidence BETWEEN 0.0 AND 1.0),
    status             TEXT NOT NULL
                       CHECK(status IN ('active','archived','expired','superseded')),
    superseded_by      TEXT REFERENCES memories(id),
    valid_from         TEXT NOT NULL,
    valid_until        TEXT,
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL,
    last_retrieved_at  TEXT,
    retrieval_count    INTEGER NOT NULL DEFAULT 0,
    revision           INTEGER NOT NULL DEFAULT 1 CHECK(revision >= 1),
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
                       CHECK(source_role IN ('user','assistant','tool','manual','agent')),
    context_json       TEXT NOT NULL DEFAULT '{}'
                       CHECK(json_valid(context_json) AND json_type(context_json)='object'),
    tags_json          TEXT NOT NULL DEFAULT '[]'
                       CHECK(json_valid(tags_json) AND json_type(tags_json)='array'),
    redacted           INTEGER NOT NULL DEFAULT 0 CHECK(redacted IN (0,1)),
    legacy_imported    INTEGER NOT NULL DEFAULT 0 CHECK(legacy_imported IN (0,1)),
    CHECK(
        length(trim(text)) BETWEEN 1 AND 2000
        OR (legacy_imported=1 AND length(trim(text)) BETWEEN 1 AND 100000)
    )
);
CREATE INDEX IF NOT EXISTS idx_memories_owner ON memories(owner_id, status);
CREATE INDEX IF NOT EXISTS idx_memories_kind ON memories(owner_id, kind, status);

CREATE TABLE IF NOT EXISTS memory_sources (
    memory_id   TEXT NOT NULL REFERENCES memories(id),
    message_id  INTEGER NOT NULL REFERENCES messages(id),
    PRIMARY KEY (memory_id, message_id)
);

CREATE TABLE IF NOT EXISTS memory_evidence (
    memory_id   TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
    message_id  INTEGER NOT NULL REFERENCES messages(id),
    start_char  INTEGER NOT NULL CHECK(start_char >= 0),
    end_char    INTEGER NOT NULL CHECK(end_char > start_char),
    excerpt_sha256 TEXT NOT NULL,
    PRIMARY KEY (memory_id, message_id, start_char, end_char)
);

CREATE TABLE IF NOT EXISTS memory_revisions (
    memory_id          TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
    revision           INTEGER NOT NULL CHECK(revision >= 1),
    kind               TEXT NOT NULL,
    text               TEXT NOT NULL,
    importance         REAL NOT NULL,
    confidence         REAL NOT NULL,
    status             TEXT NOT NULL,
    superseded_by      TEXT,
    valid_until        TEXT,
    extraction_version TEXT NOT NULL,
    judge_run_id       INTEGER,
    source_role        TEXT NOT NULL,
    context_json       TEXT NOT NULL CHECK(json_valid(context_json)),
    tags_json          TEXT NOT NULL CHECK(json_valid(tags_json)),
    redacted           INTEGER NOT NULL CHECK(redacted IN (0,1)),
    created_at         TEXT NOT NULL,
    PRIMARY KEY (memory_id, revision)
);

CREATE TABLE IF NOT EXISTS index_outbox (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    collection    TEXT NOT NULL,
    entity_id     TEXT NOT NULL,
    operation     TEXT NOT NULL CHECK(operation IN ('upsert','delete')),
    payload_json  TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(payload_json)),
    status        TEXT NOT NULL DEFAULT 'pending'
                  CHECK(status IN ('pending','processing','done','failed')),
    attempts      INTEGER NOT NULL DEFAULT 0 CHECK(attempts >= 0),
    available_at  TEXT NOT NULL,
    last_error    TEXT,
    claim_token   TEXT,
    lease_expires_at TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_outbox_pending
    ON index_outbox(status, available_at, id);
CREATE INDEX IF NOT EXISTS idx_outbox_entity_sequence
    ON index_outbox(collection, entity_id, id);

CREATE TABLE IF NOT EXISTS jobs (
    id              TEXT PRIMARY KEY,
    kind            TEXT NOT NULL,
    status          TEXT NOT NULL
                    CHECK(status IN ('queued','running','complete','failed','cancelled')),
    input_json      TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(input_json)),
    result_json     TEXT CHECK(result_json IS NULL OR json_valid(result_json)),
    error_code      TEXT,
    error           TEXT,
    call_limit      INTEGER NOT NULL DEFAULT 0 CHECK(call_limit >= 0),
    calls_completed INTEGER NOT NULL DEFAULT 0 CHECK(calls_completed >= 0),
    cancel_requested INTEGER NOT NULL DEFAULT 0 CHECK(cancel_requested IN (0,1)),
    holder          TEXT,
    lease_expires_at TEXT,
    attempts        INTEGER NOT NULL DEFAULT 0 CHECK(attempts >= 0),
    created_at      TEXT NOT NULL,
    started_at      TEXT,
    finished_at     TEXT,
    updated_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status, created_at);

CREATE TABLE IF NOT EXISTS job_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id      TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    status      TEXT NOT NULL,
    detail_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(detail_json)),
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_job_events_job ON job_events(job_id, id);

CREATE TABLE IF NOT EXISTS leases (
    name        TEXT PRIMARY KEY,
    holder      TEXT NOT NULL,
    expires_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS budget_reservations (
    id              TEXT PRIMARY KEY,
    job_id          TEXT REFERENCES jobs(id),
    period          TEXT NOT NULL,
    reserved_usd    REAL NOT NULL CHECK(reserved_usd >= 0),
    actual_usd      REAL CHECK(actual_usd IS NULL OR actual_usd >= 0),
    status          TEXT NOT NULL CHECK(status IN ('active','reconciled','released')),
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_budget_period ON budget_reservations(period, status);

CREATE TABLE IF NOT EXISTS namespaces (
    id          TEXT PRIMARY KEY,
    owner_id    TEXT NOT NULL REFERENCES owners(id),
    name        TEXT NOT NULL CHECK(length(trim(name)) BETWEEN 1 AND 128),
    description TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    UNIQUE(owner_id, name)
);

CREATE TABLE IF NOT EXISTS collections (
    id              TEXT PRIMARY KEY,
    namespace_id    TEXT NOT NULL REFERENCES namespaces(id) ON DELETE CASCADE,
    name            TEXT NOT NULL CHECK(length(trim(name)) BETWEEN 1 AND 128),
    schema_version  INTEGER NOT NULL DEFAULT 1 CHECK(schema_version >= 1),
    schema_json     TEXT NOT NULL CHECK(json_valid(schema_json)),
    indexed_fields_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(indexed_fields_json)),
    embedding_fields_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(embedding_fields_json)),
    policy_json     TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(policy_json)),
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    UNIQUE(namespace_id, name)
);

CREATE TABLE IF NOT EXISTS records (
    id              TEXT PRIMARY KEY,
    collection_id   TEXT NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    revision        INTEGER NOT NULL DEFAULT 1 CHECK(revision >= 1),
    value_json      TEXT NOT NULL CHECK(json_valid(value_json)),
    metadata_json   TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json)),
    context_json    TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(context_json)),
    status          TEXT NOT NULL DEFAULT 'active'
                    CHECK(status IN ('active','archived','deleted')),
    idempotency_key TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    UNIQUE(collection_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS idx_records_collection
    ON records(collection_id, status, updated_at);

CREATE TABLE IF NOT EXISTS record_revisions (
    record_id      TEXT NOT NULL REFERENCES records(id) ON DELETE CASCADE,
    revision       INTEGER NOT NULL,
    value_json     TEXT NOT NULL CHECK(json_valid(value_json)),
    metadata_json  TEXT NOT NULL CHECK(json_valid(metadata_json)),
    context_json   TEXT NOT NULL CHECK(json_valid(context_json)),
    status         TEXT NOT NULL DEFAULT 'active'
                   CHECK(status IN ('active','archived','deleted')),
    created_at     TEXT NOT NULL,
    PRIMARY KEY(record_id, revision)
);

CREATE TABLE IF NOT EXISTS links (
    id            TEXT PRIMARY KEY,
    namespace_id  TEXT NOT NULL REFERENCES namespaces(id) ON DELETE CASCADE,
    from_ref      TEXT NOT NULL,
    relation      TEXT NOT NULL CHECK(length(trim(relation)) BETWEEN 1 AND 128),
    to_ref        TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json)),
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS policies (
    id          TEXT PRIMARY KEY,
    namespace_id TEXT REFERENCES namespaces(id) ON DELETE CASCADE,
    kind        TEXT NOT NULL CHECK(kind IN ('extraction','retrieval','retention','consolidation')),
    name        TEXT NOT NULL,
    version     INTEGER NOT NULL CHECK(version >= 1),
    config_json TEXT NOT NULL CHECK(json_valid(config_json)),
    created_at  TEXT NOT NULL,
    UNIQUE(namespace_id, kind, name, version)
);

CREATE TABLE IF NOT EXISTS retrieval_feedback (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    memory_id   TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
    query_hash  TEXT NOT NULL,
    useful      INTEGER CHECK(useful IN (0,1)),
    correct     INTEGER CHECK(correct IN (0,1)),
    created_at  TEXT NOT NULL
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
    conn.execute("PRAGMA secure_delete=ON")
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
        has_legacy_data = bool(
            conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='memories'"
            ).fetchone()
        )
        if current == 0 and not has_legacy_data:
            conn.executescript(SCHEMA)
            conn.executescript(MIGRATION_V6)
            _sync_fts(conn)
            _record_migration_history(conn, through=SCHEMA_VERSION)
            _seed_core_policies(conn)
            conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            return

        # Databases from versions 1 and 2 are first normalised to the known v3
        # layout. This keeps the destructive boundary migration single-shaped.
        if current < 2:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS task_board (
                    memory_id TEXT PRIMARY KEY REFERENCES memories(id) ON DELETE CASCADE,
                    workflow_status TEXT NOT NULL,
                    project_key TEXT, position REAL NOT NULL,
                    version INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                """
            )
            _backfill_task_board(conn)
            current = 2
        if current < 3:
            _migrate_source_role(conn)
            current = 3
        if current == 3:
            _backup_and_export_v3(conn, db_path)
            _migrate_v4(conn)
            current = 4
        memory_columns = {row["name"] for row in conn.execute("PRAGMA table_info(memories)")}
        if "kind" in memory_columns and "legacy_imported" not in memory_columns:
            conn.execute(
                "ALTER TABLE memories ADD COLUMN legacy_imported "
                "INTEGER NOT NULL DEFAULT 0 CHECK(legacy_imported IN (0,1))"
            )
        conn.executescript(SCHEMA)
        if current < 5:
            _migrate_v5(conn)
            conn.executescript(SCHEMA)
            current = 5
        if current < 6:
            _assert_database_integrity(conn, stage="before migration v6")
            artifact = _create_pre_migration_backup(conn, db_path, source_version=current)
            conn.executescript(MIGRATION_V6)
            _sync_fts(conn)
            _record_migration_history(conn, through=6)
            conn.execute(
                """INSERT OR IGNORE INTO backup_artifacts
                   (id,kind,path,sha256,size_bytes,verified_at,protected,created_at)
                   VALUES (?,'pre-migration',?,?,?,?,1,?)""",
                (
                    str(uuid.uuid4()),
                    str(artifact["path"]),
                    artifact["sha256"],
                    artifact["size_bytes"],
                    artifact["verified_at"],
                    artifact["created_at"],
                ),
            )
            _assert_database_integrity(conn, stage="after migration v6")
            current = 6
        _verify_migration_history(conn)
        _seed_core_policies(conn)
        conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")


def _assert_database_integrity(conn: sqlite3.Connection, *, stage: str) -> None:
    quick = [str(row[0]) for row in conn.execute("PRAGMA quick_check").fetchall()]
    if quick != ["ok"]:
        raise RuntimeError(f"{stage}: SQLite quick_check failed: {quick[:3]}")
    broken = conn.execute("PRAGMA foreign_key_check").fetchall()
    if broken:
        raise RuntimeError(f"{stage}: SQLite has {len(broken)} foreign-key violations")


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _create_pre_migration_backup(
    conn: sqlite3.Connection, db_path: Path, *, source_version: int
) -> dict[str, object]:
    conn.commit()
    backup_dir = db_path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(backup_dir, 0o700)
    timestamp = utcnow().replace(":", "").replace("-", "")
    path = backup_dir / f"pre-migration-v{source_version}-{timestamp}-{uuid.uuid4().hex[:8]}.db"
    temporary = path.with_suffix(".db.tmp")
    target = sqlite3.connect(temporary)
    try:
        conn.backup(target)
    finally:
        target.close()
    os.chmod(temporary, 0o600)
    check = sqlite3.connect(f"file:{temporary}?mode=ro", uri=True)
    try:
        check.execute("PRAGMA foreign_keys=ON")
        _assert_database_integrity(check, stage="migration backup verification")
    finally:
        check.close()
    temporary.replace(path)
    now = utcnow()
    return {
        "path": path.resolve(),
        "sha256": _file_sha256(path),
        "size_bytes": path.stat().st_size,
        "verified_at": now,
        "created_at": now,
    }


def _sync_fts(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM memories_fts")
    conn.execute(
        """INSERT INTO memories_fts(memory_id,owner_id,text,kind,tags)
           SELECT id,owner_id,text,kind,tags_json FROM memories WHERE status='active'"""
    )


def _record_migration_history(conn: sqlite3.Connection, *, through: int) -> None:
    for version in range(1, through + 1):
        checksum = MIGRATION_CHECKSUMS.get(
            version, sha256(f"legacy-schema-v{version}".encode()).hexdigest()
        )
        conn.execute(
            "INSERT OR IGNORE INTO schema_migrations(version,checksum,applied_at) VALUES (?,?,?)",
            (version, checksum, utcnow()),
        )


def _verify_migration_history(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        "SELECT version,checksum FROM schema_migrations ORDER BY version"
    ).fetchall()
    expected_versions = list(range(1, SCHEMA_VERSION + 1))
    if [int(row["version"]) for row in rows] != expected_versions:
        raise RuntimeError("database migration ledger is incomplete or out of order")
    for row in rows:
        expected = MIGRATION_CHECKSUMS.get(
            int(row["version"]),
            sha256(f"legacy-schema-v{int(row['version'])}".encode()).hexdigest(),
        )
        if row["checksum"] != expected:
            raise RuntimeError(f"database migration {row['version']} checksum mismatch")


def _migrate_v5(conn: sqlite3.Connection) -> None:
    """Add durable claims and immutable revision streams to schema v4."""

    def add(table: str, column: str, declaration: str) -> None:
        columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")

    add("messages", "claim_token", "TEXT")
    add("messages", "claim_expires_at", "TEXT")
    add("memories", "revision", "INTEGER NOT NULL DEFAULT 1 CHECK(revision >= 1)")
    add("index_outbox", "claim_token", "TEXT")
    add("index_outbox", "lease_expires_at", "TEXT")
    add("jobs", "holder", "TEXT")
    add("jobs", "lease_expires_at", "TEXT")
    add("jobs", "attempts", "INTEGER NOT NULL DEFAULT 0 CHECK(attempts >= 0)")
    add(
        "record_revisions",
        "status",
        "TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','archived','deleted'))",
    )
    conn.execute("DROP INDEX IF EXISTS idx_outbox_one_active")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_outbox_entity_sequence "
        "ON index_outbox(collection,entity_id,id)"
    )
    now = utcnow()
    conn.execute(
        """INSERT OR IGNORE INTO memory_revisions
           (memory_id,revision,kind,text,importance,confidence,status,superseded_by,
            valid_until,extraction_version,judge_run_id,source_role,context_json,
            tags_json,redacted,created_at)
           SELECT id,revision,kind,text,importance,confidence,status,superseded_by,
                  valid_until,extraction_version,judge_run_id,source_role,context_json,
                  tags_json,redacted,COALESCE(updated_at,?) FROM memories""",
        (now,),
    )


def _seed_core_policies(conn: sqlite3.Connection) -> None:
    now = utcnow()
    defaults = (
        (
            "core-extraction-v1",
            "extraction",
            "evidence-citations",
            {"require_evidence": True, "max_fact_chars": 200},
        ),
        (
            "core-retrieval-neutral-v1",
            "retrieval",
            "neutral",
            {
                "dense_weight": 0.60,
                "lexical_weight": 0.30,
                "entity_weight": 0.10,
                "importance_weight": 0.10,
                "recency_weight": 0.05,
                "min_relevance": 0.18,
                "allowed_source_roles": ["user", "manual", "tool"],
                "default_half_life_days": 180.0,
            },
        ),
        (
            "core-retention-v1",
            "retention",
            "owner-controlled",
            {"default_expiry": None, "erase_requires_confirmation": True},
        ),
        (
            "core-consolidation-v1",
            "consolidation",
            "context-safe",
            {"same_owner": True, "same_context": True, "automatic_semantic_merge": False},
        ),
    )
    for policy_id, kind, name, config in defaults:
        conn.execute(
            """INSERT OR IGNORE INTO policies
               (id,namespace_id,kind,name,version,config_json,created_at)
               VALUES (?,NULL,?,?,1,?,?)""",
            (policy_id, kind, name, json.dumps(config, sort_keys=True), now),
        )


def _backup_and_export_v3(conn: sqlite3.Connection, db_path: Path) -> None:
    """Create recoverable v3 artifacts before retiring the task aggregate."""
    conn.commit()
    identity_payload = {
        "database": str(db_path.resolve()),
        "owners": conn.execute("SELECT COUNT(*) FROM owners").fetchone()[0],
        "sessions": conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0],
        "messages": conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0],
        "memories": conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0],
        "task_ids": [
            row[0]
            for row in conn.execute(
                "SELECT memory_id FROM task_board ORDER BY memory_id"
            ).fetchall()
        ],
    }
    source_identity = sha256(json.dumps(identity_payload, sort_keys=True).encode()).hexdigest()[:16]
    backup_path = db_path.with_name(f"{db_path.name}.v3-{source_identity}.bak")
    if not backup_path.exists():
        temporary = backup_path.with_suffix(f"{backup_path.suffix}.tmp")
        backup_conn = sqlite3.connect(temporary)
        try:
            conn.backup(backup_conn)
        finally:
            backup_conn.close()
        temporary.replace(backup_path)

    task_table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='task_board'"
    ).fetchone()
    tasks: list[dict[str, object]] = []
    if task_table:
        rows = conn.execute(
            """SELECT tb.*, m.text, m.valid_until AS due_at, m.status AS memory_status,
                      m.source_role, m.judge_run_id
                 FROM task_board tb JOIN memories m ON m.id=tb.memory_id
                ORDER BY tb.position, tb.memory_id"""
        ).fetchall()
        tasks = [dict(row) for row in rows]
        for task in tasks:
            task["source_message_ids"] = [
                int(row[0])
                for row in conn.execute(
                    "SELECT message_id FROM memory_sources WHERE memory_id=? ORDER BY message_id",
                    (task["memory_id"],),
                ).fetchall()
            ]
    export_dir = db_path.parent / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    export_path = export_dir / f"task-board-v3-{source_identity}.json"
    if not export_path.exists():
        temporary = export_path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(
                {
                    "schema_version": 3,
                    "exported_at": utcnow(),
                    "source_database": db_path.name,
                    "source_identity": source_identity,
                    "tasks": tasks,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        temporary.replace(export_path)


def _migrate_v4(conn: sqlite3.Connection) -> None:
    """Replace the closed task/scope ontology with domain-neutral memory fields."""
    old_columns = {row["name"] for row in conn.execute("PRAGMA table_info(memories)")}
    if "kind" in old_columns:
        return
    rows = conn.execute("SELECT * FROM memories ORDER BY created_at, id").fetchall()

    conn.commit()
    conn.execute("PRAGMA foreign_keys=OFF")
    try:
        conn.execute("BEGIN")
        conn.execute(
            """CREATE TABLE memories_v4 (
                id TEXT PRIMARY KEY,
                owner_id TEXT NOT NULL REFERENCES owners(id),
                agent_id TEXT,
                kind TEXT NOT NULL CHECK(length(trim(kind)) BETWEEN 1 AND 64),
                text TEXT NOT NULL,
                importance REAL NOT NULL CHECK(importance BETWEEN 0.0 AND 1.0),
                confidence REAL NOT NULL CHECK(confidence BETWEEN 0.0 AND 1.0),
                status TEXT NOT NULL CHECK(status IN ('active','archived','expired','superseded')),
                superseded_by TEXT REFERENCES memories_v4(id),
                valid_from TEXT NOT NULL,
                valid_until TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_retrieved_at TEXT,
                retrieval_count INTEGER NOT NULL DEFAULT 0 CHECK(retrieval_count >= 0),
                extraction_version TEXT NOT NULL,
                judge_run_id INTEGER REFERENCES judge_runs(id),
                source_role TEXT NOT NULL
                    CHECK(source_role IN ('user','assistant','tool','manual','agent')),
                context_json TEXT NOT NULL DEFAULT '{}'
                    CHECK(json_valid(context_json) AND json_type(context_json)='object'),
                tags_json TEXT NOT NULL DEFAULT '[]'
                    CHECK(json_valid(tags_json) AND json_type(tags_json)='array'),
                redacted INTEGER NOT NULL DEFAULT 0 CHECK(redacted IN (0,1)),
                legacy_imported INTEGER NOT NULL DEFAULT 1
                    CHECK(legacy_imported IN (0,1)),
                CHECK(
                    length(trim(text)) BETWEEN 1 AND 2000
                    OR (legacy_imported=1 AND length(trim(text)) BETWEEN 1 AND 100000)
                )
            )"""
        )
        for row in rows:
            retired_domain = row["type"] == "task" or row["scope"] == "task"
            context: dict[str, str] = {}
            if row["scope"] == "project" and row["scope_key"]:
                context["source_workspace"] = row["scope_key"]
            kind = "observation" if retired_domain else row["type"]
            status = "archived" if retired_domain else row["status"]
            valid_until = None if retired_domain else row["valid_until"]
            tags = ["retired-domain-record"] if retired_domain else []
            conn.execute(
                """INSERT INTO memories_v4
                   (id,owner_id,agent_id,kind,text,importance,confidence,status,
                    superseded_by,valid_from,valid_until,created_at,updated_at,
                    last_retrieved_at,retrieval_count,extraction_version,judge_run_id,
                    source_role,context_json,tags_json,redacted,legacy_imported)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,1)""",
                (
                    row["id"],
                    row["owner_id"],
                    row["agent_id"],
                    kind,
                    row["text"],
                    row["importance"],
                    row["confidence"],
                    status,
                    row["superseded_by"],
                    row["valid_from"],
                    valid_until,
                    row["created_at"],
                    row["updated_at"],
                    row["last_retrieved_at"],
                    row["retrieval_count"],
                    row["extraction_version"],
                    row["judge_run_id"],
                    row["source_role"],
                    json.dumps(context, ensure_ascii=False, sort_keys=True),
                    json.dumps(tags, ensure_ascii=False),
                ),
            )
        conn.execute("DROP TABLE IF EXISTS task_board")
        conn.execute("DROP TABLE memories")
        conn.execute("ALTER TABLE memories_v4 RENAME TO memories")
        if "context_json" not in {
            row["name"] for row in conn.execute("PRAGMA table_info(sessions)")
        }:
            conn.execute("ALTER TABLE sessions ADD COLUMN context_json TEXT NOT NULL DEFAULT '{}'")
            conn.execute("UPDATE sessions SET context_json=COALESCE(meta, '{}')")
        message_columns = {row["name"] for row in conn.execute("PRAGMA table_info(messages)")}
        if "context_json" not in message_columns:
            conn.execute("ALTER TABLE messages ADD COLUMN context_json TEXT NOT NULL DEFAULT '{}'")
        if "redacted" not in message_columns:
            conn.execute("ALTER TABLE messages ADD COLUMN redacted INTEGER NOT NULL DEFAULT 0")
        judge_columns = {row["name"] for row in conn.execute("PRAGMA table_info(judge_runs)")}
        if "owner_id" not in judge_columns:
            conn.execute("ALTER TABLE judge_runs ADD COLUMN owner_id TEXT REFERENCES owners(id)")
        if "job_id" not in judge_columns:
            conn.execute("ALTER TABLE judge_runs ADD COLUMN job_id TEXT")
        broken = conn.execute("PRAGMA foreign_key_check").fetchall()
        if broken:
            raise RuntimeError(f"v4 migration left {len(broken)} dangling references")
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.execute("PRAGMA foreign_keys=ON")


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
    "CREATE INDEX IF NOT EXISTS idx_memories_scope ON memories(owner_id, scope, scope_key)",
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
        "INSERT INTO owners (id, name, created_at) VALUES (?, ?, ?) ON CONFLICT(id) DO NOTHING",
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
                with suppress(sqlite3.Error):
                    conn.close()
            self._opened.clear()
        self._local = threading.local()
