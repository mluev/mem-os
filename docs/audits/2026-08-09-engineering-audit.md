# memkit comprehensive engineering audit

**Audit date:** 2026-08-09 (Asia/Tashkent)  
**Repository:** `/Users/mlutfullaev/dev/indie/mem-os`  
**Revision:** `0fad59dcaf4f979062552a37a52508261a1c8f73` (`master`)  
**Mode:** read-only; all destructive/failure probes used temporary databases, stub embedders/providers/Qdrant, or a Git archive under `/tmp`. No paid provider or live Qdrant call was made.

## Executive assessment

The repository has unusually strong design documentation, a large deterministic backend suite, careful provenance controls, and a sensible SQLite/WAL/thread-local-connection foundation. The central reliability invariant is nevertheless broken in multiple production write paths: Qdrant is mutated before the surrounding SQLite transaction commits. A rollback can therefore leave retrievable facts that do not exist in the declared source of truth. The reverse failure also occurs for raw-message indexing: SQLite commits, the request fails during Qdrant indexing, and an idempotent retry deliberately skips the repair.

Other release-blocking findings are:

1. The documented hard monthly spend ceiling permits the call that crosses the limit and has no atomic reservation across job types.
2. Extraction opens a SQLite write transaction before a remote judge call, so unrelated writes wait for provider latency.
3. Reindex swallows collection-drop failures, can retain expired points, reports success, and clears `index_dirty`.
4. The reindex mutation barrier omits task and message writers.
5. Bulk mutation accepts arbitrary values and can persist out-of-vocabulary types, invalid numeric values, or unrelated fields.
6. A wheel built from a clean Git archive contains neither the dashboard nor the Hermes plugin; both documented installed features fail.

No unauthenticated `/v1` route, SQL injection, command injection, unsafe deserialization, or React raw-HTML sink was found. The default loopback bindings and no-CORS default materially reduce exposure. They do not repair the correctness, privacy-boundary, packaging, and cost-control failures above.

### Verified finding count

| Severity | Count | Meaning in this report |
|---|---:|---|
| Critical | 0 | Immediate remote compromise or unrecoverable broad loss was not demonstrated. |
| High | 7 | Release-blocking correctness, spend, concurrency, or packaging defect. |
| Medium | 7 | User-visible contract/data-quality defect or material operational weakness. |
| Low | 3 | Limited exposure, accessibility, or documentation defect. |

The count covers only **verified defects** below. Conditional threats and unmeasured failure modes are kept separately under **Risks**, so they are not presented as observed failures.

## Scope and method

Reviewed surfaces:

- Backend/API: `src/memkit/` (19 Python modules), route schemas, auth, provider adapters, import, extraction, mutations, retrieval, consolidation, and task board.
- Data: SQLite schema/versioning/transactions and Qdrant collections/index lifecycle.
- Cost/privacy: provider prompts, cost ledger, credentials, Hermes scrubbing, raw retention, remote-data boundary.
- Frontend: 43 TypeScript/TSX files, API client/types, routing, accessibility, state, bundles, and build configuration.
- Operations: `pyproject.toml`, `uv.lock`, `pnpm-lock.yaml`, Docker Compose, launchd files, wheel contents, docs, tests, and generated doc blocks.

Important limitations:

- No live cloud judge, model download, MPS benchmark, live Qdrant container, browser assistive-technology pass, or network CVE lookup was run. Those would be stateful, paid, hardware-specific, or online checks.
- `vite build` was not run in the checkout because `web/vite.config.ts:29-31` empties and rewrites `src/memkit/web_dist`. TypeScript was checked with `--noEmit --incremental false`; release packaging was tested from a clean Git archive in `/tmp`.
- The existing untracked `.idea/` and `deploy/ai.memkit.service.plist` were left untouched. Final `git status --short` remained exactly those two entries.

## What passed

- **Backend behavior:** 399 offline `unittest` tests passed.
- **Frontend behavior:** 6 Vitest tests in 2 files passed; TypeScript no-emit checking passed.
- **Generated documentation:** all 8 generated blocks match code.
- **Dependency consistency:** `uv lock --check` and `uv pip check` passed.
- **Deployment syntax:** both present plist files pass `plutil -lint` (the service file is untracked).
- **Security basics:** every `/v1` OpenAPI operation carries the API-key dependency; only `/healthz` is open (`tests/test_api.py:62-64`). SQL dynamic sort columns are allow-listed (`src/memkit/admin.py:335-369`); user filter values are parameters. CORS is disabled unless explicitly configured and credentials are disabled (`src/memkit/api.py:130-137`). Qdrant and API defaults bind to loopback (`src/memkit/config.py:43-50`, `docker-compose.yml:5-9`). React renders user content as text; no `dangerouslySetInnerHTML` or equivalent sink exists.
- **Data foundations:** WAL, foreign keys, a busy timeout, and one connection per worker thread are explicit (`src/memkit/db.py:148-162,357-400`). The v3 table-rebuild migration uses explicit transaction control and foreign-key verification (`src/memkit/db.py:239-288`), and migration preservation is tested.
- **Mutation design precedent:** ordinary admin edits already use the correct shape—commit SQLite, then apply an index plan and mark the index dirty on repeated failure (`src/memkit/mutate.py:1-6,30-83`; `src/memkit/admin.py:162-215`). This provides an in-repository pattern for repairing the inconsistent paths.
- **Retrieval discipline:** owner/status filters and project/task filtering are pushed into Qdrant (`src/memkit/retrieval.py:199-248`); route-level bounds exist for result limit and token budget (`src/memkit/api.py:58-76`). Routes are lazy-loaded (`web/src/router.tsx:12-55`) and reduced-motion CSS exists (`web/src/styles/globals.css:1559-1560`).

---

## Verified defects

### V1 — HIGH — Qdrant receives uncommitted memory revisions

**Evidence**

- `store.add_memory` inserts the SQLite row and then immediately embeds/upserts the point at `src/memkit/store.py:250-330`.
- Callers still own an open SQLite transaction: manual memory creation (`src/memkit/api.py:427-448`), task creation (`src/memkit/taskboard.py:364-384`), consolidation (`src/memkit/consolidate.py:423-451` within `src/memkit/admin.py:1058-1074`), and CLI/API extraction (`src/memkit/api.py:196-214`; `src/memkit/cli.py:190-199`).
- Extraction ADD, UPDATE, and DELETE apply Qdrant operations at `src/memkit/extract.py:323-355,378-405,417-428` before the caller commits. Re-extraction does the same at `src/memkit/reextract.py:262-292` inside `src/memkit/admin.py:1009-1024`.
- This directly contradicts the module invariant: “Qdrant work ... must be applied only after that commit” (`src/memkit/mutate.py:1-6`).

**Observed result**

```text
rollback_split_brain {"sqlite_memories": 0, "qdrant_points": 1}
```

The SQLite transaction rolled back, but the fact remained in Qdrant and can be returned by search. UPDATE can similarly expose a revision SQLite rejected; DELETE can hide a fact whose status rollback kept active. The DELETE exception handler at `src/memkit/extract.py:424-427` also does not set any durable or in-memory dirty marker.

**Required correction**

