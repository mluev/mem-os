# Experiment record

Every live semantic run automatically saves a new folder under ignored
`data/experiments/`. Each folder holds exact results, a machine-readable manifest,
and a readable report. The reviewed **synthetic** runs below are also retained in
this repository, including unsuccessful variants. Repeating a run never replaces
an archived one.

The common format is independent of Jev: another model or technology supplies its
results and metrics to `eval.reports.archive`, with a dataset identity, model IDs,
code provenance, labels, a hypothesis, limitations and a decision. Missing historical
execution provenance stays unknown; archival provenance is recorded separately.

## Retained experiments

| Experiment | Decision |
| --- | --- |
| [Initial v1 adapter failure](runs/20260920T102610403106Z-initial-v1-adapter-failure-a8718cad/report.md) | reject |
| [v1 with corrected response parsing](runs/20260920T102610424606Z-v1-with-corrected-response-parsing-e17c70a1/report.md) | observe |
| [v2 development selection](runs/20260920T102610445525Z-v2-development-selection-cb474b44/report.md) | observe |
| [v3 support wording](runs/20260920T102610466307Z-v3-support-wording-de8cbfc8/report.md) | reject |
| [v4 binary support](runs/20260920T102610486875Z-v4-binary-support-553d5b2c/report.md) | reject |
| [v2 first heldout](runs/20260920T102610507534Z-v2-first-heldout-31d2d6ad/report.md) | observe |
| [v2 hard evidence gate](runs/20260920T102610528881Z-v2-hard-evidence-gate-b7499ddb/report.md) | reject |
| [v3 hard evidence gate](runs/20260920T102610547778Z-v3-hard-evidence-gate-da44c2dc/report.md) | reject |
| [v4 hard evidence gate](runs/20260920T102610566718Z-v4-hard-evidence-gate-d3a315c4/report.md) | reject |
| [v2 across fictional user scenarios](runs/20260920T102610586176Z-v2-across-fictional-user-scenarios-830225b8/report.md) | observe |
| [v2 evidence with date and entity context](runs/20260920T102610611761Z-v2-evidence-with-date-and-entity-context-fd22f2db/report.md) | reject |
| [v2 after the real hybrid retrieval pipeline](runs/20260920T102610629430Z-v2-after-the-real-hybrid-retrieval-pipeline-aa29a39e/report.md) | adopt |
| [v2 batched duplicate guard](runs/20260920T102610645574Z-v2-batched-duplicate-guard-8e7d5483/report.md) | adopt |

## Running and comparing

```bash
# Validates both contents and stored artifact hashes; no model calls.
uv run python -m eval.reports check docs/experiments/runs

# Refuses comparison when dataset, split, thresholds or label source differ.
uv run python -m eval.reports compare PATH_TO_RUN_A PATH_TO_RUN_B

# The same runner accepts another model pin and a labeled external corpus.
uv run python -m eval.semantic --corpus PATH_TO_PRIVATE_CORPUS --split dev --version v2 --model MODEL_ID
```

To retain another technology's report, use `eval.reports archive INPUT_JSON` with
`--name`, `--technology`, `--hypothesis`, `--decision`, `--limitation`,
`--data-class` and `--label-source`. A private input must stay in private storage;
public repository archives accept synthetic data only. Merely redacting a real
user's text does not make it a public fixture.

For new experiments, freeze labels and splits before running. Record language,
scenario and pseudonymous cohort slices. Tune on development; reserve independent
users/scenarios for confirmation. Compare the whole workflow, record outages
separately from wrong answers, and include both gains and regressions. Repeated
requests measure variability and do not create independent examples. Historical
models should be compared on identical input snapshots with independently reviewed
labels before promotion beyond an experimental configuration.

See [Jev controls and commands](jev.md), [corpus definitions](../../eval/corpora/README.md),
and [measurements](../measurements.md#modular-semantic-blocks-and-durable-reports).

## Context detail experiments

[Results, tradeoffs and implementation](context-details.md). Exact synthetic artifacts are gzip-compressed without loss; archive validation checks the decompressed JSON hash.

| Experiment | Decision |
| --- | --- |
| [Context development: original score and strict compaction](runs/20260920T111219748781Z-context-development-original-score-and-strict-compaction-5cb415d0/report.md) | reject |
| [Context development: contribution in batches of ten](runs/20260920T111220199142Z-context-development-contribution-in-batches-of-ten-9794cc8f/report.md) | observe |
| [Context development: contribution and compaction selection](runs/20260920T111220606688Z-context-development-contribution-and-compaction-selection-37ad7aea/report.md) | observe |
| [Context confirmation: frozen contribution policy](runs/20260920T111221048175Z-context-confirmation-frozen-contribution-policy-0dc8e20e/report.md) | adopt |
| [Context runtime: actual facts and user messages](runs/20260920T111221471552Z-context-runtime-actual-facts-and-user-messages-74dac87f/report.md) | adopt |
| [Contribution retrieval: previous corpus regression](runs/20260920T111221754410Z-contribution-retrieval-previous-corpus-regression-cdee6fa6/report.md) | adopt |
| [Context diagnostic: source priority and token budgets](runs/20260920T111221774190Z-context-diagnostic-source-priority-and-token-budgets-125125a2/report.md) | observe |
| [Duplicate width diagnostic: no policy promotion](runs/20260920T111221797830Z-duplicate-width-diagnostic-no-policy-promotion-f09001fa/report.md) | reject |

| Additional regression | Decision |
| --- | --- |
| [Budget-aware compaction, recorded judgments](runs/20260920T113215964755Z-context-budget-aware-compaction-regression-27300a4e/report.md) | observe; no new model calls |
