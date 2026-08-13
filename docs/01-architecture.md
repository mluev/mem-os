# Architecture

## Memory, not workflow

Mem OS preserves evidence and memory. It has no task aggregate, workflow status, due-date semantics, or action engine. A caller may store opaque record content, but the core never interprets it as work to perform.

## Write path

1. Normalize and redact the event.
2. Commit evidence or memory plus an `index_outbox` row in one short SQLite transaction.
3. Return `stored`, `indexed`, and durable identifiers separately.
4. Claim an immutable, per-entity outbox operation and deliver it idempotently to Qdrant after commit. Completion uses the claim token; expired claims are retried.
5. Extraction jobs atomically claim a message window, reserve their maximum cost, call the provider outside SQLite transactions, validate exact citations, then commit operations and reconcile cost.

SQLite is the source of truth. FTS5 is transactionally synchronized with memory rows; Qdrant, profiles, and the dashboard remain derived views. Retrieval requests form a bounded union of dense, lexical, and exact-identifier candidates before scoring. Owner-scoped barriers coordinate delivery, reindex, and erasure; a late delivery rechecks the authoritative row before any external write.

## Durable work

A polling worker claims queued jobs with renewable leases. Startup requeues expired jobs, releases their message claims and unreconciled budget reservations, and resumes persistent replay cursors. API request lifetimes do not own background work.

## Reindex

Reindex snapshots SQLite and the outbox high-water mark, builds new `memories__g*` and `raw__g*` collections, validates exact IDs, replays concurrent writes, and atomically switches `__live` aliases. Failure or cancellation before activation leaves the old generation live. Activated predecessors are retained for seven days.

## Degraded dependencies

Qdrant unavailability does not stop authoritative evidence writes. The service reports a degraded state, search returns `503`, and the dependency-aware worker reconnects and drains the durable outbox when the index becomes available.

## Release workflow

V7 replay runs against a consistent database copy and produces an immutable-provenance review batch. Promotion applies only the reviewed manifest, never reruns the model, and is blocked on deterministic safety/retrieval/latency gates, a checksummed approval, a 32-case human evaluation, and both program and monthly budgets. A protected SQLite checkpoint and the previous Qdrant generation provide automatic rollback.

## Ownership and trust

One API key maps to one configured owner; clients cannot provide `owner_id`. Session owner and agent identity are immutable. Normal retrieval excludes assistant/agent claims and expired rows. Corrections and consolidation require the same owner and identical context; an API context move must be explicit.

## Extensibility

Namespaces contain JSON-Schema collections, revisioned records, metadata, context, links, and versioned extraction/retrieval/retention/consolidation policies. Judge providers and rerankers are replaceable; embedding model and immutable revision are configuration.