Return index plans from all SQLite mutations and apply them only after commit, as the admin edit path already does. For crash safety, make this a durable SQLite outbox (`index_outbox`) written in the same transaction, with idempotent Qdrant application, retry state, and an operator-visible lag/error metric. A Boolean held in one process is not a substitute for an outbox.

### V2 — HIGH — Committed message can return failure and remain permanently absent from raw retrieval

**Evidence**

- `/v1/messages` commits at `src/memkit/api.py:222-232`, then calls `store.index_raw` without error handling at line 236.
- If indexing raises, the client observes a server error after the message is durable.
- An idempotent retry returns early at `src/memkit/api.py:233-234`, before line 236, so it never repairs the missing raw point. `index_dirty` is not set.

**Observed result**

```text
ingest_commit_before_index {"first_error": "RuntimeError: qdrant offline", "sqlite_messages": 1, "retry_status": 201, "retry_deduplicated": true, "raw_qdrant_points": 0, "index_dirty": false}
```

Without an `external_id`, a normal retry can instead create a duplicate message. With one, it acknowledges success while leaving retrieval incomplete until a full manual reindex.

**Required correction**

Use the same durable index outbox. The initial response should truthfully distinguish `stored` from `indexed` (or return 202), and a deduplicated retry must enqueue/retry any incomplete index operation.

### V3 — HIGH — Reindex silently succeeds when collection deletion fails

**Evidence**

- `vectors.drop_collection` catches every exception and returns success (`src/memkit/vectors.py:166-170`).
- `store.reindex` calls it for both collections and then only upserts rows that should exist (`src/memkit/store.py:381-435`). It cannot remove stale points if the drop failed.
- Both reindex controllers mark the job complete and clear `index_dirty` after `store.reindex` returns (`src/memkit/api.py:515-526`; `src/memkit/admin.py:938-945`).

**Observed result**

```text
reindex_swallowed_drop {"reported_memories": 1, "sqlite_active": 1, "qdrant_points_after": 2, "stale_point_survived": true}
```

An expired point survived, while the rebuild reported the correct number of *upserted* rows as if that were the final collection count.

**Required correction**

Never suppress a failed collection delete unless a specific “not found” response is verified. Re-read exact counts and preferably IDs after rebuilding before declaring success. The safer operational design is generation-named collections plus an atomic alias swap; the old generation remains available until the new one validates.

### V4 — HIGH — The documented hard monthly spend ceiling is not hard

**Evidence**

- The contract calls it a hard ceiling (`README.md:7-9`, `.env.example:46-48`, `docs/01-architecture.md:126-127`).
- `judge.extract` only rejects when already-recorded spend is at or above the limit (`src/memkit/judge.py:390-398`). It makes the provider call at lines 428-437 and records actual cost at lines 447-469. There is no projected-cost or worst-case reservation.
- Consolidation has the same shape: compare current spend, call, then add actual cost (`src/memkit/consolidate.py:344-368`).

**Observed result**

```text
cost_ceiling {"limit": 1e-06, "call_cost": 0.0003, "month_spend": 0.0003, "error": null}
```

A call from zero spend exceeded the configured ceiling by 300× and returned no error. Concurrent re-extraction, consolidation, API, or CLI jobs can also read the same committed total before any of them logs cost; there is no reservation shared across job types.

**Required correction**

Create an atomic monthly budget ledger/reservation in SQLite. In a short `BEGIN IMMEDIATE` transaction, reserve a conservative maximum derived from input size, provider pricing, and the configured output-token cap; refuse when `actual + reserved + proposed > limit`; reconcile reservation to actual usage after the call. Apply this to every paid path. Use provider-side spending limits as a second boundary, not the primary application guarantee.

### V5 — HIGH — Extraction holds SQLite's writer slot across the remote judge call

**Evidence**

- The caller opens a transaction around the entire extraction (`src/memkit/api.py:196-214`; `src/memkit/cli.py:190-199`).
- `run_extraction` first executes `fast_forward_to_user_turn` (`src/memkit/extract.py:459-464`). That helper executes an UPDATE even when zero rows need changing (`src/memkit/extract.py:113-142`), opening a SQLite write transaction.
- Candidate work and the remote provider call then occur before commit (`src/memkit/extract.py:496-515`; provider at `src/memkit/judge.py:428-437`). SQLite permits only one writer.

**Observed result with an offline judge stub sleeping 11 seconds**

```text
judge_holds_sqlite_writer {"concurrent_write_seconds": 11.24, "concurrent_write_error": null, "extraction_errors": []}
```

An unrelated message insert waited for essentially the full simulated provider latency. This can stall ingestion, task edits, retrieval feedback writes, and maintenance. It also makes request latency and lock behavior depend on a cloud service.

**Required correction**

Claim an extraction window in a short transaction using a durable lease/idempotency key, commit, perform embeddings/provider work outside any SQLite transaction, then apply the result in another short transaction conditioned on the lease. This preserves single-processing semantics without serializing every database writer behind network I/O.

### V6 — HIGH — The reindex mutation barrier omits writers that mutate both stores

**Evidence**

- The documented contract says every mutation returns 409 (`docs/03-api.md:134-135`, `docs/02-data-model.md:179-185`, `docs/08-testing.md:47-49`).
- The guard exists only in `src/memkit/admin.py:152-160` and a hand-written check for manual memory creation (`src/memkit/api.py:427-430`).
- Task create/edit routes have no guard (`src/memkit/taskboard.py:364-483`); `/v1/messages` and session close/background extraction have none (`src/memkit/api.py:196-301`).
- The test's mutation matrix omits task/message routes (`tests/test_api.py:72-105`).

**Observed result**

```text
task_during_reindex_status: 201
```

Task writes can land while the collection is being dropped/refilled. Raw-message indexing and extraction can do the same. A point written after reindex read its SQLite source but before the new collection finishes can be lost or overwritten, after which the job unconditionally clears `index_dirty` (`src/memkit/admin.py:941-945`). The lock/job state is process-local (`src/memkit/api.py:110-112`; `src/memkit/admin.py:1088-1108`), so another worker or CLI process does not see it.

**Required correction**

Enforce a durable maintenance lease at the shared mutation layer, not route by route, and include all SQLite/Qdrant writers. Prefer the generation-and-alias reindex design so reads and ordinary writes do not need a long global outage; replay outbox entries created after the reindex snapshot before swapping.

### V7 — HIGH — Bulk mutation bypasses the API's declared vocabularies and bounds

**Evidence**

- `BulkIn.value` is `Any` (`src/memkit/admin.py:274-280`).
- `set_type` and `set_importance` pass it directly; `set_scope` passes the caller's entire dictionary (`src/memkit/mutate.py:385-406`).
- The generic mutation layer validates only field names and status; it does not validate type, scope, text, key relationships, or numeric bounds (`src/memkit/mutate.py:148-190`).
- SQLite has no CHECK constraints for type, scope, status, importance, or confidence (`src/memkit/db.py:84-115`), despite the declared vocabularies at `docs/02-data-model.md:92-109`.

**Observed result**

```text
bulk_invalid_status: 200
bulk_invalid_stored_type: "not-a-memory-type"
```

`set_importance` can store a string or values outside `[0,1]`. `set_scope` can include any otherwise allowed field—such as `status` or `judge_run_id`—so an operation named “set_scope” can change unrelated lifecycle/audit state.

