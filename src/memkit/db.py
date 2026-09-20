"""Postgres access. This is the source of truth; Qdrant is derived from it.

Schema version 1 is a fresh start, not a port of the SQLite ladder. The old
database was single-owner by construction: one `owners` row, an `owner_id` on
every table, and no way for a request to name a different one. Every table here
is multi-tenant from the first migration instead, because retrofitting tenancy
onto a schema is how isolation bugs are made -- a query that forgets the
predicate still returns rows.

Two identifiers carry that tenancy, and the distinction between them is the
whole model:

    scope_id    the entity whose space holds this row. The authorization
                boundary: a request may only read scopes its principal belongs
                to, and asking for another is refused rather than filtered.
    subject_id  the entity a fact is *about*. Attribution, not permission.
                NULL means the fact is about the scope itself.

A user's private memory is a scope whose entity is that user. A fact about a
teammate lives in the team scope with the teammate as subject, so the team can
see it and the teammate can delete it. Nothing else needs a new namespace.

Existing SQLite data is imported once by `memkit import-sqlite`, which is the
only module still allowed to touch sqlite3.
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool as _PsycopgPool

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 2

DDL_V1 = """
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version     integer PRIMARY KEY,
    checksum    text NOT NULL,
    applied_at  timestamptz NOT NULL DEFAULT now()
);

-- People. A user is not an entity, but every user has one (see entities).
CREATE TABLE IF NOT EXISTS users (
    id             uuid PRIMARY KEY,
    handle         text NOT NULL UNIQUE
                   CHECK (handle ~ '^[a-z0-9][a-z0-9_.-]{1,62}$'),
    display_name   text NOT NULL CHECK (length(btrim(display_name)) BETWEEN 1 AND 200),
    email          text UNIQUE,
    password_hash  text NOT NULL,
    role           text NOT NULL CHECK (role IN ('admin','member')),
    created_at     timestamptz NOT NULL DEFAULT now(),
    disabled_at    timestamptz
);

-- Agents and hooks authenticate with these; the dashboard uses auth_sessions.
-- Only the hash is stored, so a leaked database cannot be used to call the API.
CREATE TABLE IF NOT EXISTS api_keys (
    id            uuid PRIMARY KEY,
    user_id       uuid NOT NULL REFERENCES users ON DELETE CASCADE,
    name          text NOT NULL CHECK (length(btrim(name)) BETWEEN 1 AND 200),
    key_prefix    text NOT NULL UNIQUE,
    key_hash      text NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now(),
    last_used_at  timestamptz,
    revoked_at    timestamptz
);
CREATE INDEX IF NOT EXISTS api_keys_user ON api_keys(user_id);

CREATE TABLE IF NOT EXISTS auth_sessions (
    id            uuid PRIMARY KEY,
    user_id       uuid NOT NULL REFERENCES users ON DELETE CASCADE,
    token_hash    text NOT NULL UNIQUE,
    created_at    timestamptz NOT NULL DEFAULT now(),
    expires_at    timestamptz NOT NULL,
    last_seen_at  timestamptz,
    ip            inet,
    user_agent    text,
    revoked_at    timestamptz
);
CREATE INDEX IF NOT EXISTS auth_sessions_user ON auth_sessions(user_id);

-- Everything a memory can belong to or be about: a person, the team, a product,
-- a company, a project. `kind='user'` rows are created with their user and are
-- that user's private space.
CREATE TABLE IF NOT EXISTS entities (
    id           uuid PRIMARY KEY,
    kind         text NOT NULL
                 CHECK (kind IN ('user','team','project','product','company','person','custom')),
    name         text NOT NULL CHECK (length(btrim(name)) BETWEEN 1 AND 200),
    slug         text NOT NULL UNIQUE CHECK (slug ~ '^[a-z0-9][a-z0-9_-]{0,62}$'),
    description  text NOT NULL DEFAULT '',
    visibility   text NOT NULL DEFAULT 'members' CHECK (visibility IN ('members','team')),
    user_id      uuid UNIQUE REFERENCES users ON DELETE CASCADE,
    created_by   uuid REFERENCES users,
    created_at   timestamptz NOT NULL DEFAULT now(),
    archived_at  timestamptz,
    CHECK ((kind = 'user') = (user_id IS NOT NULL))
);
-- Exactly one team entity: it is the shared scope every user belongs to.
CREATE UNIQUE INDEX IF NOT EXISTS entities_single_team ON entities((kind)) WHERE kind = 'team';

