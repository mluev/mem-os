# Architecture

## Memory, not workflow

Mem OS preserves evidence and memory. It has no task aggregate, workflow status, due-date semantics, or action engine. A caller may store opaque record content, but the core never interprets it as work to perform.

## Write path

1. Normalize and redact the event.
2. Commit evidence or memory plus an `index_outbox` row in one short SQLite transaction.
3. Return `stored`, `indexed`, and durable identifiers separately.
4. Deliver the outbox idempotently to Qdrant after commit. A retry repairs missing delivery.
5. Extraction jobs reserve their maximum cost, call the provider outside SQLite transactions, validate exact citations, then commit operations and reconcile cost.

SQLite is the source of truth. Qdrant, BM25 candidates, profiles, and the dashboard are derived views.

## Reindex

Reindex snapshots SQLite and the outbox high-water mark, builds new `memories__g*` and `raw__g*` collections, validates exact IDs, replays concurrent writes, and atomically switches `__live` aliases. Failure or cancellation before activation leaves the old generation live.

## Ownership and trust

One API key maps to one configured owner; clients cannot provide `owner_id`. Session owner and agent identity are immutable. Normal retrieval excludes assistant/agent claims and expired rows. Corrections and consolidation require the same owner and identical context; an API context move must be explicit.

## Extensibility

Namespaces contain JSON-Schema collections, revisioned records, metadata, context, links, and versioned extraction/retrieval/retention/consolidation policies. Judge providers and rerankers are replaceable; embedding model and immutable revision are configuration.
