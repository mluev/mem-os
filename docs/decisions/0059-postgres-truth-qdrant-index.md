# 0059 — Postgres is the source of truth; Qdrant stays the derived index

    Status:        accepted
    Date:          2026-09-04
    Supersedes:    —
    Superseded by: —
    Evidence:      ../measurements.md#to-be-re-measured
    Code:          src/memkit/db.py, src/memkit/outbox.py, src/memkit/reindex.py
    Contract:      ../01-architecture.md, ../02-data-model.md

## Decision

The authoritative store is Postgres, reached through `psycopg` 3 with a connection pool. Qdrant is kept exactly as it was: a derived vector index holding `memories` and `raw`, fed by the transactional outbox, delivered by the durable worker, and rebuilt by generation reindex with an alias swap.

Three primitives change substrate and nothing else. `BEGIN IMMEDIATE`, which serialised writers by taking the whole database, becomes `FOR UPDATE SKIP LOCKED` on the specific rows a claim needs. The lock file beside the SQLite database, which coordinated erasure against index delivery and only worked because every process shared a filesystem, becomes `pg_advisory_xact_lock` — held by the database, so it also holds between containers. Per-thread connections become a pool, because a Postgres connection is a process fork and a handshake, not a file handle.

## Alternatives and why not

**Stay on SQLite.** It was never the wrong choice for one person on one laptop. It is the wrong choice for several people on a VPS: one writer at a time, a lock that is the whole file, no advisory locks, no server-side text search worth the name, and coordination primitives that assume a shared filesystem. Every one of those is load-bearing in a team instance — two agents posting evidence while a reindex runs is the ordinary case, not the edge.

**Postgres with pgvector, dropping Qdrant.** This is the tempting one, and it would have bought a real simplification: one datastore, one backup, one restore, transactional consistency between a memory and its vector — which would retire the outbox, the delivery worker, the per-scope barrier, the generation reindex, and the alias swap, along with several hundred lines of the most subtle code in the repository and the `index_drift` metric that exists because those two stores can disagree.

It was not taken, for three reasons and one of them is decisive. The decisive one: the outbox, the worker and generation reindex are *written, tested and correct*. Deleting working durability machinery to remove a dependency is paying a migration risk to collect a maintenance saving, in the same change as a database port and a tenancy model. The second: HNSW in pgvector is built and tuned inside the same server that is answering everything else, and the index parameters that matter at 100 facts are not the ones that matter at 100,000, whereas the Qdrant pin is a tested pair with a known upgrade path. The third: the alias swap gives a validated rebuild with instant rollback — the old generation is still serving until the exact id set is confirmed present — and reproducing that on a pgvector table means a shadow table and a rename, which is the same complexity in a place where a mistake is harder to undo.

Deferred rather than declined. The trigger is a Qdrant operational cost that is actually being paid: an upgrade that breaks the pin, a memory footprint that matters on the VPS, or a drift incident the outbox did not prevent. At that point the migration is a reindex into a table instead of a collection, which is exactly the shape the derived-index design already supports — and this ADR is the reason it is a reindex and not a rewrite.
