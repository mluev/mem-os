# Jev semantic blocks

Status: three independent runtime blocks and explicit evaluation runners are
implemented. Distributed defaults remain off. The reviewed synthetic results,
including unsuccessful variants, live in the [experiment archive](README.md).
The [opportunity map](../plans/2026-09-20-jev-opportunities.md) describes future
candidates, not a list of completed integrations.

## Runtime controls

Configure `JEV` in the environment or `.env`. `TYPESAFE_API_KEY` is an alternate
name; `JEV` takes precedence. `MEMKIT_JEV_MODEL` defaults to `jev-1.13.0`. A
credential alone activates no calls. Each block has an explicit switch:

| Setting | Modes | Failure behavior |
| --- | --- | --- |
| `MEMKIT_SEMANTIC_DEDUP` | `off`, `shadow`, `verify` | Verify preserves the incoming fact as a new row |
| `MEMKIT_SEMANTIC_RETRIEVAL` | `off`, `shadow`, `rerank`, `filter`, `contribution` | Preserves baseline results and scores |
| `MEMKIT_SEMANTIC_SUPPORT` | `off`, `shadow` | Records an unavailable check; writes continue |
| `MEMKIT_SEMANTIC_CONTEXT` | `off`, `select`, `compact` | Preserves the budgeted facts/passages candidate order |

`MEMKIT_SEMANTIC_VERSION=v2` selects the measured questions.
`MEMKIT_SEMANTIC_DUPLICATE_FLOOR=0.9` and
`MEMKIT_SEMANTIC_RELEVANCE_FLOOR=2.0` select explicit policies. Settings take effect
on service startup. The initial experimental profile used `verify`, `filter`, and
`shadow`, respectively. Editing settings does not restart or deploy a service.

The newer [detail-preserving context experiments](context-details.md) select
`contribution` for retrieval and `compact` for explicit raw-context requests in
the local experimental profile; distributed defaults stay off. Contribution asks
whether a candidate supplies **any** requested detail, avoiding the old score
floor's rejection of useful partial answers to broad queries. Its probability
floor is `MEMKIT_SEMANTIC_CONTRIBUTION_FLOOR=0.7`.

With `include_raw=true` and a context mode enabled, up to 60 authorized fact/user
passage candidates share one selection and the request's token budget. `select`
uses contribution filtering; `compact` also removes high-probability redundancy
against already-kept candidates, with `MEMKIT_SEMANTIC_REDUNDANCY_FLOOR=0.7`.
Compaction never merges or deletes stored memories. Raw passages are quoted user
evidence, not confirmed current facts; their timestamps and source IDs are retained.
Facts remain in `memories`, selected quotations in `raw`. `used_tokens` includes
both text sets and six wrapper tokens per item; supplemental `include_sources`
excerpts also spend that budget. This is a content budget, not a count of every
JSON field in the HTTP response.

The context path re-fetches raw IDs from Postgres and checks current session scope,
user role and requested filters before provider egress. It uses batches of 30,
at most 12 compaction candidates, a five-second deadline checked between calls,
and a three-second per-request provider timeout without retries. The deadline may
overrun by the in-flight request; it is not a hard wall-clock cancellation.
Very long unsplittable turns and text beyond eight source passages are omitted
from this bounded path. The existing raw index length floor still applies.

```bash
uv run python -m eval.context_experiments --split dev --coverage
uv run python -m eval.context_experiments --split confirmation --selection-policy contribution --redundancy-floor .7 --batch-size 30
uv run python -m eval.context_runtime --split confirmation
uv run python -m eval.context_relations
```

The confirmation set is now opened; do not tune on it and call a rerun heldout.

Duplicate verification only vetoes cosine proposals. It cannot broaden the
candidate set, rewrite facts or resolve conflicts. The target must match resolved
scope, subject, context, kind and validity, be live and trusted, and retain its
planned revision when evidence is attached under a short row lock. An unavailable
or uncertain judgment inserts a separate fact. Manual writes are unchanged.

Retrieval authorizes candidates before provider egress: scope, trust, expiry,
request filters and the original relevance floor run first. Shadow observes
without changing output. Rerank changes ordering. Filter also discards candidates
below the usefulness floor. Failures restore the baseline. Reranked scores use
0–3; unchecked tail scores in pure rerank retain their hybrid scale. Filter mode
excludes unchecked tail items. The block cannot rescue missing candidates or
resolve which of two conflicting facts is true.

Support checks use exact cited user spans, with conversation, known entities and
recording date for reference resolution. They never gate or quarantine writes.
Counts appear in the existing scoped job result. Operational observations record
counts, provider/model version, usage and errors without source/query text or
request hashes. The generative provider's monthly budget does not include Jev;
Jev tokens are observed separately.