-- Alternate names the extractor may see in conversation ("Саша", "the shop").
-- Normalised for case-insensitive lookup in either language.
CREATE TABLE IF NOT EXISTS entity_aliases (
    entity_id   uuid NOT NULL REFERENCES entities ON DELETE CASCADE,
    alias_norm  text PRIMARY KEY CHECK (length(btrim(alias_norm)) BETWEEN 1 AND 200),
    alias       text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS entity_aliases_entity ON entity_aliases(entity_id);

CREATE TABLE IF NOT EXISTS memberships (
    entity_id   uuid NOT NULL REFERENCES entities ON DELETE CASCADE,
    user_id     uuid NOT NULL REFERENCES users ON DELETE CASCADE,
    role        text NOT NULL CHECK (role IN ('owner','member','viewer')),
    created_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (entity_id, user_id)
);
CREATE INDEX IF NOT EXISTS memberships_user ON memberships(user_id);

CREATE TABLE IF NOT EXISTS sessions (
    id          text PRIMARY KEY,
    user_id     uuid NOT NULL REFERENCES users,
    scope_id    uuid NOT NULL REFERENCES entities,
    agent_id    text NOT NULL,
    started_at  timestamptz NOT NULL DEFAULT now(),
    ended_at    timestamptz,
    context     jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(context) = 'object')
);
CREATE INDEX IF NOT EXISTS sessions_user ON sessions(user_id, started_at DESC);

-- Raw evidence. Never deleted except by erasure: every extractor prompt rewrite
-- must be able to replay the entire history. `user_id` is denormalised so an
-- isolation check never depends on remembering to join sessions.
CREATE TABLE IF NOT EXISTS messages (
    id                bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    session_id        text NOT NULL REFERENCES sessions,
    user_id           uuid NOT NULL REFERENCES users,
    role              text NOT NULL CHECK (role IN ('user','assistant','tool')),
    content           text NOT NULL,
    created_at        timestamptz NOT NULL,
    processed         boolean NOT NULL DEFAULT false,
    external_source   text,
    external_id       text,
    context           jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(context) = 'object'),
    redacted          boolean NOT NULL DEFAULT false,
    claim_token       text,
    claim_expires_at  timestamptz
);
CREATE INDEX IF NOT EXISTS messages_session ON messages(session_id, id);
CREATE INDEX IF NOT EXISTS messages_unprocessed ON messages(session_id, id)
    WHERE NOT processed;