**Required correction**

Use a discriminated union of strict per-operation request models, `extra="forbid"`, and domain validation in the shared mutation layer. `set_scope` should construct exactly `{scope, scope_key}`. Add database CHECK constraints as defense in depth, audit existing rows before migration, then reindex.

### V8 — MEDIUM — `valid_until` is not enforced on the read path

**Evidence**

- The Qdrant memory payload omits `valid_until` (`src/memkit/store.py:333-378`).
- Qdrant filters check only owner/status/scope (`src/memkit/retrieval.py:199-248`), and reranking never checks validity (`src/memkit/retrieval.py:251-295`).
- Expiration only occurs when consolidation runs (`src/memkit/consolidate.py:111-126,320-330`). The docs explicitly acknowledge that expired facts previously surfaced (`docs/04-judge.md:155-162`) but rely on a nightly job.

An expired fact remains retrievable until the scheduler succeeds; in a clean checkout the service launch agent is missing and the consolidation agent is path-specific, so that delay can be indefinite.

**Required correction**

Include validity in the derived payload and exclude `valid_until <= now` during candidate selection (or overfetch and validate against SQLite before final ranking). Reject/upsert-as-expired any already-expired write. Keep consolidation as lifecycle cleanup, not correctness enforcement.

### V9 — MEDIUM — Session ownership supplied by the caller can contradict the stored session

**Evidence**

- `ensure_session` silently keeps the original owner/agent on ID collision (`src/memkit/db.py:327-338`).
- `/v1/sessions/{session_id}/close` fetches only `agent_id`, not `owner_id` (`src/memkit/api.py:250-257`), then passes the query parameter/default as extraction owner (`src/memkit/api.py:272-284`).

**Observed result**

```text
cross_owner_close {"created_status": 201, "close_status": 200, "session_owner": "owner-a", "extract_owner": "owner-b"}
```

The same static API key currently makes this a correctness/isolation flaw rather than an authentication bypass. A typo or reused session ID can place extracted memories under a different owner than their source session, making them invisible to the expected owner and unsafe for future multi-user support.

**Required correction**

Derive owner and agent from the stored session for close/extraction. On ingest, reject a session ID whose supplied owner/agent does not match its existing row. Add a test now, before owner-level authentication is introduced.

### V10 — MEDIUM — Filtered session pagination returns the wrong total

**Evidence**

- The item query applies `has_unprocessed` through HAVING (`src/memkit/admin.py:687-700`).
- The count query ignores that HAVING condition (`src/memkit/admin.py:719-721`).

**Observed result**

```text
filtered_session_items: 1
filtered_session_total: 2
```

Clients calculate incorrect pages and display a total that includes sessions excluded from the result.

**Required correction**

Count the grouped/filtered subquery, or express the filter as `EXISTS`/`NOT EXISTS` and reuse one WHERE builder for both item and count queries.

### V11 — MEDIUM — Core write/search models accept blank and unbounded text/identifiers

**Evidence**

- `MessageIn.content`, session/owner/agent/external IDs, `SearchIn.query`, and `MemoryIn.text` have no trim, minimum, or maximum constraints (`src/memkit/api.py:42-95`).
- `store.add_memory` stores and embeds the text verbatim (`src/memkit/store.py:250-330`).
- The task API demonstrates the expected validation pattern, including strip and a 200-character cap (`src/memkit/taskboard.py:201-219`).

**Observed result**

```text
empty_memory_status: 201
empty_memory_stored_length: 3
```

Whitespace facts pollute durable memory and create meaningless embeddings. Unbounded messages/searches/memories enable local memory/CPU/storage exhaustion and unexpectedly large provider prompts. Model-emitted facts are described as capped at 200 characters (`docs/04-judge.md:82-86`), but the provider schema only describes that preference (`src/memkit/providers.py:105-128,167`) and `Op.parse` only strips/nonempty-checks (`src/memkit/judge.py:166-223`).

**Required correction**

Normalize and bound every user-controlled string in Pydantic, reject blank-after-trim, impose request-body limits at the server/proxy, and enforce the 200-character operation limit in code/schema. Select explicit limits for messages and identifiers based on importer corpus measurements.

### V12 — MEDIUM — Clean release artifacts omit the two documented installed features

**Evidence**

- `src/memkit/web_dist/` is ignored (`.gitignore:14`), absent from `git archive`, and there is no frontend build hook in `pyproject.toml:22-28`.
- FastAPI mounts `/ui` only if a CWD-relative directory exists at import time (`src/memkit/config.py:51`; `src/memkit/api.py:540-546`).
- `memkit install-hermes` looks outside the installed package for `integrations/hermes/memkit` (`src/memkit/cli.py:362-392`), while the wheel target packages only `src/memkit` (`pyproject.toml:26-28`).

**Observed from a wheel built from `git archive HEAD`**

```text
Successfully built /tmp/.../memkit-0.1.0-py3-none-any.whl
{'wheel': '/tmp/.../memkit-0.1.0-py3-none-any.whl', 'files': 25, 'web_dist_files': 0}
provider source not found at /private/tmp/integrations/hermes/memkit
wheel_install_hermes_return 1
wheel_payload {'web_dist_files': 0, 'hermes_integration_files': 0, 'total_files': 25}
```

A source checkout with a prebuilt ignored directory hides both failures. A normal wheel/fresh clone cannot serve the documented dashboard (`README.md:46,60-70`) and cannot install the documented Hermes provider.

**Required correction**

Build the frontend in a deterministic release step, include it and the Hermes package as package data, resolve assets with `importlib.resources`, and add a smoke test that installs the wheel into an empty environment, starts the app, checks `/ui/`, and runs `memkit install-hermes` into a temporary home.

### V13 — MEDIUM — Frontend quality gates do not validate the claimed API contract

**Evidence**

- `pnpm lint` is declared (`web/package.json:6-12`) but no `eslint.config.*` exists; ESLint 9 exits before analyzing code.
- `web/src/api/schema.d.ts:1-2` is explicitly a placeholder containing `export interface paths {}`. It is not imported anywhere. The application uses hand-written types.
- Documentation says the file is generated and only calls drift detection a gap (`docs/08-testing.md:219-224`), understating that the checked-in schema is empty and the generated types protect no client call.

**Observed result**

```text
> eslint .
ESLint: 9.39.5
ESLint couldn't find an eslint.config.(js|mjs|cjs) file.
ELIFECYCLE Command failed with exit code 2.
```

TypeScript passes, but it validates casts against hand-maintained interfaces rather than the backend OpenAPI contract.

**Required correction**

Add a flat ESLint config and make lint part of CI. Generate OpenAPI deterministically without a live paid service, regenerate `schema.d.ts`, use those endpoint types in the client, and fail CI on a diff.

### V14 — MEDIUM — Operations UI claims implemented service operations do not exist

`web/src/routes/Ops.tsx:112-120` disables Reextract and Consolidate and states they are “not implemented in the service yet.” Both APIs are implemented at `src/memkit/admin.py:966-1031,1043-1085`, documented at `docs/03-api.md:137-181`, and the README says stages 0–6 are done (`README.md:11-16`). Operators are incorrectly told that available maintenance/recovery functions do not exist.

