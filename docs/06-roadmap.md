# Delivery status

The team migration is implemented: Postgres as the source of truth with additive schema v2, per-user credentials and dashboard sessions, entities and memberships as the scope model, subject attribution, a review queue, and routing in extractor prompt v9. Qdrant remains the derived index, so the transactional outbox, the durable worker, and generation reindex with alias swap survive the substrate change unaltered in shape.

Deployment is Docker Compose on Coolify — app, `postgres:16`, `qdrant:v1.18.2` — with CPU embeddings, persistent backup/export volumes, full archive decoding, and an isolated restore drill. Restore is an offline operator procedure into an empty replacement database, followed by current erasure receipt replay and index rebuilding; see [upgrade and recovery](09-operations.md). An existing single-owner database is moved in once with `memkit import-sqlite`.

Multiple owners and team scopes are no longer out of scope; they are the product. What remains out of scope: connectors, multimodal ingestion, multi-region operation, and a graph database. Entities and aliases cover the relationships a memory service needs, and a second store would have to be kept consistent with the first for a question nobody has asked yet.

Parked, with its trigger stated: the replay/release/evaluation program. Applying a replay used to copy the SQLite file, rewrite the copy, and swap it in; on Postgres that is a shadow database and a promotion procedure, which is real work with no rows waiting for it. `reextract.dry_run_report` — reachable as `memkit reextract-report` and `POST /v1/admin/reextract` — survives as the planner and answers the question that was actually being asked: how many windows, over which scopes, at what cost. It unparks when a prompt change needs to be applied to history rather than measured on a golden set, which means a measured v9-to-vNext win large enough that leaving old facts at the old version is the more expensive option.

Also removed with the single-owner deployment: the records platform (`namespaces`/`collections`/`records`/`links`), offline policy sweeps, the 100k benchmark command, and launchd service management. Policies survive, re-keyed by scope.

No automatic semantic merge and no confidence-based rank. Semantic merge exists behind an explicit `--apply --merge` flag with LLM confirmation and free rollback (decisions/0056); it never runs by default or on a schedule. Confidence-based rank still requires a measured evaluation before activation.

Every number that used to justify a threshold here was measured on SQLite, FTS5, and one owner. [`measurements.md`](measurements.md) marks which of those are now invalid and lists what must be re-measured before the next release.
