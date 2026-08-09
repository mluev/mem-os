# Data model

Schema version is 4.

- `owners`, `sessions`, `messages`: single-owner normalized source evidence. Messages are redacted and retained until explicit erasure.
- `memories`, `memory_sources`, `memory_evidence`: free-form `kind`, tags, neutral JSON context, trust role, validity, exact message spans, and supersession history.
- `index_outbox`: idempotent SQLite→Qdrant delivery.
- `jobs`, `job_events`, `leases`, `budget_reservations`: durable long work, cooperative cancellation, locks, and atomic spend control.
- `namespaces`, `collections`, `records`, `record_revisions`, `links`: caller-defined structured data.
- `policies`: immutable versioned extraction, retrieval, retention, and consolidation configuration.
- `retrieval_feedback`: usefulness and correctness, not a display counter.
- `judge_runs`: redacted model-call audit, token use, cost, latency, errors, request owner, and job.

All JSON columns have SQLite validity checks. Memory text/kind, probabilities, status, roles, revisions, and job state have database constraints in addition to API validation.

## v3 migration

Migration first creates a SQLite backup and a JSON export of the retired board. Former task memories become archived `observation` rows, are excluded from search, and lose misused expiry values. Project scope becomes neutral `context.source_workspace`. The old table is then removed.
