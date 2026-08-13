# Data model

Schema version is 6. Ordered migrations have recorded SHA-256 checksums and run only after a verified online backup and SQLite integrity checks.

- `owners`, `sessions`, `messages`: single-owner normalized source evidence. Messages are redacted and retained until explicit erasure.
- `memories`, `memory_revisions`, `memory_sources`, `memory_evidence`: free-form `kind`, tags, neutral JSON context, integer optimistic revisions, trust role, validity, exact message spans, and immutable mutation history.
- `index_outbox`: immutable, sequenced SQLite→Qdrant operations with claim-token and stale-lease recovery.
- `jobs`, `job_events`, `leases`, `budget_reservations`: durable long work, cooperative cancellation, locks, and atomic spend control.
- `namespaces`, `collections`, `records`, `record_revisions`, `links`: caller-defined structured data.
- `policies`: immutable versioned extraction, retrieval, retention, and consolidation configuration.
- `memories_fts`: FTS5 lexical projection maintained by insert/update/delete triggers.
- `retrieval_runs`, `retrieval_run_feedback`: HMAC query identity, safe result/rank/component telemetry, timings, token use, abstention, and explicit labels. Raw queries are never stored; runs expire after 90 days.
- `replay_batches`, `replay_items`: shadow-replay cursor, immutable provenance/evidence, editable review fields, decisions, approval checksum, and release-gate audit.
- `evaluation_runs`, `evaluation_cases`: blinded four-arm outputs and human-only reviews.
- `backup_artifacts`: verified recovery points, checksums, retention kind, and protection state.
- `judge_runs`: redacted model-call audit, token use, cost, latency, errors, request owner, and job.

All JSON columns have SQLite validity checks. Memory text/kind, probabilities, status, roles, revisions, and job state have database constraints in addition to API validation.

## v3 migration

Migration first creates a source-identified SQLite backup and JSON export of the retired board. Former task memories become archived `observation` rows, are excluded from search, and lose misused expiry values. Project scope becomes neutral `context.source_workspace`. The old table is then removed. Importing that handoff into a task authority remains the responsibility of the external Life OS workspace.
