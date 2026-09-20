# HTTP context readiness diagnostic

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