-- Idempotency for every writer that can replay. Scoped by user because two
-- people on one machine would otherwise collide on transcript line ids.
CREATE UNIQUE INDEX IF NOT EXISTS messages_external
    ON messages(user_id, external_source, external_id) WHERE external_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS judge_runs (
    id              bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    user_id         uuid REFERENCES users,
    job_id          uuid,
    kind            text NOT NULL,
    model           text NOT NULL,
    prompt_version  text NOT NULL,
    input           jsonb NOT NULL,
    output          jsonb,
    error           text,
    input_tokens    integer,
    output_tokens   integer,
    cost_usd        numeric(12,6),
    latency_ms      integer,
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS judge_runs_created ON judge_runs(created_at);
CREATE INDEX IF NOT EXISTS judge_runs_user ON judge_runs(user_id, created_at);

CREATE TABLE IF NOT EXISTS memories (
    id                  uuid PRIMARY KEY,
    scope_id            uuid NOT NULL REFERENCES entities,
    subject_id          uuid REFERENCES entities,
    author_id           uuid NOT NULL REFERENCES users,
    agent_id            text,
    kind                text NOT NULL CHECK (length(btrim(kind)) BETWEEN 1 AND 64),
    text                text NOT NULL,
    importance          real NOT NULL CHECK (importance BETWEEN 0 AND 1),
    confidence          real NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    status              text NOT NULL
                        CHECK (status IN ('active','archived','expired','superseded')),
    superseded_by       uuid REFERENCES memories,
    valid_from          timestamptz NOT NULL,
    valid_until         timestamptz,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now(),
    last_retrieved_at   timestamptz,
    retrieval_count     integer NOT NULL DEFAULT 0,
    revision            integer NOT NULL DEFAULT 1 CHECK (revision >= 1),
    extraction_version  text NOT NULL,
    judge_run_id        bigint REFERENCES judge_runs,
    -- Who the claim came from: the highest-authority role among the messages
    -- this fact cites, or 'manual' when it cites none and the caller asserted
    -- it. Deliberately no default: an INSERT that forgets this column must
    -- fail rather than label model-authored text as something a human typed.
    source_role         text NOT NULL
                        CHECK (source_role IN ('user','assistant','tool','manual','agent')),
    -- Every automatic write starts unconfirmed and is fully usable anyway; the
    -- dashboard confirms or deletes. A user's own manual save is confirmed on
    -- arrival, because they just said it.
    review_status       text NOT NULL DEFAULT 'pending'
                        CHECK (review_status IN ('pending','confirmed','declined')),
    reviewed_by         uuid REFERENCES users,
    reviewed_at         timestamptz,
    -- sha256 of the normalised text, for exact-duplicate rejection on write.
    content_hash        text NOT NULL,
    context             jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(context) = 'object'),
    tags                jsonb NOT NULL DEFAULT '[]' CHECK (jsonb_typeof(tags) = 'array'),
    redacted            boolean NOT NULL DEFAULT false,
    legacy_imported     boolean NOT NULL DEFAULT false,
    -- Case folding is pinned to ICU rather than left to the database's ctype.
    -- Under the C locale Postgres folds ASCII and leaves Cyrillic alone, so
    -- `ПРЕДПОЧИТАЕТ` never matched a query for `предпочитает` -- which is every
    -- sentence-initial word and every name. Nothing in a connection string
    -- says which locale a database was created with, so the schema states it.
    text_folded         text GENERATED ALWAYS AS (lower(text COLLATE "und-x-icu")) STORED,
    -- The 'russian' configuration stems Cyrillic with russian_stem and ASCII
    -- with english_stem, so one column covers both languages. SQLite's FTS5
    -- tokenizer had no stemming at all, which left the lexical arm blind to
    -- Russian morphology.
    search_tsv          tsvector GENERATED ALWAYS AS
                        (to_tsvector('russian', lower(text COLLATE "und-x-icu"))) STORED,
    CHECK (
        length(btrim(text)) BETWEEN 1 AND 2000
        OR (legacy_imported AND length(btrim(text)) BETWEEN 1 AND 100000)
    )
);
CREATE INDEX IF NOT EXISTS memories_scope
    ON memories(scope_id, status, importance DESC, updated_at DESC);
CREATE INDEX IF NOT EXISTS memories_scope_kind ON memories(scope_id, kind, status);
CREATE INDEX IF NOT EXISTS memories_subject ON memories(subject_id)
    WHERE subject_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS memories_pending ON memories(scope_id, created_at)
    WHERE review_status = 'pending' AND status = 'active';
CREATE INDEX IF NOT EXISTS memories_hash ON memories(scope_id, content_hash);
CREATE INDEX IF NOT EXISTS memories_updated ON memories(scope_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS memories_author ON memories(author_id);
CREATE INDEX IF NOT EXISTS memories_tsv ON memories USING gin (search_tsv)
    WHERE status = 'active';
CREATE INDEX IF NOT EXISTS memories_trgm ON memories USING gin (text_folded gin_trgm_ops)
    WHERE status = 'active';

CREATE TABLE IF NOT EXISTS memory_revisions (
    memory_id           uuid NOT NULL REFERENCES memories ON DELETE CASCADE,
    revision            integer NOT NULL CHECK (revision >= 1),
    scope_id            uuid NOT NULL,
    subject_id          uuid,
    author_id           uuid NOT NULL,
    kind                text NOT NULL,
    text                text NOT NULL,
    importance          real NOT NULL,
    confidence          real NOT NULL,
    status              text NOT NULL,
    superseded_by       uuid,
    valid_until         timestamptz,
    extraction_version  text NOT NULL,
    judge_run_id        bigint,
    source_role         text NOT NULL,
    review_status       text NOT NULL,
    context             jsonb NOT NULL,
    tags                jsonb NOT NULL,
    redacted            boolean NOT NULL,
    created_at          timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (memory_id, revision)
);

CREATE TABLE IF NOT EXISTS memory_sources (
    memory_id   uuid NOT NULL REFERENCES memories ON DELETE CASCADE,
    message_id  bigint NOT NULL REFERENCES messages,
    PRIMARY KEY (memory_id, message_id)
);

CREATE TABLE IF NOT EXISTS memory_evidence (
    memory_id       uuid NOT NULL REFERENCES memories ON DELETE CASCADE,
    message_id      bigint NOT NULL REFERENCES messages,
    start_char      integer NOT NULL CHECK (start_char >= 0),
    end_char        integer NOT NULL CHECK (end_char > start_char),
    excerpt_sha256  text NOT NULL,
    PRIMARY KEY (memory_id, message_id, start_char, end_char)
);

-- Work the dashboard surfaces as "needs attention". Pending memories are not
-- duplicated here: they are found by memories.review_status.
CREATE TABLE IF NOT EXISTS needs_attention (
    id             uuid PRIMARY KEY,
    user_id        uuid NOT NULL REFERENCES users ON DELETE CASCADE,
    scope_id       uuid REFERENCES entities ON DELETE CASCADE,
    kind           text NOT NULL
                   CHECK (kind IN ('unresolved_mention','conflict','failed_job','budget')),
    ref_memory_id  uuid REFERENCES memories ON DELETE CASCADE,
    ref_job_id     uuid,
    payload        jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(payload) = 'object'),
    status         text NOT NULL DEFAULT 'open' CHECK (status IN ('open','resolved')),
    created_at     timestamptz NOT NULL DEFAULT now(),
    resolved_at    timestamptz,
    resolved_by    uuid REFERENCES users
);
CREATE INDEX IF NOT EXISTS needs_attention_open
    ON needs_attention(user_id, status, created_at DESC);