**Required correction:** wire safe dry-run-first UI flows or accurately describe them as CLI/API-only. Generated capability metadata would avoid a third hand-maintained implementation-status copy.

### V15 — LOW — Public health response leaks paths and can report healthy through degraded dependencies

`/healthz` is intentionally unauthenticated (`docs/03-api.md:3-4`). It returns the absolute database path, collection counts, backlog, reindex state, and dirty state (`src/memkit/api.py:162-193`). The probe reproduced status 200 and a concrete temp path. `ok` is only `qdrant_ok` (line 183): `backlog=-1` after a database failure and `embedder=false` do not make it false. `vectors.count` converts any Qdrant error into zero (`src/memkit/vectors.py:173-177`), conflating “empty” with “unavailable.”

On default loopback this is low exposure; it becomes an information leak and misleading readiness signal when `MEMKIT_HOST` is changed.

**Required correction:** expose only minimal liveness publicly; protect detailed diagnostics. Make readiness fail on required DB/Qdrant/embedder checks and represent unknown counts as errors/null, not zero.

### V16 — LOW — Frontend has concrete keyboard/screen-reader gaps

Verified against the source and the current [Vercel Web Interface Guidelines](https://raw.githubusercontent.com/vercel-labs/web-interface-guidelines/main/command.md):

- Theme icon button has only a tooltip, no accessible name (`web/src/components/AppShell.tsx:203-207`).
- Clear-search and copy-ID icon buttons lack `aria-label` (`web/src/routes/Memories.tsx:160-165,323`).
- Clickable memory table rows are mouse-only `<tr onClick>` elements (`web/src/routes/Memories.tsx:196-207`).
- Session filter inputs and select have placeholders/visible values but no labels (`web/src/routes/Sessions.tsx:33-36`); Judge Runs output select is unlabeled (`web/src/routes/JudgeRuns.tsx:36-40`).
- There is no skip link before the application main content (`web/src/components/AppShell.tsx:193-217`).

Reduced-motion support is present, and most destructive/menu controls correctly use semantic buttons/Radix primitives. Fix the named controls with labels, keyboard-equivalent row actions, focus-visible behavior, and a skip link; then add component-level axe/keyboard tests.

### V17 — LOW — Deployment and spending documentation contains executable contradictions

- README says `deploy/` holds two launchd agents (`README.md:89-96`), but `git ls-files deploy` returns only `deploy/ai.memkit.consolidate.plist`. The service plist in this working tree is untracked.
- README says neither agent loads automatically (`README.md:95`), while the untracked service file says `RunAtLoad=true` (`deploy/ai.memkit.service.plist:19-20`).
- README says every money-spending command prints an estimate first (`README.md:72-73`). `memkit consolidate` defaults to live execution because `--dry-run` is `store_true` (`src/memkit/cli.py:455-461`); it prints current spend, not a proposed-call estimate, then calls the model (`src/memkit/cli.py:286-337`).

The tracked consolidation plist is explicitly machine-specific (`deploy/ai.memkit.consolidate.plist:27-36,57-60`) and writes indefinitely to `/tmp/memkit-consolidate.log` with no rotation (`:49-52`). The hardcoded paths are documented, but a missing service artifact and false safety claim are not.

**Required correction:** track or generate the service unit, make README semantics exact, add an explicit `--apply`/`--yes` for human paid runs while the scheduler supplies it intentionally, and configure log rotation/size retention.

---

## Risks (credible, but not demonstrated as an incident)

### R1 — HIGH privacy risk — Secret scrubbing is adapter-specific, not a provider boundary

The Hermes adapter has a thoughtful structural policy: tool results default off and user text passes through regex scrubbing (`integrations/hermes/memkit/scrub.py:1-57`; `integrations/hermes/memkit/__init__.py:275-322`). The central service does not enforce that boundary:

- Direct `/v1/messages` stores caller content unchanged (`src/memkit/api.py:217-236`).
- Claude transcript import extracts user text but never invokes the Hermes scrubber (`src/memkit/importers/claude_code.py:112-193`; import write path `src/memkit/cli.py:72-121`). It rejects tool-result blocks and oversized documents, which is valuable, but a user-pasted credential remains user text.
- `judge.render_window` sends user messages in full (`src/memkit/judge.py:331-347`) and the provider call receives that prompt (`src/memkit/judge.py:401-437`). The prompt rule “never store credentials” (`docs/04-judge.md:102-105`) can stop a value from becoming a memory; it cannot stop disclosure to the provider that is reading the rule.
- The leak metric only checks values reaching the store (`docs/08-testing.md:78-96`), not values leaving for a provider.

This is a verified data path, but no real secret was sent during the audit, so it is classified as risk rather than incident. Centralize redaction/DLP immediately before every provider call, preserve a local redaction audit count without values, document exactly what leaves the machine and provider retention terms, and test direct API/import/re-extraction/consolidation paths. Regexes are only a second line; consider local secret scanners and explicit opt-in for imported histories.

### R2 — HIGH when exposed beyond loopback — Authentication can run with a public default

`Settings.api_key` and `.env.example` default to `change-me` (`src/memkit/config.py:16`; `.env.example:3-4`), and startup does not reject it. `require_key` accepts whatever is configured (`src/memkit/api.py:150-155`). The API has no per-route authorization, rate limiting, or owner-bound identity; all data and paid operations are behind one bearer-like static key. Docs/OpenAPI are exposed by default (`src/memkit/config.py:53`; `src/memkit/api.py:122-129`).

Loopback is a strong default and keeps this conditional. If host/Qdrant/CORS are changed, fail startup unless a high-entropy key and an explicit exposure acknowledgement are supplied; compare keys with `secrets.compare_digest`; put TLS/auth/rate limits at a reverse proxy; disable docs in exposed deployments; never expose Qdrant directly.

### R3 — Cost accounting can understate or misprice provider charges

- A provider exception before usage metadata leaves `in_tok=out_tok=0`, so the logged cost is zero (`src/memkit/judge.py:422-459`) even if a provider billed work before failing.
- Several selectable model prices are explicitly placeholders (`src/memkit/judge.py:74-90`; rendered at `docs/04-judge.md:14-25`).
- Prices are hard-coded and date-dependent; there is no provider billing reconciliation or alert on model/rate drift.
- Consolidation and re-extraction have independent loops and no shared `max_calls`/reservation policy. API consolidation exposes no call cap (`src/memkit/admin.py:1034-1074`).

Record “cost unknown” distinctly from zero, reconcile periodically against provider billing, make unverified prices opt-in, pin an effective-date price catalog, and apply both a reservation ceiling and explicit per-job call cap.

### R4 — Process-local maintenance state is unsafe for multi-process/CLI operation

`reindex_lock`, `reindex_job`, and `index_dirty` live only in FastAPI process memory (`src/memkit/api.py:106-112`). They disappear on restart and are invisible to `memkit reindex`, scheduled consolidation, a second Uvicorn worker, or another service instance. Re-extraction and consolidation also run as ordinary request transactions without a global job lease (`src/memkit/admin.py:1009-1024,1058-1074`).

Deployment currently appears single-process, so this was not reproduced across workers. Make leases, outbox state, dirty state, and job history durable in SQLite; reject unsupported `--workers > 1` until that exists.

### R5 — Retention and deletion semantics create a broad local privacy footprint

- Raw messages are explicitly never deleted (`src/memkit/db.py:48-66`; `docs/02-data-model.md:44-48`). There is no retention/redaction endpoint (`docs/02-data-model.md:187-190`).
- Full raw user text is duplicated into Qdrant (`src/memkit/store.py:71-81`), and full memory text is duplicated in Qdrant payloads (`src/memkit/store.py:333-378`).
- The API/dashboard exposes transcripts, model outputs, provenance, and paths to anyone with the one key.

This may be an intentional single-user replay policy, but it needs explicit retention/backup threat modeling. Add export/delete/retention controls, document both SQLite and Qdrant copies, recommend encrypted disks/backups and restrictive `.env`/DB permissions, and ensure deletion/outbox operations cover every replica.

### R6 — Migration and database-domain controls are operationally fragile

The v3 rebuild is careful and tested. Remaining risks are:

- Every service startup automatically runs schema creation/migration (`src/memkit/api.py:98-107`; `src/memkit/db.py:165-177`) with only `PRAGMA user_version`, no preflight backup/maintenance mode or migration history/checksum.
- Base `executescript(SCHEMA)` precedes versioned steps (`src/memkit/db.py:165-177`); unlike the v3 rebuild, its entire evolution is not represented as individually named migrations.
- Database constraints enforce provenance and task workflow, but not memory type/scope/status/numeric ranges (`src/memkit/db.py:84-130`). Corrupt values therefore survive non-HTTP write paths.
- There is no downgrade path; documentation relies on a manually gzipped backup (`README.md:119-133`; `docs/02-data-model.md:115-140`).

Adopt ordered, checksumed migrations; expose preflight and backup/restore verification; run `foreign_key_check` and domain audits after every migration; add the missing CHECK constraints. Keep the excellent rollback test pattern.

### R7 — API error/idempotency semantics remain ambiguous outside verified V2

- Successful semantic search is coupled to a SQLite telemetry write (`src/memkit/api.py:384-410`); a locked/broken database can turn already-computed results into a 500.
- Background extraction errors are logged after `/v1/messages` already returns 201 (`src/memkit/api.py:196-247`). This is reasonable async behavior, but clients lack a stable extraction job/status ID.
- Session close drains an unbounded number of remote-call windows synchronously (`src/memkit/api.py:250-301`), while the Hermes caller uses a 30-second timeout (`integrations/hermes/memkit/client.py:163-166`). The client can time out while server work and spending continue.
- Pydantic models use default extra-field ignoring. Typos in mutation bodies can become silent no-ops rather than 422s.
- Bulk deliberately returns partial success but its per-ID failure/atomicity semantics are only implicit (`src/memkit/mutate.py:385-412`).

Decouple retrieval telemetry via an outbox/best-effort metric, make long operations asynchronous jobs with idempotency keys and cancellation/call caps, set `extra="forbid"`, and document partial-success status/error schemas.

### R8 — Retrieval quality has known, measured limitations

The repository is commendably explicit about these; they should not be mistaken for a met exit gate:

- On 31 shared cases, extracted facts score recall@10 **0.84 vs 0.90** and MRR **0.728 vs 0.790** for raw turns; they win strongly on token efficiency. The written stage-2 absolute gate was not met (`docs/measurements.md:143-163`).
- Retrieval is dense-only; the sparse/BM25 slot is declared but unused (`src/memkit/vectors.py:49-62`; `docs/05-retrieval.md:45-53`). Exact identifiers, error strings, and rare names are likely weak cases.
- There is intentionally no similarity floor. Qdrant returns `k` results even for unrelated queries (`docs/05-retrieval.md:145-151`). The eval has zero “not a memory question” and zero degenerate-query cases (`docs/08-testing.md:132-157`), so irrelevant memory injection is unmeasured.
- Unkeyed task facts are admitted for every task/project and controlled only by two-day recency decay (`src/memkit/retrieval.py:160-182,199-248`). Extraction always creates task scope with no task key (`src/memkit/extract.py:309-320`), so unrelated current work can cross task boundaries.
- Read-path dedup at 0.90 is known to miss a genuine paraphrase measured at 0.8979 (`src/memkit/config.py:61-69`).
- Token counting is `len(text)//3` (`src/memkit/retrieval.py:61-63,355-381`), not the downstream model tokenizer. `budget_tokens=0` means unlimited (`src/memkit/retrieval.py:365-366`) even though the API accepts zero without documenting that sentinel.

Add the missing negative/stale/many-relevant cases first. Then measure lexical+dense fusion, task keys, a calibrated abstention/floor, and tokenizer-aware budgets against both MRR and false-context rate. Preserve the current diagnostics endpoint for explaining changes.

### R9 — Performance is acceptable at current scale but has hard serialization points

- All embedding calls share one global lock (`src/memkit/embed.py:48-67,77-93`). This protects MPS but lets imports/reindex/consolidation block latency-sensitive search.
- Startup constructs `SentenceTransformer(model_name)` without a pinned model revision or offline-only setting (`src/memkit/embed.py:48-67`). A missing cache can turn startup into a network download and a mutable model tag can silently change vectors.
- Current Qdrant search is brute force; measurements explicitly warn current latency will not hold at 10,000 facts (`docs/measurements.md:213-225`).
- Search-preview diagnostics issues a second Qdrant query (`src/memkit/retrieval.py:461-493`), appropriate for admin use but costly at scale.
- Existing local dashboard output is 7.4 MiB because sourcemaps are enabled (`web/vite.config.ts:28-31`); largest maps are 1.75 MiB and 1.70 MiB. Main React/charts chunks are about 394 KiB each. Route lazy loading/manual chunks are good, but maps should not ship by default.
- Sessions/Judge Runs request and render 100 rows without pagination controls/virtualization (`web/src/routes/Sessions.tsx:23-52`; `web/src/routes/JudgeRuns.tsx:27-52`).

Pin the embedding repository revision and record it with Qdrant generation metadata. Separate interactive/background embedding queues, batch background work, establish p95 budgets, enable HNSW from measured corpus thresholds, and exclude production sourcemaps or publish them privately.

### R10 — Observability is rich for judge decisions but thin for service reliability

Strengths: every completed provider call records model/version/output/tokens/cost/latency (`src/memkit/judge.py:385-469`), the dashboard exposes backlog/cost/drift, and provenance links facts to messages.

Gaps:

- Logs are unstructured and have no request/job correlation IDs, metrics, tracing, or alert rules.
- `index_dirty` is transient/coarse and inconsistently set; count drift cannot detect a same-count wrong ID/payload.
- Qdrant helpers suppress errors (`src/memkit/vectors.py:64-73,166-177`), erasing root cause.
- Backlog has count/estimate but no oldest age, lease state, retry distribution, or outbox lag.
- No provider-bill reconciliation, remaining reserved budget, or alert near ceiling.
- Launchd logs have no rotation (`deploy/ai.memkit.consolidate.plist:49-52`).

Add structured logs and stable error codes, request/job/window IDs, Prometheus/OpenTelemetry or a minimal `/metrics`, durable outbox/lease/budget metrics, oldest-backlog and provider-error alerts, generation/checksum sampling, and explicit log retention.

### R11 — Deployment and supply-chain reproducibility needs hardening

- Compose uses mutable `qdrant/qdrant:latest` (`docker-compose.yml:1-12`) with no healthcheck, resource limits, or explicit version/schema compatibility policy.
- The embedding model is not revision-pinned (R9).
- `uv.lock`/`pnpm-lock.yaml` are present and validate, but published Python dependency specifiers are lower bounds with no upper compatibility limits (`pyproject.toml:5-17`).
- No CI exists (`docs/08-testing.md:223-224`), so locks, wheel contents, migrations, lint, and docs depend on manual execution.
- Launchd uses author-specific absolute paths and `/tmp` logs (`deploy/ai.memkit.consolidate.plist:27-36,49-60`).

Pin Qdrant by version/digest; add healthcheck, backup/restore and upgrade runbooks, resource ceilings, SBOM/dependency scanning, signed/reproducible release artifacts, and fresh-machine installation tests.

### R12 — Frontend credential handling and request lifecycle are adequate only for trusted loopback

- The API key persists in `localStorage` and is attached by JavaScript (`web/src/api/client.ts:1-34`); any future same-origin XSS/dependency compromise can read it. No CSP appears in `web/index.html:1-14`.
- `api()` supplies no timeout/AbortSignal policy (`web/src/api/client.ts:26-50`); views can wait indefinitely and stale route requests cannot be cancelled centrally.
- The key dialog persists the candidate key before validation and has no pending guard (`web/src/components/AppShell.tsx:74-112`), permitting duplicate submissions.
- Session and Judge Runs filter state is component-local, not URL state (`web/src/routes/Sessions.tsx:23-30`; `web/src/routes/JudgeRuns.tsx:27-33`), reducing reproducible operations links.
- Clipboard calls often announce success without handling rejection (`web/src/routes/Memories.tsx:323`; `web/src/routes/JudgeRuns.tsx:83`; `web/src/routes/Sessions.tsx:84`).

For the loopback threat model, keep the no-cookie/custom-header design and add a strict CSP, dependency hygiene, request cancellation/timeouts, pending guards, URL filter schemas, and error-aware clipboard feedback. Revisit credential storage before any remote hosting.

### R13 — Test coverage is strong in quantity but misses the highest-risk boundaries

The docs candidly list many gaps (`docs/08-testing.md:209-224`): CLI untested, importer traversal untested, provider parsers mock-only, two frontend logic files/no component tests, no OpenAPI drift enforcement, no CI. Additional gaps revealed by this audit:

- rollback after a Qdrant mutation and crash/repair of the reverse ordering;
- reindex drop failure and post-build verification;
- the call that crosses budget plus concurrent reservations across all paid job kinds;
- writer availability while the provider is slow;
- task/message mutation during reindex;
- bulk value domains and `set_scope` extra fields;
- filtered session totals;
- whitespace/maximum payloads;
- cross-owner session reuse/close;
- central outbound secret scrubbing;
- read-time validity exclusion;
- installed-wheel `/ui` and Hermes smoke tests.

The Python suite emits a `StarletteDeprecationWarning` recommending `httpx2`; leaving warnings ungoverned can hide future breakage. Ruff is configured (`pyproject.toml:30-32`) but absent from the environment/dependency groups, so `.venv/bin/ruff check --no-cache .` cannot run.

---

## Opportunities and recommended order

### P0 — Release blockers

1. **Introduce durable leases/outbox/reservations as one data-consistency project.** Short SQLite transaction claims work and reserves cost; cloud/embedding work happens outside; a second short transaction commits source changes plus index outbox; an idempotent worker applies Qdrant. This addresses V1, V2, V4, V5, much of V6, and R4 rather than patching each route.
2. **Make reindex fail closed and generation-based.** Never swallow drop errors; validate exact post-build invariants; atomically switch aliases; replay later outbox entries; persist job state.
3. **Close bulk and core input validation.** Strict discriminated request types, trimmed/bounded strings, database CHECKs, and a one-time invalid-row audit.
4. **Repair release packaging.** Package-relative resources, deterministic frontend build, bundled Hermes assets, and clean-wheel smoke tests.
5. **Move secret protection to the last local boundary before providers.** Retain Hermes' structural “no tool results” rule, but do not trust adapters or prompt instructions as the central privacy control.

### P1 — Correctness and operability

1. Enforce read-time validity and stored-session ownership.
2. Make all maintenance/paid work durable asynchronous jobs with IDs, call caps, cancellation semantics, and history.
3. Correct session counts, detailed health/readiness, and stale Operations UI.
4. Add structured logs/metrics and alerts for outbox lag, oldest backlog, budget reservations, provider errors, and index generation drift.
5. Pin Qdrant and the embedding model revision; document tested upgrade pairs and restore drills.

### P2 — Quality and developer experience

1. Establish CI: Python 3.12 offline suite with warnings policy, generated docs, Ruff/type checks; frontend lint/typecheck/test; clean wheel/install smoke; optional real-Qdrant integration job.
2. Replace the empty OpenAPI placeholder with generated types actually consumed by the client.
3. Add component accessibility/keyboard tests and fix the concrete controls in V16.
4. Expand retrieval evaluation with abstention, stale, exact-identifier, degenerate, many-relevant, and cross-task cases before tuning thresholds/hybrid search.
5. Add retention/export/delete controls and a written privacy/threat model for local transcripts, backups, Qdrant copies, and provider transmission.

### Acceptance invariants for the repair

The next release should mechanically prove all of these:

1. Rolling back any SQLite mutation leaves Qdrant unchanged; crashing after commit leaves a durable pending outbox entry that eventually converges.
2. A successful rebuild has exactly the active memory IDs and eligible raw IDs from one declared SQLite snapshot; any failed precondition leaves the old generation active.
3. `actual_spend + active_reservations` never exceeds the configured ceiling, including concurrent extract/reextract/consolidate jobs.
4. A 30-second provider stall does not block an unrelated SQLite write for provider latency.
5. Every write path shares the same maintenance/validation/owner checks.
6. Secrets matching the central policy never reach the provider stub from direct API, importer, Hermes, re-extraction, or consolidation paths.
7. A wheel installed outside the repository serves `/ui/` and installs Hermes into a temporary home.

---

## Test and static-check transcript

### Backend and docs

```console
$ PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s tests -t .
...
Ran 399 tests in 13.849s

OK

$ PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m tools.docblocks --check
all 8 generated doc blocks match the code

$ .venv/bin/ruff check --no-cache .
.venv/bin/ruff: no such file or directory
```

The suite was offline by design; its harness blanks all provider credential aliases and asserts none survived (`tests/httpharness.py:34-101`).

### Frontend

```console
$ cd web && pnpm exec tsc -p tsconfig.app.json --noEmit --incremental false
# exit 0, no output

$ cd web && pnpm test
Test Files  2 passed (2)
Tests       6 passed (6)
Duration    2.28s

$ cd web && pnpm lint
> eslint .

Oops! Something went wrong! :(

ESLint: 9.39.5
ESLint couldn't find an eslint.config.(js|mjs|cjs) file.
ELIFECYCLE Command failed with exit code 2.
```

### Locks, dependencies, and deployment syntax

```console
$ uv lock --check
Resolved 98 packages in 7ms

$ uv pip check
Checked 77 packages in 2ms
All installed packages are compatible

$ plutil -lint deploy/ai.memkit.consolidate.plist deploy/ai.memkit.service.plist
deploy/ai.memkit.consolidate.plist: OK
deploy/ai.memkit.service.plist: OK
```

`deploy/ai.memkit.service.plist` is not tracked, so its successful syntax check does not make it part of a clean checkout.

---

## Reproduction appendix

All scripts below are offline and use temporary SQLite databases plus repository test stubs. `PYTHONDONTWRITEBYTECODE=1` avoids writing bytecode into the checkout.

### A. Uncommitted Qdrant point and hard-ceiling overrun

```console
$ PYTHONDONTWRITEBYTECODE=1 .venv/bin/python - <<'PY'
import json
from unittest.mock import patch
from memkit import judge, providers, store
from memkit.db import transaction
from tests.fixtures import OWNER, StubEmbedder, StubQdrant, make_db

conn = make_db(); q = StubQdrant()
try:
    with transaction(conn):
        store.add_memory(conn, q, StubEmbedder(), owner_id=OWNER,
            text='rolled back', type='fact')
        raise RuntimeError('force rollback')
except RuntimeError:
    pass
print('rollback_split_brain', json.dumps({
    'sqlite_memories': conn.execute('SELECT COUNT(*) FROM memories').fetchone()[0],
    'qdrant_points': len(q.points),
}))

cost_conn = make_db()
fake = providers.ProviderResult(operations=[], raw={'operations': []},
    input_tokens=1000, output_tokens=0)
with patch.object(providers, 'call', return_value=fake):
    result = judge.extract(cost_conn, window=[], candidates=[],
        monthly_limit_usd=0.000001, gemini_api_key='offline-stub')
print('cost_ceiling', json.dumps({
    'limit': 0.000001,
    'call_cost': result.cost_usd,
    'month_spend': judge.month_spend_usd(cost_conn),
    'error': result.error,
}))
PY
rollback_split_brain {"sqlite_memories": 0, "qdrant_points": 1}
cost_ceiling {"limit": 1e-06, "call_cost": 0.0003, "month_spend": 0.0003, "error": null}
```

### B. HTTP validation, pagination, reindex guard, and health disclosure

```console
$ PYTHONDONTWRITEBYTECODE=1 .venv/bin/python - <<'PY'
import json
from tests.httpharness import ApiTestCase

case = ApiTestCase(methodName='runTest'); case.setUp()
try:
    mem = case.seed_memory()
    bulk = case.client.post('/v1/admin/memories/bulk', headers=case.auth,
        json={'ids': [mem], 'op': 'set_type', 'value': 'not-a-memory-type'})
    bad_type = case.db.execute(
        'SELECT type FROM memories WHERE id=?', (mem,)
    ).fetchone()[0]
    blank = case.client.post('/v1/memories', headers=case.auth,
        json={'text': '   ', 'type': 'fact'})
    blank_len = case.db.execute(
        'SELECT length(text) FROM memories WHERE id=?', (blank.json()['id'],)
    ).fetchone()[0]
    case.seed_message(session_id='pending')
    case.seed_message(session_id='done')
    case.db.execute("UPDATE messages SET processed=1 WHERE session_id='done'")
    case.db.commit()
    filtered = case.client.get(
        '/v1/admin/sessions?has_unprocessed=true', headers=case.auth
    ).json()
    case.set_reindex_running()
    task = case.client.post('/v1/admin/tasks', headers=case.auth,
        json={'text': 'created during rebuild'})
    health = case.client.get('/healthz')
    print('http_contracts', json.dumps({
        'bulk_invalid_status': bulk.status_code,
        'bulk_invalid_stored_type': bad_type,
        'empty_memory_status': blank.status_code,
        'empty_memory_stored_length': blank_len,
        'filtered_session_items': len(filtered['items']),
        'filtered_session_total': filtered['total'],
        'task_during_reindex_status': task.status_code,
        'unauth_health_status': health.status_code,
        'unauth_health_db': health.json()['db'],
    }))
finally:
    case.doCleanups()
PY
http_contracts {"bulk_invalid_status": 200, "bulk_invalid_stored_type": "not-a-memory-type", "empty_memory_status": 201, "empty_memory_stored_length": 3, "filtered_session_items": 1, "filtered_session_total": 2, "task_during_reindex_status": 201, "unauth_health_status": 200, "unauth_health_db": "/var/folders/.../memkit-case-.../t.db"}
```

The `StarletteDeprecationWarning` emitted before this output is omitted here for readability and recorded under test risks.

### C. Message commit followed by index failure and ineffective idempotent retry

```console
$ PYTHONDONTWRITEBYTECODE=1 .venv/bin/python - <<'PY'
import json
from unittest.mock import patch
from tests.httpharness import ApiTestCase

case = ApiTestCase(methodName='runTest'); case.setUp()
try:
    body = {
        'session_id': 's-index-fail', 'role': 'user',
        'content': 'a durable user turn long enough to index',
        'external_source': 'audit', 'external_id': 'turn-1',
    }
    first_error = None
    with patch.object(case.qdrant, 'upsert',
                      side_effect=RuntimeError('qdrant offline')):
        try:
            case.client.post('/v1/messages', headers=case.auth, json=body)
        except Exception as exc:
            first_error = type(exc).__name__ + ': ' + str(exc)
    retry = case.client.post('/v1/messages', headers=case.auth, json=body)
    print('ingest_commit_before_index', json.dumps({
        'first_error': first_error,
        'sqlite_messages': case.scalar(
            "SELECT COUNT(*) FROM messages WHERE external_id='turn-1'"
        ),
        'retry_status': retry.status_code,
        'retry_deduplicated': retry.json()['deduplicated'],
        'raw_qdrant_points': len(case.qdrant.raw_points),
        'index_dirty': case.client.get('/healthz').json()['index_dirty'],
    }))
finally:
    case.doCleanups()
PY
ingest_commit_before_index {"first_error": "RuntimeError: qdrant offline", "sqlite_messages": 1, "retry_status": 201, "retry_deduplicated": true, "raw_qdrant_points": 0, "index_dirty": false}
```

### D. Reindex retaining stale points after a swallowed drop error

```console
$ PYTHONDONTWRITEBYTECODE=1 .venv/bin/python - <<'PY'
import json
from unittest.mock import patch
from memkit import store
from memkit.db import transaction
from tests.fixtures import OWNER, StubEmbedder, StubQdrant, make_db

conn = make_db(); q = StubQdrant(); emb = StubEmbedder()
with transaction(conn):
    store.add_memory(conn, q, emb, owner_id=OWNER,
                     text='active fact', type='fact')
with transaction(conn):
    stale = store.add_memory(conn, q, emb, owner_id=OWNER,
                             text='expired fact', type='fact')
with transaction(conn):
    conn.execute("UPDATE memories SET status='expired' WHERE id=?", (stale,))
with patch.object(q, 'delete_collection',
                  side_effect=RuntimeError('drop denied')):
    reported = store.reindex(conn, q, emb)
print('reindex_swallowed_drop', json.dumps({
    'reported_memories': reported['memories'],
    'sqlite_active': conn.execute(
        "SELECT COUNT(*) FROM memories WHERE status='active'"
    ).fetchone()[0],
    'qdrant_points_after': len(q.points),
    'stale_point_survived': stale in q.points,
}))
PY
reindex_swallowed_drop {"reported_memories": 1, "sqlite_active": 1, "qdrant_points_after": 2, "stale_point_survived": true}
```

### E. Provider latency occupying SQLite's single writer

```console
$ PYTHONDONTWRITEBYTECODE=1 .venv/bin/python - <<'PY'
import json, tempfile, threading, time
from pathlib import Path
from unittest.mock import patch
from memkit import extract, judge, store
from memkit.db import connect, ensure_owner, ensure_session, init_db, transaction, utcnow
from tests.fixtures import OWNER, StubEmbedder, StubQdrant

path = Path(tempfile.mkdtemp(prefix='memos-lock-')) / 'lock.db'
init_db(path)
seed = connect(path)
ensure_owner(seed, OWNER, 'test'); ensure_session(seed, 's-1', OWNER, 'chat')
seed.executemany(
    "INSERT INTO messages(session_id,role,content,created_at) "
    "VALUES('s-1','user',?,?)",
    [(f'durable fact {i}', utcnow()) for i in range(10)],
)
seed.commit(); seed.close()
extract_conn, ingest_conn = connect(path), connect(path)
entered = threading.Event(); extraction_errors = []

def slow_judge(*args, **kwargs):
    entered.set(); time.sleep(11)
    return judge.JudgeResult([], None, 100, 20, .001, 11000)

def first():
    try:
        with transaction(extract_conn):
            extract.run_extraction(
                extract_conn, StubQdrant(), StubEmbedder(),
                session_id='s-1', owner_id=OWNER, agent_id='chat',
                monthly_limit_usd=15, force=True,
            )
    except Exception as exc:
        extraction_errors.append(type(exc).__name__ + ': ' + str(exc))

with patch.object(judge, 'extract', side_effect=slow_judge):
    thread = threading.Thread(target=first); thread.start(); entered.wait(3)
    started = time.monotonic(); write_error = None
    try:
        with transaction(ingest_conn):
            store.add_message(ingest_conn, session_id='s-2', owner_id=OWNER,
                agent_id='chat', role='user', content='concurrent request')
    except Exception as exc:
        write_error = type(exc).__name__ + ': ' + str(exc)
    elapsed = time.monotonic() - started
    thread.join()
print('judge_holds_sqlite_writer', json.dumps({
    'concurrent_write_seconds': round(elapsed, 2),
    'concurrent_write_error': write_error,
    'extraction_errors': extraction_errors,
}))
PY
judge_holds_sqlite_writer {"concurrent_write_seconds": 11.24, "concurrent_write_error": null, "extraction_errors": []}
```

### F. Stored-session owner versus extraction owner

```console
$ PYTHONDONTWRITEBYTECODE=1 .venv/bin/python - <<'PY'
import json
from unittest.mock import patch
from memkit import api, extract
from tests.httpharness import ApiTestCase

case = ApiTestCase(methodName='runTest'); case.setUp()
try:
    created = case.client.post('/v1/messages', headers=case.auth, json={
        'session_id': 'owner-session', 'owner_id': 'owner-a',
        'agent_id': 'chat', 'role': 'user',
        'content': 'remember my timezone is UTC',
    })
    seen = []
    def fake_run(*args, **kwargs):
        seen.append(kwargs['owner_id'])
        return extract.ExtractionOutcome()
    with patch.object(api, 'judge_configured', return_value=True), \
         patch.object(api.extract, 'run_extraction', side_effect=fake_run):
        closed = case.client.post(
            '/v1/sessions/owner-session/close?owner_id=owner-b', headers=case.auth
        )
    stored = case.db.execute(
        "SELECT owner_id FROM sessions WHERE id='owner-session'"
    ).fetchone()[0]
    print('cross_owner_close', json.dumps({
        'created_status': created.status_code,
        'close_status': closed.status_code,
        'session_owner': stored,
        'extract_owner': seen[0],
    }))
finally:
    case.doCleanups()
PY
cross_owner_close {"created_status": 201, "close_status": 200, "session_owner": "owner-a", "extract_owner": "owner-b"}
```

### G. Fresh-archive wheel contents

```console
$ audit_tmp=$(mktemp -d /tmp/memos-audit-build.XXXXXX)
$ git archive --format=tar HEAD | tar -xf - -C "$audit_tmp"
$ uv build --wheel --out-dir "$audit_tmp/out" "$audit_tmp"
Building wheel...
Successfully built /tmp/memos-audit-build.../out/memkit-0.1.0-py3-none-any.whl

$ python3 - <<'PY' "$audit_tmp/out/memkit-0.1.0-py3-none-any.whl"
import sys, zipfile
with zipfile.ZipFile(sys.argv[1]) as z:
    names = z.namelist()
print({
    'files': len(names),
    'web_dist_files': sum('/web_dist/' in n for n in names),
    'hermes_integration_files': sum('integrations/hermes' in n for n in names),
})
PY
{'files': 25, 'web_dist_files': 0, 'hermes_integration_files': 0}
```

Extracting that wheel and invoking `cmd_install_hermes` with a temporary Hermes home produced:

```text
provider source not found at /private/tmp/integrations/hermes/memkit
wheel_install_hermes_return 1
```

### H. Read-only state check

```console
$ git diff --check
# exit 0, no output

$ git status --short
?? .idea/
?? deploy/ai.memkit.service.plist
```

Those two entries existed before the audit and were not changed. The report itself is outside the repository at `/tmp/memos-engineering-audit.md`.

---

## Final disposition

The repository is **not release-ready as a dependable source-of-truth memory service** until V1–V7 are corrected and protected by failure-injection/clean-artifact tests. The architecture does not need replacement: the existing `MutationResult` post-commit pattern, strong migration tests, provenance model, and explicit retrieval measurements are sound building blocks. The highest-leverage change is to make cross-store indexing, paid-work claiming, and budget accounting durable SQLite state instead of in-process sequencing.

---

## Independent validation addendum

A later independent three-agent pass confirmed the main findings and added four source-verified defects:

1. **HIGH — cross-owner mutation:** extraction UPDATE/DELETE selects by memory ID and active status without `owner_id` (`src/memkit/extract.py:357-367,407-414`). A temporary-database probe changed owner B's memory during owner A's extraction.
2. **HIGH — session identity collision:** `ensure_session` silently accepts an existing session ID with a different owner/agent (`src/memkit/db.py:327-338`). A probe submitted owner-B input into an owner-A session and observed storage under owner A.
3. **HIGH — raw-secret cloud egress:** normal user text from the Claude importer and generic message API is not centrally redacted before judge prompts are sent to Gemini/Anthropic (`src/memkit/importers/claude_code.py:112-127,159-189`; `src/memkit/providers.py:218-225,274-285`). Output instructions do not protect provider input.
4. **MEDIUM — silent Anthropic data loss:** a non-refusal Anthropic response without the required tool block returns no error and zero operations (`src/memkit/providers.py:230-237`); extraction can then mark the window processed.

The same pass found source-package inclusion controls weak enough for unrelated untracked `.idea` content and the machine-specific service plist to enter an sdist. These addendum findings strengthen the release-blocking conclusion; they do not change the recommended outbox/lease/budget architecture.
