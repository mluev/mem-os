# Semantic blocks and a durable experiment record

Approved direction: use small replaceable judgments throughout the service and
development, keep measured improvements, and retain experiments for comparisons
across models, technologies, languages and user scenarios.

## Runtime

One provider protocol supplies typed judgments. Three independent blocks consume
them: duplicate verification, retrieval relevance, and advisory evidence support.
Each has an explicit configuration switch. A credential alone activates nothing.

Duplicate verification may veto an existing cosine-based duplicate proposal. It
does not broaden candidate selection or generate mutations. Scope, context,
subject, kind, trust and validity remain deterministic constraints. Resolve
routing before comparison and recheck the target revision under a short row lock
before attaching evidence. Uncertainty or service failure inserts the new fact.

Retrieval supports observation, reordering and a separately selectable relevance
filter. Provider failures return the original candidates. Authorization, trust,
expiry and request filters run first. Evidence support is observation only because
the earlier hard gate lost correct facts. Its state now includes known entities,
the recording date and conversation for reference resolution.

Runtime observations contain counts and provider metadata, never query/fact text
or request hashes. Support counts live in the existing scoped job result. Raw
experimental results are separate from runtime operational logs.

## Experiments

Preserve both successful and rejected variants. Store immutable run directories,
a common manifest, hashes of exact artifacts, code identity, question/dataset
identity, metrics, errors, language/scenario slices, a hypothesis, limitations and
a decision. Keep synthetic detailed artifacts in the repository with readable
reports; private datasets must remain in access-controlled local storage.

Add an independent multi-scenario challenge set. Freeze v2 and its thresholds
before running it. Measure both benefits and lost positives; repeated calls are
not independent examples. Allow external corpora with explicit labels and cohort
metadata so future users and technologies use the same reporting contract.

Alternative considered: enable all judgments as hard gates. Rejected by the
measured evidence-support regression. Alternative considered: keep everything in
standalone scripts. That cannot improve live workflows or exercise integration
boundaries. Explicit blocks with conservative failure policies provide both.

## Validation

Offline tests cover provider failure, authorization before egress, revision races,
same-subject constraints, observation-only behavior and archive integrity. Live
experiments are explicit and use synthetic data. Run the backend suite and record
results in measurements. Do not infer production universality from a small corpus.