CREATE TABLE IF NOT EXISTS index_outbox (
    id                bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    collection        text NOT NULL,
    entity_id         text NOT NULL,
    operation         text NOT NULL CHECK (operation IN ('upsert','delete')),
    payload           jsonb NOT NULL DEFAULT '{}',
    status            text NOT NULL DEFAULT 'pending'
                      CHECK (status IN ('pending','processing','done','failed')),
    attempts          integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    available_at      timestamptz NOT NULL DEFAULT now(),
    last_error        text,
    claim_token       text,
    lease_expires_at  timestamptz,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS outbox_pending ON index_outbox(status, available_at, id);
CREATE INDEX IF NOT EXISTS outbox_entity_sequence ON index_outbox(collection, entity_id, id);

CREATE TABLE IF NOT EXISTS jobs (
    id                uuid PRIMARY KEY,
    user_id           uuid REFERENCES users,
    kind              text NOT NULL,
    status            text NOT NULL
                      CHECK (status IN ('queued','running','complete','failed','cancelled')),
    input             jsonb NOT NULL DEFAULT '{}',
    result            jsonb,
    error_code        text,
    error             text,
    call_limit        integer NOT NULL DEFAULT 0 CHECK (call_limit >= 0),
    calls_completed   integer NOT NULL DEFAULT 0 CHECK (calls_completed >= 0),
    cancel_requested  boolean NOT NULL DEFAULT false,
    holder            text,
    lease_expires_at  timestamptz,
    attempts          integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    created_at        timestamptz NOT NULL DEFAULT now(),
    started_at        timestamptz,
    finished_at       timestamptz,
    updated_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS jobs_status ON jobs(status, created_at);

CREATE TABLE IF NOT EXISTS job_events (
    id          bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    job_id      uuid NOT NULL REFERENCES jobs ON DELETE CASCADE,
    status      text NOT NULL,
    detail      jsonb NOT NULL DEFAULT '{}',
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS job_events_job ON job_events(job_id, id);

CREATE TABLE IF NOT EXISTS leases (
    name        text PRIMARY KEY,
    holder      text NOT NULL,
    expires_at  timestamptz NOT NULL,
    updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS budget_reservations (
    id            uuid PRIMARY KEY,
    job_id        uuid REFERENCES jobs,
    user_id       uuid REFERENCES users,
    period        text NOT NULL,
    reserved_usd  numeric(12,6) NOT NULL CHECK (reserved_usd >= 0),
    actual_usd    numeric(12,6) CHECK (actual_usd IS NULL OR actual_usd >= 0),
    status        text NOT NULL CHECK (status IN ('active','reconciled','released')),
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS budget_period ON budget_reservations(period, status);

CREATE TABLE IF NOT EXISTS policies (
    id          text PRIMARY KEY,
    scope_id    uuid REFERENCES entities ON DELETE CASCADE,
    kind        text NOT NULL
                CHECK (kind IN ('extraction','retrieval','retention','consolidation')),
    name        text NOT NULL,
    version     integer NOT NULL CHECK (version >= 1),
    config      jsonb NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (scope_id, kind, name, version)
);

CREATE TABLE IF NOT EXISTS retrieval_runs (
    id           uuid PRIMARY KEY,
    user_id      uuid REFERENCES users ON DELETE CASCADE,
    query_hash   text NOT NULL,
    policy_id    text NOT NULL,
    results      jsonb NOT NULL DEFAULT '[]',
    timings      jsonb NOT NULL DEFAULT '{}',
    used_tokens  integer NOT NULL DEFAULT 0,
    abstained    boolean NOT NULL DEFAULT false,
    created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS retrieval_runs_created ON retrieval_runs(created_at);

CREATE TABLE IF NOT EXISTS retrieval_run_feedback (
    id          bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    run_id      uuid NOT NULL REFERENCES retrieval_runs ON DELETE CASCADE,
    memory_id   uuid,
    useful      boolean,
    correct     boolean,
    label       text,
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS retrieval_run_feedback_run ON retrieval_run_feedback(run_id);

CREATE TABLE IF NOT EXISTS retrieval_feedback (
    id          bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    memory_id   uuid NOT NULL REFERENCES memories ON DELETE CASCADE,
    query_hash  text NOT NULL,
    useful      boolean,
    correct     boolean,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS backup_artifacts (
    id           uuid PRIMARY KEY,
    path         text NOT NULL,
    kind         text NOT NULL,
    sha256       text NOT NULL,
    bytes        bigint NOT NULL CHECK (bytes >= 0),
    protected    boolean NOT NULL DEFAULT false,
    created_at   timestamptz NOT NULL DEFAULT now(),
    verified_at  timestamptz
);
"""

DDL_V2 = """
ALTER TABLE jobs ADD COLUMN available_at timestamptz NOT NULL DEFAULT now();
CREATE TABLE memory_revision_evidence (
    memory_id uuid NOT NULL,
    revision integer NOT NULL,
    message_id bigint NOT NULL,
    start_char integer NOT NULL,
    end_char integer NOT NULL,
    PRIMARY KEY (memory_id, revision, message_id, start_char, end_char),
    FOREIGN KEY (memory_id, revision)
        REFERENCES memory_revisions(memory_id, revision) ON DELETE CASCADE,
    FOREIGN KEY (memory_id, message_id, start_char, end_char)
        REFERENCES memory_evidence(memory_id, message_id, start_char, end_char) ON DELETE CASCADE
);
"""

MIGRATIONS: dict[int, str] = {1: DDL_V1, 2: DDL_V2}
MIGRATION_CHECKSUMS = {
    version: sha256(ddl.encode()).hexdigest() for version, ddl in MIGRATIONS.items()
}

# Timestamps are `timestamptz` and come back as aware datetimes. Callers that
# put one in JSON use `iso`.
_ISO_Z = "%Y-%m-%dT%H:%M:%SZ"


def utcnow() -> datetime:
    """Now, at full precision.

    The SQLite build truncated this to whole seconds because timestamps were
    ISO text and comparisons were lexicographic. `timestamptz` keeps
    microseconds, and the precision is load-bearing: `updated_at` orders the
    dashboard's recent list and two writes in one second used to tie, leaving
    the order to fall back on a random uuid. `iso` still renders to the second,
    so API output is unchanged.
    """
    return datetime.now(UTC)


def iso(value: datetime | str | None) -> str | None:
    """ISO-8601 UTC with a trailing Z, for JSON and for API responses."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return value.astimezone(UTC).replace(microsecond=0).strftime(_ISO_Z)


def as_datetime(value: datetime | str | None) -> datetime | None:
    """Accept either shape; return an aware datetime.

    Clients send ISO strings and the database returns datetimes, so the write
    paths take both rather than making every caller convert.
    """
    if value is None or isinstance(value, datetime):
        return value.astimezone(UTC) if isinstance(value, datetime) and value.tzinfo else value
    text = value.strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


class Row(dict[str, Any]):
    """A result row that also supports positional access.

    The codebase reads rows three ways -- `row["column"]`, `row[0]`, and
    `dict(row)` -- because sqlite3.Row supported all three. Keeping that
    contract means the port does not have to touch every read site.
    """

    __slots__ = ()

    def __getitem__(self, key: Any) -> Any:
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)

    def keys(self) -> Any:  # type: ignore[override]
        return super().keys()


def _row_factory(cursor: Any) -> Any:
    make = dict_row(cursor)

    def build(values: Sequence[Any]) -> Row:
        return Row(make(values))

    return build


def connect(dsn: str) -> psycopg.Connection:
    """One connection, autocommit, dict-like rows.

    Autocommit is the default because most reads are single statements; a unit
    of work is an explicit `transaction()` block.
    """
    conn = psycopg.connect(dsn, autocommit=True, row_factory=_row_factory)
    conn.execute("SET lock_timeout = '5s'")
    conn.execute("SET idle_in_transaction_session_timeout = '60s'")
    return conn


@contextmanager
def transaction(conn: psycopg.Connection) -> Iterator[psycopg.Connection]:
    """Commit on success, roll back on failure.

    Kept as a wrapper with the old name and shape so the sixty-odd call sites
    that use it do not move. Nested use is safe: psycopg opens a savepoint.
    """
    with conn.transaction():
        yield conn


def advisory_lock(conn: psycopg.Connection, name: str) -> None:
    """Serialise a critical section across processes for this transaction.

    Replaces SQLite's `BEGIN IMMEDIATE`, which serialised writers by taking the
    whole database, and the file lock the outbox used as an owner barrier. Must
    be called inside a transaction: the lock is released when it ends.
    """
    conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (name,))


class ConnectionPool:
    """Borrow one connection per request or worker operation, then return it.

    A borrow owns a resource, not a transaction. Callers retain short explicit
    transactions, and provider calls must run outside those transactions.
    """

    def __init__(self, dsn: str, *, max_size: int = 10) -> None:
        self.dsn = dsn
        self._pool = _PsycopgPool(
            dsn,
            min_size=1,
            max_size=max_size,
            kwargs={"autocommit": True, "row_factory": _row_factory},
            configure=self._configure,
            open=True,
            name="memkit",
        )

    @staticmethod
    def _configure(conn: psycopg.Connection) -> None:
        conn.execute("SET lock_timeout = '5s'")
        conn.execute("SET idle_in_transaction_session_timeout = '60s'")

    @contextmanager
    def borrow(self) -> Iterator[psycopg.Connection]:
        """A connection for one short piece of work, returned immediately."""
        with self._pool.connection() as conn:
            yield conn

    def close_all(self) -> None:
        """Shutdown only."""
        self._pool.close()


def _require_icu(conn: psycopg.Connection) -> None:
    """Refuse a database that cannot fold case the way the schema assumes.

    The searchable columns are generated with an explicit ICU collation, so a
    build without ICU would fail at DDL time with a message about a missing
    collation rather than about search. Checked first, and named, because the
    failure it prevents is silent: half the corpus becomes unfindable and
    nothing errors.
    """
    row = conn.execute(
        "SELECT lower('ПРЕДПОЧИТАЕТ' COLLATE \"und-x-icu\") = 'предпочитает' AS ok"
    ).fetchone()
    if row is None or not row["ok"]:
        raise RuntimeError(
            "this PostgreSQL build cannot case-fold Cyrillic with the und-x-icu "
            "collation, which the memories search columns require. Use a build "
            "with ICU support (the official postgres images have it)."
        )


def init_db(dsn: str) -> None:
    """Create or verify the schema. Safe to call from every process at once."""
    with connect(dsn) as conn:
        _require_icu(conn)
        with conn.transaction():
            # Two containers starting together must not both run the DDL.
            conn.execute("SELECT pg_advisory_xact_lock(hashtext('memkit:migrate'))")
            applied = _applied_versions(conn)
            if applied and max(applied) > SCHEMA_VERSION:
                raise RuntimeError(
                    f"database schema {max(applied)} is newer than supported {SCHEMA_VERSION}"
                )
            for version in sorted(MIGRATIONS):
                if version in applied:
                    continue
                logger.info("applying schema migration %s", version)
                conn.execute(MIGRATIONS[version])
                conn.execute(
                    "INSERT INTO schema_migrations(version,checksum) VALUES (%s,%s)",
                    (version, MIGRATION_CHECKSUMS[version]),
                )
            _verify_migration_history(conn)
        with conn.transaction():
            _seed_core_policies(conn)


def _applied_versions(conn: psycopg.Connection) -> set[int]:
    exists = conn.execute("SELECT to_regclass('schema_migrations') IS NOT NULL AS ok").fetchone()
    if not exists or not exists["ok"]:
        return set()
    return {int(row["version"]) for row in conn.execute("SELECT version FROM schema_migrations")}


def _verify_migration_history(conn: psycopg.Connection) -> None:
    """The ledger must hold every version in order, with matching checksums.

    An edited migration is a different migration, and a database that skipped
    one is not the schema this code expects. Both are startup failures rather
    than a surprise at the first query.
    """
    rows = list(conn.execute("SELECT version,checksum FROM schema_migrations ORDER BY version"))
    versions = [int(row["version"]) for row in rows]
    if versions != list(range(1, SCHEMA_VERSION + 1)):
        raise RuntimeError(f"migration history is not contiguous: {versions}")
    for row in rows:
        expected = MIGRATION_CHECKSUMS[int(row["version"])]
        if row["checksum"] != expected:
            raise RuntimeError(
                f"migration {row['version']} checksum mismatch: the applied migration "
                "differs from the one in this build"
            )


def _seed_core_policies(conn: psycopg.Connection) -> None:
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
            "scope-controlled",
            {"default_expiry": None, "erase_requires_confirmation": True},
        ),
        (
            "core-consolidation-v1",
            "consolidation",
            "context-safe",
            {"same_scope": True, "same_context": True, "automatic_semantic_merge": False},
        ),
    )
    for policy_id, kind, name, config in defaults:
        conn.execute(
            """INSERT INTO policies (id,scope_id,kind,name,version,config)
               VALUES (%s,NULL,%s,%s,1,%s) ON CONFLICT (id) DO NOTHING""",
            (policy_id, kind, name, json.dumps(config, sort_keys=True)),
        )


def reset_schema(conn: psycopg.Connection) -> None:
    """Drop and recreate everything. Test setup and `memkit erase --all` only."""
    conn.execute("DROP SCHEMA public CASCADE")
    conn.execute("CREATE SCHEMA public")


def truncate_all(conn: psycopg.Connection) -> None:
    """Empty every table, keeping the schema. Test teardown.

    Faster than recreating the schema per test, and identity sequences restart
    so tests that assert on message ids stay deterministic.
    """
    rows = conn.execute(
        """SELECT tablename FROM pg_tables
            WHERE schemaname='public' AND tablename <> 'schema_migrations'"""
    ).fetchall()
    if not rows:
        return
    names = sql.SQL(", ").join(sql.Identifier(str(row["tablename"])) for row in rows)
    conn.execute(sql.SQL("TRUNCATE {} RESTART IDENTITY CASCADE").format(names))
    _seed_core_policies(conn)


_SLUG_RE = re.compile(r"[^a-z0-9]+")

# Slugs are ASCII because they appear in URLs and in the prompt's entity block.
# Without transliteration every Cyrillic name collapsed to the fallback, so a
# team writing Russian would get "entity-1", "entity-2" for its own people.
_TRANSLITERATE = str.maketrans(
    {
        "а": "a",
        "б": "b",
        "в": "v",
        "г": "g",
        "д": "d",
        "е": "e",
        "ё": "e",
        "ж": "zh",
        "з": "z",
        "и": "i",
        "й": "y",
        "к": "k",
        "л": "l",
        "м": "m",
        "н": "n",
        "о": "o",
        "п": "p",
        "р": "r",
        "с": "s",
        "т": "t",
        "у": "u",
        "ф": "f",
        "х": "kh",
        "ц": "ts",
        "ч": "ch",
        "ш": "sh",
        "щ": "shch",
        "ъ": "",
        "ы": "y",
        "ь": "",
        "э": "e",
        "ю": "yu",
        "я": "ya",
        "ў": "u",
        "қ": "q",
        "ғ": "g",
        "ҳ": "h",
    }
)


def slugify(value: str, *, fallback: str = "entity") -> str:
    """A slug an alias lookup and a URL can both use."""
    slug = _SLUG_RE.sub("-", value.strip().casefold().translate(_TRANSLITERATE)).strip("-")[:63]
    if not slug or not slug[0].isalnum():
        slug = f"{fallback}-{slug}".strip("-")[:63]
    return slug or fallback


def normalise_alias(value: str) -> str:
    """Case-folded, whitespace-collapsed alias key.

    Case folding rather than lowering, because Cyrillic needs it and the old
    SQLite build had to register a Python function to get it at all.
    """
    return re.sub(r"\s+", " ", value).strip().casefold()


def dsn_from_env(default: str = "") -> str:
    return os.environ.get("MEMKIT_DATABASE_URL", default)
