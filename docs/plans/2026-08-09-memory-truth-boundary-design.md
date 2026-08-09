# Memory Truth + Boundary Separation

This design implements the accepted audit repair program. Memkit owns evidence,
semantic memory, generic records, indexing, provenance, and retrieval policies. It
does not own tasks, workflow states, due dates, projects, reminders, or personal
productivity UI.

The migration is intentionally breaking. Before changing a v3 database, memkit
creates a SQLite backup and exports every task-board row with its memory and source
references. Task memories become archived observations and are excluded from normal
retrieval. The task aggregate, routes, prompt fields, vector payloads, UI, tests, and
documentation are then removed.

SQLite remains authoritative. Every derived-index mutation is recorded in a durable
outbox in the same transaction as its source mutation. Workers apply those operations
idempotently after commit. Paid and maintenance work uses durable jobs, leases, and
budget reservations; network calls never hold SQLite's writer lock. Reindex builds a
new generation, validates it, replays newer outbox operations, and switches aliases.

The public model becomes domain-neutral: namespaces contain collections with
versioned JSON Schemas; collections contain records, metadata, links, and opaque
context. Memories use free-form kinds, tags, context, validity, evidence spans, and
trust roles. Retrieval policies select candidate arms, filters, ranking, trust,
validity, abstention, and token budgets. A single configured owner is derived by the
service and is never selected by callers.

Legacy memory replay remains dry-run only. The implementation produces a costed,
reviewable report and does not apply it to live data without a later explicit request.
