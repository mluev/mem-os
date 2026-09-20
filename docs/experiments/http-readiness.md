# HTTP context readiness diagnostic

## Measured result: 20 September 2026

The final runs completed **680 measured HTTP requests with no HTTP errors,
content-budget violations, or result-limit violations**. This supports the
structural behavior of the tested read path. It does not establish that the
default ranking is ready for every user: the ordinary fact response retained
20/25 labeled details, and all five representations failed the strict retrieval
abstention check on all six unique questions with no labeled answer. Here,
abstention means returning empty context, not an answer-generating model refusing
to answer.

All runs used unchanged `neutral-v1`, 256 distractor memories, native PostgreSQL
**17.4 with fsync on**, local **Metal/MPS** BGE-M3, and the pinned Qdrant 1.18.2
server. The main runs used a 160-token content budget and limit 30, two repeats,
and concurrency 1, 4, and 8. The small-budget diagnostic used 32 tokens, limit 1,
one repeat, and concurrency 4. No paid provider was called, candidate policy was
introduced, or shipping ranking default was changed.

Counts below represent one pass over each split's unique queries; repeats and
concurrency levels produced the same quality counts.

| Representation | Dev details | Dev irrelevant items | Heldout details | Heldout irrelevant items |
| --- | ---: | ---: | ---: | ---: |
| Facts | 9/12 | 55 | 11/13 | 56 |
| Facts + sources | 9/12 | 57 | 11/13 | 57 |
| Facts + raw evidence | 12/12 | 49 | 13/13 | 51 |
| Facts + raw evidence + sources | 12/12 | 49 | 13/13 | 52 |
| Semantic-provider outage fallback | 12/12 | 49 | 13/13 | 52 |

Raw evidence recovered reasons, exceptions, and the historical database detail
that short facts omitted. Sources alone did not recover those details under this
budget: facts fill the budget before optional citations. More evidence improved
coverage but still returned substantial irrelevant context. These are baseline
quality gaps, not reasons to promote an untested threshold. A future ranking or
packing change needs declared quality gates and fresh independent heldout data.

Heldout request latency and throughput showed a plateau at concurrency 4–8:

| Representation | p95 ms, concurrency 1 | p95 ms, concurrency 4 | p95 ms, concurrency 8 | Requests/s, concurrency 4 → 8 |
| --- | ---: | ---: | ---: | ---: |
| Facts | 65 | 191 | 357 | 22.43 → 22.26 |
| Facts + sources | 67 | 199 | 358 | 21.60 → 22.63 |
| Facts + raw evidence | 74 | 203 | 385 | 20.77 → 21.24 |
| Facts + raw evidence + sources | 74 | 210 | 381 | 21.08 → 21.04 |
| Semantic-provider outage fallback | 84 | 215 | 411 | 19.73 → 19.52 |

These are short local bursts, not CPU VPS capacity estimates. At 32 tokens and
limit 1, all five variants still respected both bounds and retained 6/12 dev
details. The smaller context did not fix abstention.

The final archives contain **300 dev**, **330 heldout**, and **50 small-budget**
observations. Each records `code_changed_during_run=false`, no fixture retries,
the same corpus hash, source hash, and resolved policy hash captured before
requests. The runtime checkpoint was `f1e523d`, with the fixture-retry runner
change separately captured by the working-copy source fingerprint:

- Corpus SHA-256: `66c01a81d9675404b37f12b3ef67ef30e10861ecd9cac7a0deab87864f11fde4`.
- Source SHA-256: `b167ae4386b520a54c401351d9ac34f9024b9628040b142d184ecae5b938fc27`.
- Policy SHA-256: `d8b0a11c3def66efe045080107f006ee4b6d33fd3b4e0b58a5adb1335981839e`.

Exact results and provenance:

- [Final dev run](runs/20260920T130418055331Z-http-readiness-dev-5bf35cde/report.md).
- [Final heldout run](runs/20260920T130455862632Z-http-readiness-heldout-6f9201ad/report.md).
- [32-token, limit-1 run](runs/20260920T130524112493Z-http-readiness-dev-08915b8e/report.md).
- [Earlier dev run](runs/20260920T125953417794Z-http-readiness-dev-4705e724/report.md),
  whose latency overlapped another focused test run and is excluded from the
  timing summary above. It had the same quality counts and no measured failures.

A separate early attempt stopped on a fixture-write HTTP 503 before measurement.
The startup worker's maintenance pruning can temporarily refuse writes. Setup
now retries only the explicit maintenance response with `Retry-After`, at most
five times, records every retry, and exposes every other failure. Measured
searches are never retried. The final three runs required no such setup retry.

## Reproduce and interpret

`eval/readiness_http.py` measures the real HTTP application with the pinned
BGE-M3 revision, a Qdrant 1.18.2 server, and disposable PostgreSQL with fsync on.
It creates only fictional data in its own temporary services. Distribution
defaults are used; existing configuration files, storage URLs, and provider keys
are not inherited. Docker, local PostgreSQL binaries, and the Python dependencies
are required. The first run may download the pinned model and container image.

```sh
uv run python -m eval.readiness_http --split dev
uv run python -m eval.readiness_http --split heldout
uv run python -m eval.readiness_http --split dev --budget 32 --limit 1 --concurrency 4 --repeats 1
```

The default run makes no paid provider calls. `--semantic contribution|compact`
is an explicit opt-in requiring `JEV` or `TYPESAFE_API_KEY`. The separate
`semantic_outage` variant injects a failing provider without making a request;
it checks that the ordinary fallback still honors token and result limits.

The frozen [corpus](../../eval/corpora/readiness-v1.json) contains 11 memories,
8 evidence events, and 21 queries in English, Russian, and Uzbek. Scenarios cover
preferences, corrections, exceptions, exact identifiers, historical evidence,
trust, and questions with no answer. Development has 10 queries; heldout has 11.
They share scenario families and are author-labeled, so they are a diagnostic
split, not independent user cohorts. Details receive credit only when both the
record label and the expected text pattern match. This tests retrieval of answer
material, not the correctness of a generated answer.

Facts, facts with sources, facts with raw evidence, their combination, and a
semantic-provider outage are tested at each requested concurrency. Every
response is checked against the combined content token budget and fact/raw
result limit. Six wrapper tokens per returned content item are included; JSON
transport metadata is not part of this content budget. Reports separately count
HTTP errors, expected details, irrelevant items, correct abstentions, and latency.
Repeats measure timing variation and are not additional independent examples.

Archives default to ignored `data/experiments`. `--output docs/experiments/runs`
can preserve these synthetic results in the repository. Archives include the
corpus hash, resolved policy and its hash captured before any measured requests,
model revision, container image ID, source fingerprints before and after the
run, request-level observations, and aggregate metrics. A nonzero exit means an
HTTP or budget/limit failure; a zero exit does **not** certify retrieval quality.

`--candidate-policy path.json` evaluates a separate immutable policy in the
temporary database. Declare and check it on development data before opening
heldout. The runner never promotes policies or changes shipping defaults. Once
heldout results have been inspected, further tuning needs a fresh heldout set.

These short local bursts expose queueing and throughput plateaus, not sustained
production capacity. The index is small; using a real Qdrant server does not
prove approximate-neighbor recall without an exact-neighbor comparison. Memory
creation and correction use HTTP, but extraction quality is excluded: evidence
links are fixture data, and no paid extractor runs. Readiness also requires the
separate authorization, migration, recovery, and concurrency regression suites.
