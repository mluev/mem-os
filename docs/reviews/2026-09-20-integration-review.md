# Context and integration review — 20 September 2026

The branch brings the existing team-memory and standalone-client work together
with optional semantic context selection and the dashboard. The repository's
actual default branch is `master`; there is no `main` branch.

## Repairs from this review

- Context compaction only uses earlier passages that fit the remaining response
  budget and result count. A long rejected passage cannot suppress a short fact.
- Source quotations, source session links, revision history, predecessor/successor
  links and review previews each enforce the reader's scope. Publishing a current
  memory does not publish private source conversations or earlier private wording.
- Ordinary raw search reloads scope, role and text from Postgres, just as the new
  context path does. Stale vector payloads cannot supply quotations or authorize
  access. Query embeddings are still reused.
- The evidence drawer respects failed server verification and interprets legacy
  source offsets as Unicode characters. Missing verification stays unchecked.
- Signing out cancels in-flight queries and clears cached data before another
  identity can enter. Browser coverage reproduces the previous cross-user reuse.
- Operations calls the current report-only extraction endpoint and user-specific
  erasure endpoint. Removed replay/evaluation screens are no longer browser tests.
- Dashboard statistics have real Postgres coverage for empty data, scope isolation,
  reporting windows and the latency tail. P95 now uses nearest rank, matching the
  telemetry endpoint instead of hiding slow requests in small samples.
- Docker copies the dashboard from the actual Vite output path. SDK packaging
  checks use the generated package name rather than an obsolete version.
- Pull requests exercise CLI deployment against an isolated SSH target on the
  disposable CI runner, including backup/restore and unhealthy-image recovery.
- That live check exposed an empty-cache ownership reset: Docker copied the
  image's UID back over the deployment user's initialized model volume. Managed
  model mounts now disable copy-up; a separate Docker check attempts writes from
  two fresh containers before the full remote installation test.

## Dependency repairs

The Python audit found no known vulnerabilities. Frontend overrides update
[nanoid](https://github.com/advisories/GHSA-2v37-7h3g-55p8) and
[js-yaml](https://github.com/advisories/GHSA-2883-xcg3-v3hh); the test runner moves
to the maintained Vitest 4 line for its
[redirect-mock fix](https://github.com/advisories/GHSA-82fw-gwwq-j7x9).

## Experiment boundary

See [the experiment report](../experiments/context-details.md) for paired results,
prices, rejected hypotheses and limitations. A cached rerun after the packing fix
preserves 37/40 expected details, no irrelevant fragments and 8/8 correct empty
answers on the opened fictional integration corpus. It establishes neither new
model accuracy nor new provider latency. Semantic modes remain opt-in in shipped
configuration; no production deployment is part of this PR.

The integrated Linux backend passed 816 tests and 55 subtests (81.04% coverage;
two optional tests skipped). Frontend checks passed 79 unit tests and six browser
tests; Qdrant and clean server/SDK/CLI distributions passed. The original work
was merged as PR #5 before the remote deployment check finished. Its discovered
cache-permission repair and final live verification continue in a follow-up PR.