## Experiments

```bash
# Offline validation; both corpus checks also run in CI.
uv run python -m eval.semantic --schema-only
uv run python -m eval.semantic --schema-only --corpus eval/corpora/multiscenario-v1.json

# Explicit live development runs.
uv run python -m eval.semantic --split dev --version v1 --repeat 2 --embeddings
uv run python -m eval.semantic --split dev --version v2 --repeat 2 --embeddings

# Only after freezing questions and thresholds; this set is already opened.
uv run python -m eval.semantic --split heldout --version v2 --repeat 3 --embeddings

# Fictional development, education and personal-assistant scenarios.
uv run python -m eval.semantic --corpus eval/corpora/multiscenario-v1.json --split heldout --version v2 --repeat 2 --embeddings --data-class synthetic

# Actual batched duplicate block on measured cosine proposals.
uv run python -m eval.semantic_dedup

# Real hybrid fusion in disposable Postgres, BGE and local exact Qdrant.
uv run python -m eval.semantic_hybrid

# Identical cached generative outputs; regenerate only with --refresh.
uv run python -m eval.semantic_extraction --version v2 --state-version minimal --output data/jev/extractor-v2-minimal.json
uv run python -m eval.semantic_extraction --version v2 --state-version anchored --output data/jev/extractor-v2-anchored.json

# Offline provider contracts, authorization, revision races and report integrity.
uv run pytest -q tests/test_semantic.py tests/test_semantic_retrieval.py tests/test_semantic_blocks.py tests/test_experiment_reports.py
uv run python -m eval.reports check docs/experiments/runs
```

Working outputs live under ignored `data/jev/`. Every live run also saves an
immutable archive under `data/experiments/`, with exact answers, errors, hashes,
resolved models, source identity, thresholds, usage, slices and a readable report.
Reviewed synthetic runs are retained in `docs/experiments/runs/`. Private external
corpora and reports must remain in controlled storage with retention/erasure
rules; never put credentials in arguments or artifacts.

`--model` selects another TypeSafe model pin; `--corpus` accepts another labeled
JSON corpus and records its language/scenario/cohort slices. The common
`eval.reports.archive` interface also accepts other technologies' results. Failed
variants are retained, not silently replaced. Unknown historical execution
provenance stays unknown; archival provenance is recorded separately.

Support/equivalence decisions use the probability of that condition, not Choice
confidence. Noul has no separate confidence. Service errors are distinct from
negative judgments. Repetitions probe variability and are not independent cases.
The new corpus has 72 probes derived from 12 related scenario families, not 72
independent users. See [corpus definitions](../../eval/corpora/README.md).

## Reusable components

`semantic.SemanticClient` defines typed provider judgments. `JevClient` handles
redaction, bounded HTTP retries, response validation, pinned model identity and
sanitized errors. `semantic_runtime.SemanticBlocks` composes those judgments into
independent workflow policies. `JevReranker` implements the existing retrieval
interface and may also be passed directly to `retrieval.explain`.

```python
from memkit.semantic import JevClient
from memkit.semantic_runtime import SemanticBlocks

with JevClient(api_key, model="jev-1.13.0") as client:
    blocks = SemanticBlocks(client, version="v2", dedup="verify", retrieval="filter")
    # The caller authorizes inputs first; judgments never grant permissions.
    accepted = blocks.verify_duplicates({
        0: {"existing": "Atlas uses Redis.", "incoming": "Atlas uses PostgreSQL."}
    })
```

v1–v4 questions remain in the registry. v2 was selected on development. v3 and
binary v4 did not rescue support gating. Adding date/entity context also failed
that diagnostic (27 to 14 retained expected facts); support stays advisory.

## Next evidence to collect

Use independently reviewed user cohorts, realistic query distributions, larger
candidate pools and production-style Qdrant ANN. Current hybrid diagnostics show
context filtering gains, not top-1 ranking gains. The duplicate guard improves
precision but misses more true duplicates, which remain as separate rows.

The original Russian development equivalence label about preferring short answers
versus preferring to answer briefly remains ambiguous. It was not relabeled after
observing the model and must not justify autonomous merging. Do not tune on the
already opened heldout sets or lower a threshold merely until an old corpus passes.

## Sources

Current [HTTP API](https://docs.typesafe.ai/api),
[confidence guidance](https://docs.typesafe.ai/confidence),
[reranking cookbook](https://docs.typesafe.ai/cookbooks/rerank_typesafe), and
[citation-checking pattern](https://docs.typesafe.ai/cookbooks/citation_check).
Known limitations: [Jev model notes](https://docs.typesafe.ai/model-jaggedness/jev-1.13).
