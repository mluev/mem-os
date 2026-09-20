# Production readiness implementation — 20 September 2026

For the consolidated branch, current artifact bundle, and integration follow-ups,
start with the [final handoff](../releases/2026-09-20-handoff.md). This review records
the original readiness checkpoint and its measurements.

Scope: one self-hosted production team. PostgreSQL remains authoritative and Qdrant remains rebuildable. No production service was changed. Work started from the remote `master` at `b4204ef`; this repository has no `main` branch. Changes are on `codex/production-readiness` in the separate `mem-os-readiness` worktree.

## Readiness judgment

The implementation is ready for release-candidate review; unrestricted production readiness is not established. Storage, authorization, recovery and context-boundary regressions are verified below. The real-model diagnostic still returns substantial irrelevant context and never returns empty context for its unanswerable questions. Ranking improvements need a separate evaluation with fresh heldout data. Deployment-host recovery and sustained CPU capacity remain unmeasured.

## Implemented

| Plan area | Delivered behavior |
| --- | --- |
| Connections and work | Request/operation connection ownership; expiring lease fences for writes, renewal, index delivery and completion; periodic recovery during index outages; startup/recovery provisioning; cooperative cancellation without follow-on extraction jobs. |
| Maintenance and erasure | One consistent maintenance gate; stable generation build and payload validation before alias activation; stale deliveries reload authoritative state; retryable erasure that survives deletion of its user and cleans all managed generations and exports. |
| Backup and recovery | Persistent backup/export volumes; full archive decoding; isolated restore drill; durable external erasure receipts; offline v1 upgrade/replay; fail-closed checks when receipt history is missing. |
| Memory and context | Subject filtering/clearing; shared eligibility before bounded selection; conservative identity for dedup/merge; revision rechecks after inference; generated wording returned to review; current versus historical citations; one final content budget and result limit. |
| Service and clients | Four real domain routers, separate HTTP dependencies/schema/job dispatcher, no route re-parenting; typed OpenAPI response authority; generated dashboard transport types; corrected audit, timing, session and index displays; old SDK imports and dictionary reads retained. |
| Agent integration | Lightweight `memos` default; server-side `memkit` retained; unchanged shared adapter source in both distributions; transport wrappers preserve old installations and cursors; bounded evidence flush before Hermes session close; explicit scope refusal remains a failure. |
| Measurement | Frozen multilingual HTTP corpus; actual BGE-M3, Qdrant server and PostgreSQL; detail/irrelevance/abstention, provider cost, small budgets, request limits and concurrent bursts. No ranking default or embedding-model change. |

Independent review also found and repaired permission loss during queued work, private entity lookup/alias writes, inaccessible text in review attention, and global budget information exposed to members. Regression tests reproduced each issue before repair. Real-server tests caught numeric filter behavior that the local Qdrant engine did not reproduce.

## Verification

Final checks on 20 September 2026:

| Check | Result |
| --- | --- |
| Full Python backend and CLI suite, PostgreSQL 16.15 and Qdrant 1.18.2 | 926 tests and 142 subtests passed; no skips; 85.56% backend coverage. |
| Added real-HTTP client isolation checks on PostgreSQL 16.15 | 3 tests and 4 subtests passed; standalone CLI, Python SDK and TypeScript SDK. |
| Dashboard | 79 unit tests and 11 browser tests passed; lint, type checking and production build passed. |
| Contracts and architecture | All existing operation IDs, paths, tag behavior and generated-contract checks passed; adapter source synchronization and documentation checks passed. |
| Evaluation integrity | Golden and semantic corpus schemas passed; all 26 retained experiment archives verified. |
| Packages | Server, standalone CLI, Python SDK and TypeScript package built and passed clean-install/consumer checks. |
| Dependency audits | Locked Python requirements and JavaScript packages reported no known vulnerabilities. |
| Restore and persistence | Actual PostgreSQL archive restore, pre-erasure receipt replay, and backup/export volume survival across container replacement passed. |

The full suite finished before the three additional client tests were collected; these are 929 distinct Python tests and 146 subtests in total, not a sum of repeated focused runs. Test warnings concerned framework/client deprecations and the intentionally limited local Qdrant engine; separate Qdrant-server tests passed.

Reproduce the Python gate using disposable PostgreSQL/Qdrant services and PostgreSQL client tools matching the server major version:

```sh
MEMKIT_TEST_DATABASE_URL="$DISPOSABLE_TEST_DATABASE_URL" \
MEMKIT_QDRANT_INTEGRATION=1 \
MEMKIT_QDRANT_TEST_URL="$DISPOSABLE_TEST_QDRANT_URL" \
uv run pytest -q --cov=memkit --cov-report=term --cov-fail-under=75
```

Dashboard commands are `pnpm --dir web lint`, `typecheck`, `test`, `test:e2e`, and `build`. The complete standing checks and disposable service setup are in [CI](../../.github/workflows/ci.yml) and [testing](../08-testing.md).

Scenarios exercised include more concurrent requests than available connections, obsolete workers and index claims, a killed process with an uncommitted write, reindex cancellation/corruption, accepted erasure failures and retries, changed artifact paths, pre-erasure backup restoration, shared-subject preservation, correction during inference, legacy and revision-bound citations, current permission loss, and every raw/source/provider-failure combination under small budgets.

A complete fresh-install and populated-v1 journey runs capture → recall → correction → review → archive/restore → export through authenticated HTTP with real PostgreSQL and local Qdrant. Separate HTTP measurements use a Qdrant server and real embeddings. CLI/SDK installation and dashboard checks cover their own transport boundaries.

## Measured usefulness and capacity

The [frozen HTTP diagnostic](../experiments/http-readiness.md) exercised the shipping policy with pinned BGE-M3, PostgreSQL 17.4 with fsync enabled, and Qdrant 1.18.2. Development, heldout and small-budget runs kept identical source and policy fingerprints. All measured requests respected HTTP, content-budget and combined-result-limit checks. No paid provider was called.

Raw evidence recovered details that facts omitted, including reasons, exceptions and a historical value. However, every representation returned context for every unanswerable query. This measures retrieval abstention, not whether an answer-generating model would refuse to answer. More evidence currently improves coverage while retaining substantial irrelevant material. Shipping ranking and embedding defaults are unchanged.

Concurrent bursts reached a throughput plateau while latency increased. These local MPS measurements do not establish sustained capacity on the deployment CPU. Exact figures, commands and immutable artifacts are in the linked diagnostic.

## Operational boundaries

- Reindex intentionally pauses index-affecting writes. The pause lasts for the full stable rebuild; its duration depends on corpus size and embedding hardware. Reads and job control remain available.
- Dense/raw refill is bounded to four batches. Highly selective residual JSON filters or severe index drift can underfill a result; this is not exhaustive retrieval.
- The context budget includes returned text and six wrapper tokens per item, including quotations. It excludes JSON transport and arbitrary metadata. An oversized item is omitted intact rather than clipped through an exception or negation.
- Legacy citations have no invented revision link. A changed legacy claim does not inherit its predecessor's evidence as current support.
- Erasure intentionally refuses unresolved shared-authorship conflicts. Retained backups keep their existing retention; the latest external erasure manifest must be reapplied to any offline restore. Missing historical receipts require an audited operator baseline.
- Named volumes protect against container replacement, not host loss. Off-host copies, monitoring, TLS configuration and a recovery rehearsal on the actual deployment host remain operator responsibilities.
- The synthetic retrieval corpus is a diagnostic, not independent user traffic or proof of approximate-neighbor recall. Short concurrent bursts do not establish sustained production capacity. Paid extraction and optional semantic-provider quality were not re-evaluated here.

## Upgrade and rollback

Use [the operations runbook](../09-operations.md). Preserve old artifact directories before replacing a container, establish the erasure baseline, take a protected pre-migration backup, and complete the isolated restore drill. Schema v2 is additive; v1 migration history is unchanged.

The [build manifest](../releases/2026-09-20-build.json) records the checksums of the server wheel, standalone CLI wheel, Python SDK wheel, TypeScript package, production requirements and dependency lock. Binaries are retained locally under `dist/readiness/`; they are not published or committed. All packaged application inputs match `f1e523d`. Clean environments verified server/dashboard imports, Hermes installation, standalone CLI installation without server packages, legacy Python SDK imports, and TypeScript consumer compilation.

Application rollback must retain schema-v2 support. An old pre-v2 binary can reject the database. Reinstalling the packaged schema-v2 checkpoint preserves these safety fixes; returning to a pre-v2 database requires offline restoration and erasure replay. The packaged checkpoint is ready to retain as an application rollback build; a complete production container image and host recovery rehearsal are separate deployment checks. Deployment is a separate step.
