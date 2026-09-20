# Architecture

## Memory, not workflow

Mem OS preserves evidence and memory for a team. It has no task aggregate, workflow status, due-date semantics, or action engine. A memory is a durable claim with citations; nothing in the core interprets one as work to perform.

## Write path

1. Resolve the caller to a `Principal` and the request's scope name to an entity id the principal may write to. A scope it does not hold is refused here, before anything is read.
2. Normalize and redact the event; secrets are removed before persistence, not on the way out.
3. Commit evidence or memory plus an `index_outbox` row in one short Postgres transaction.
4. Return `stored`, `indexed`, and durable identifiers separately.
5. Claim an immutable, per-entity outbox operation and deliver it idempotently to Qdrant after commit. Completion uses the claim token; an expired lease is reclaimed and retried.
6. Extraction jobs assemble an exact message window under a per-session transaction advisory lock, then lease its rows with `FOR UPDATE SKIP LOCKED`. They reserve their maximum cost, call the provider outside every write transaction, validate exact citations, resolve routing, then commit operations and reconcile actual cost. Serializing assembly prevents competing workers from splitting or interleaving one window; unrelated sessions can claim concurrently.

Postgres is the source of truth. Lexical search cannot drift from it: `memories.search_tsv` is a generated `tsvector` column over the row's own text, so there is no projection to keep synchronized and no trigger to forget. Qdrant, profiles, and the dashboard are derived views, rebuildable from the database. Retrieval forms a bounded union of dense, lexical, and exact-identifier candidates before scoring.

Every request and worker operation borrows its own database connection and returns it on exit. Index-affecting writes acquire a shared maintenance gate before scope or row locks. Reindex and erasure acquire the exclusive gate on their borrowed connection; they do not upgrade a shared lock. A late delivery checks its live claim and the authoritative row before any external write, so an old upsert cannot resurrect a deletion and an old delete cannot remove a restored memory.

## Durable work

A polling worker claims queued jobs with renewable leases. Recovery periodically requeues expired jobs, releases their message claims and unreconciled budget reservations, and resumes work where it stopped, even while Qdrant is unavailable. Renewal, domain writes, and completion verify the current unexpired lease; obsolete workers cannot commit results. API request lifetimes do not own background work: a request queues a job and returns its id.

Long operations are jobs — extraction, export, erasure, reindex, consolidation, re-extraction planning. Each records events, honours cooperative cancellation, and carries a call limit that bounds provider spend and work in the same number, because each window is exactly one call.

## Reindex

Reindex pauses index-affecting writes with an instance-wide maintenance gate, takes a stable database snapshot, builds new `memories__g*` and `raw__g*` collections, and validates exact IDs and payloads before atomically switching both live aliases. Reads, job status, and cancellation remain available. Writes receive a retryable `503` during maintenance; background work is deferred.

The gate is a session advisory lock, so embedding does not hold an idle database transaction open. A crash closes the connection and releases the gate. Failure or cancellation before activation leaves the old generation serving. Retired generations are kept for seven days and remain subject to erasure; they are not current snapshots after later writes. A database restore requires a fresh rebuild, not switching to an older generation.

## Erasure and recovery

Erasure records its acceptance in a durable administrative job and fsyncs a receipt outside the database before deleting authoritative rows. The job survives deletion of its user. Cleanup covers every managed vector generation and managed export; failures stay queued for retry, and completion means all cleanup succeeded. Once accepted, erasure cannot be cancelled. Other people's shared claims are preserved; shared authorship conflicts are refused explicitly.

Compose persists backups, the erasure manifest, and exports in named volumes. Backups retain their existing retention policy. After an offline restore, the latest external manifest must be replayed before service reopens, and derived indexes and exports must be rebuilt or discarded. `memkit backup restore-drill` proves archive restoration and erasure replay in an isolated database without changing the configured database.

## Degraded dependencies

Qdrant unavailability does not stop authoritative writes. The service reports the degraded state on `/readyz` and `/v1/admin/health`, search returns `503` rather than a partial answer, and the dependency-aware worker reconnects and drains the outbox when the index returns. A provider outage fails extraction jobs without touching stored evidence; a failure that proves no billing occurred records zero cost.

## Ownership and trust

Every request resolves to exactly one principal, and every query that touches memory takes its scope set from that object. Nothing reads an owner from configuration.

Two columns carry the model, and the distinction between them is the whole of it. `scope_id` is the entity whose space holds a row — the authorization boundary. `subject_id` is the entity a fact is *about* — attribution, carrying no permission. A user's private memory is a scope whose entity is that user; a fact about a teammate lives in the team scope with that teammate as subject, so team membership controls access independently of whom the fact describes. `author_id` records who wrote it.

**A scope the caller does not hold is refused, never filtered.** A scope named in a request that the principal does not belong to is `403`; a scope that does not exist is `404`. Filtering would make a forbidden scope indistinguishable from an empty one, which hides a permissions bug and an intrusion equally well. The one deliberate exception runs the other way: a memory fetched *by id* from a scope the caller cannot reach is `404`, never `403`, so the API cannot be used to discover that somebody else's fact exists.

Session user, scope, and agent are fixed when the session is created and never move; extraction takes its authorization anchor from that row, so no request parameter can redirect a window into another person's memory. Provenance is a column no insert may omit: a fact supported only by assistant spans is refused at the write, and `assistant`/`agent` claims are excluded from normal retrieval.

Review status is orthogonal to all of it. Every automatic write is live immediately and `pending`; a user's own manual save into their own scope is `confirmed` on arrival, because they just said it. An extraction UPDATE of a confirmed memory keeps the new text live and returns the row to `pending`, with the previous wording one revision back for whoever reviews it. Declining archives; confirming re-activates, so a decline is reversible. Pending memories remain retrievable — a fact nobody has got round to confirming is still the best thing known.

## Extensibility

Entities are the extension point. A project, product, company, or ad-hoc scope is a row with a slug, aliases, and members; it needs no new table, no new endpoint, and no migration. Aliases exist because conversation does not use slugs, and they are globally unique — if two entities answered to the same name, routing a fact about either would be a guess.

Policies are versioned and immutable, optionally scoped: `NULL` is instance-wide, which is what the seeded `core-*` rows are. A measured ranking change is adopted by writing a new version and rolled back by naming the older id. Judge providers and rerankers are replaceable; the embedding model, its width, and its pinned revision are configuration, and changing any of them means a reindex rather than a restart.
