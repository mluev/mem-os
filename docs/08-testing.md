# Testing

## What the suite runs against

A real Postgres. Half of what these tests prove is SQL — scope predicates, `russian` stemming, `FOR UPDATE SKIP LOCKED` claims, advisory locks, generated columns, `NOT NULL` on `source_role` — and none of that has a meaningful in-memory stand-in. Point `MEMKIT_TEST_DATABASE_URL` at a server, or let the session fixture start a throwaway cluster from a local PostgreSQL installation with `fsync=off`; with neither, the suite skips rather than pretending.

Isolation between tests is `TRUNCATE ... RESTART IDENTITY CASCADE` followed by a re-seed of the `core-*` policies, not a rolled-back transaction. Several tests run worker or heartbeat threads that take their own pooled connections, and those threads cannot see an uncommitted outer transaction, so rollback-per-test would make them behave differently from production — the very difference the durable tests exist to catch. Truncating an empty schema costs about ten milliseconds. Restarting identity sequences keeps message-id assertions deterministic.

Qdrant is stubbed and the embedder is stubbed; nothing else is. `StubQdrant` records which writes reached the index and is deliberately not an emulator — its `query_points` returns nothing, because reimplementing Qdrant's filter semantics would be a second, wrong copy of the read path. `SearchableQdrant` adds a real dense search over upserted vectors for the claims that need one, notably abstention: a floor that is never reached cannot be proved to work against an empty index. `StubEmbedder` returns one constant unit vector, so every pair of texts has cosine 1.0; anything asserting on dedup or distinctness uses `HashEmbedder`, whose vectors are seeded from sha256 rather than the salted built-in `hash()`. The real Qdrant is exercised once, in `test_qdrant_integration.py`, which runs only with `MEMKIT_QDRANT_INTEGRATION=1` and a pinned container.

No test may call a paid provider. `conftest.py` blanks every judge credential at import time, and the HTTP harness re-asserts it on every setUp, because the first run of that suite made a real billed call — the credential fields carry a `validation_alias`, so the obvious way to blank them silently does nothing.

## What it covers

- identity and access: private scopes created with their user, team membership, viewer versus member write rights, alias uniqueness and case folding across Cyrillic, archived entities dropping out of routing and writes, a teammate's private scope never reachable, a revoked membership taking effect before the derived index catches up;
- the refusal contract: a named scope outside the caller's set is 403, an unknown one 404, another user's memory by id 404, a readable-but-not-writable memory 403 on mutation;
- authentication: key prefixes and constant-time secret comparison, keys whose base64url secret contains underscores, cookie mutations without the CSRF header, login rate limiting, session revocation on password change;
- review: an extraction ADD lands pending, a manual self-save lands confirmed, an update to a confirmed memory returns it for review with the previous wording available, decline archives and undo restores, pending memories still retrieved;
- routing: numbered entity blocks starting at one, the speaker and team first, the cap, a fact about a teammate becoming a team fact about them, a project fact landing in the project scope, a fabricated entity number dropped before it can reach a write, an unplaceable name keeping the fact private and raising a review item;
- full text: Russian nouns and verbs found through inflection, ASCII stems, case-insensitivity in both alphabets, an error code the stemmer cannot reach still found by the identifier arm, and the scope predicate applied to both arms;
- retrieval: the three arms and their fusion, rank normalisation, abstention on an unrelated query, trust and expiry guards independent of confidence, reranker limits, the token budget, correction, exact-term, temporal cases, and 10,000 distractors;
- durability: rollback versus post-commit index failure and retry, immutable outbox claim ordering, stale-lease recovery, a delivery for a deleted memory dropped rather than applied, erasure leaving no delivery that could restore a vector, concurrent budget reservation, message-window claims, heartbeats, cancellation, and provider latency proven to be outside any write transaction;
- reindex: generation build, exact-ID validation, safe alias activation, cancellation and validation failure both leaving the old alias live, and seven-day retention of the predecessor;
- privacy: secrets removed from messages, memory, revisions, stored model audit, and provider egress; export completeness; erasure refusing to delete a departing author's contributions to shared scopes;
- extraction: citation validation and quote-derived offsets, assistant-only sources refused, context reconciliation without invention, write-time dedup, per-op rejection reasons, and multi-window drains;
- architecture fitness, which reads the AST and the dependency graph rather than the source text: every handler whose SQL touches a scoped table must name the principal, every operation must declare who may call it, every `/v1/admin` route must be admin-guarded or on an explicit principal-narrowed list whose entries are checked for staleness, only the legacy importer may `import sqlite3`, `owner_id` may not reappear outside prose, retired routes must 404, and the generated OpenAPI and doc blocks must match the code;
- surfaces: the Claude Code skill and hooks, the Hermes provider, the generated SDKs, and the dashboard.

## Local gates

```bash
uv run pytest -q
uv run ruff check src tests tools integrations/hermes eval
uv run ruff format --check src tests tools integrations/hermes eval
uv run pytest -q --cov=memkit --cov-fail-under=75
uv run python -m eval.golden --schema-only
uv run python tools/export_openapi.py   # then confirm openapi.json is unchanged
uv run python -m tools.docblocks --check
pnpm --dir web lint
pnpm --dir web typecheck
pnpm --dir web test
pnpm --dir web test:e2e
pnpm --dir web build
```

CI adds a dependency audit, a real pinned-Qdrant job, SDK regeneration diffed against the committed output, and a clean wheel plus consumer install. Model-quality experiments stay explicit and budgeted; the golden comparison, the retrieval eval, and any human evaluation are release artifacts rather than ordinary CI fixtures.
