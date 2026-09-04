# 0066 — A fresh schema v1 with a one-time importer, not a ported migration ladder

    Status:        accepted
    Date:          2026-09-04
    Supersedes:    —
    Superseded by: —
    Evidence:      tests/test_architecture_fitness.py (only the legacy importer speaks sqlite)
    Code:          src/memkit/db.py, src/memkit/importers/sqlite_v6.py
    Contract:      ../02-data-model.md

## Decision

The Postgres schema starts at version 1. It is not a translation of the SQLite v1–v6 ladder. `schema_migrations` records each version with the SHA-256 of its DDL, and startup fails if the history has a gap or a checksum that does not match this build — an edited migration is a different migration.

Existing data moves once, through `memkit import-sqlite <path>`, which reads a v6 file read-only and copies it into one user's private scope, preserving ids and timestamps. `importers/sqlite_v6.py` is the only module allowed to `import sqlite3`, and a fitness test enforces that.

## Alternatives and why not

**Port the ladder.** Rewrite six migrations in Postgres syntax and run them in order. The appeal is a familiar upgrade path from an existing database; the cost is that every table would arrive in its single-owner shape and be retrofitted with tenancy by a later step. That is the specific way isolation bugs get made: a `scope_id` added by `ALTER TABLE` is nullable or backfilled with a default, half the indexes still lead with the old key, and a query that forgets the predicate keeps returning rows because there was a time when it was right to. Starting at v1 means `scope_id NOT NULL REFERENCES entities` from the first line of DDL and every index built around it.

It also carries five migrations of history that no live database will ever traverse. Exactly one SQLite database exists, at v6.

**Migrate in place with a foreign data wrapper or a dual-write period.** Both are answers to a cutover problem this deployment does not have: one instance, one owner, a few thousand rows, and an operator who can stop the service for the ten seconds the import takes.

**Export to JSON and re-import through the API.** Would lose ids and re-run redaction, which sounds harmless and is not. Memory ids appear in retrieval feedback and evidence rows, and the extractor's temporal anchor is the message's own recorded date, so a re-extraction after the import must see the same history the original run saw. The importer therefore preserves both, and reconciles counts per table afterwards rather than reporting success over a half-copied store.

**Import memories as pending.** Rejected as the default and kept as `--pending`. Everything in a v6 database was written by the person receiving it, on their own machine; presenting a hundred of their own facts for confirmation is a queue nobody reads. The flag exists for an operator who wants the review pass anyway.

## Consequences

The service can no longer read a SQLite database, and `legacy_imported` marks the rows that came from one — they keep whatever text length the old store held, which is why the length constraint has a second branch. The import is idempotent: every insert is keyed by its original id and ignores conflicts, so a partial run is repeated rather than repaired. Identity sequences are moved past the imported ids afterwards, and `memkit reindex` rebuilds Qdrant, because the vector index knows nothing about any of this.
