# Context diagnostic: source priority and token budgets

Decision: **observe**. Technology: Jev. Models: not recorded.

Compare simple source priority against semantic selection at three fixed budgets.

Labels: author-labeled; not independently reviewed. Data: synthetic. Split: opened-runtime-budget-diagnostic; repeats: 1 (not independent examples).

## Results

```json
{
  "source_first_80": {
    "queries": 24,
    "details_retained": 30,
    "details_expected": 40,
    "fully_answerable_contexts": 10,
    "irrelevant_items": 35,
    "redundant_items": 8,
    "correct_empty": 0,
    "unanswerable": 8,
    "mean_context_tokens": 77.79166666666667,
    "provider_ms_sum_p50": 0,
    "provider_ms_sum_p95": 0,
    "estimated_usd": 0.0,
    "new_estimated_usd": 0.0,
    "errors": 0
  },
  "contribution_80": {
    "queries": 24,
    "details_retained": 27,
    "details_expected": 40,
    "fully_answerable_contexts": 9,
    "irrelevant_items": 0,
    "redundant_items": 7,
    "correct_empty": 8,
    "unanswerable": 8,
    "mean_context_tokens": 37.75,
    "provider_ms_sum_p50": 0,
    "provider_ms_sum_p95": 0,
    "estimated_usd": 0.0,
    "new_estimated_usd": 0.0,
    "errors": 0
  },
  "contribution_source_first_80": {
    "queries": 24,
    "details_retained": 32,
    "details_expected": 40,
    "fully_answerable_contexts": 11,
    "irrelevant_items": 0,
    "redundant_items": 3,
    "correct_empty": 8,
    "unanswerable": 8,
    "mean_context_tokens": 38.583333333333336,
    "provider_ms_sum_p50": 0,
    "provider_ms_sum_p95": 0,
    "estimated_usd": 0.0,
    "new_estimated_usd": 0.0,
    "errors": 0
  },
  "source_first_160": {
    "queries": 24,
    "details_retained": 40,
    "details_expected": 40,
    "fully_answerable_contexts": 16,
    "irrelevant_items": 74,
    "redundant_items": 5,
    "correct_empty": 0,
    "unanswerable": 8,
    "mean_context_tokens": 155.33333333333334,
    "provider_ms_sum_p50": 0,
    "provider_ms_sum_p95": 0,
    "estimated_usd": 0.0,
    "new_estimated_usd": 0.0,
    "errors": 0
  },
  "contribution_160": {
    "queries": 24,
    "details_retained": 36,
    "details_expected": 40,
    "fully_answerable_contexts": 12,
    "irrelevant_items": 0,
    "redundant_items": 16,
    "correct_empty": 8,
    "unanswerable": 8,
    "mean_context_tokens": 59.375,
    "provider_ms_sum_p50": 0,
    "provider_ms_sum_p95": 0,
    "estimated_usd": 0.0,
    "new_estimated_usd": 0.0,
    "errors": 0
  },
  "contribution_source_first_160": {
    "queries": 24,
    "details_retained": 39,
    "details_expected": 40,
    "fully_answerable_contexts": 15,
    "irrelevant_items": 0,
    "redundant_items": 16,
    "correct_empty": 8,
    "unanswerable": 8,
    "mean_context_tokens": 60.583333333333336,
    "provider_ms_sum_p50": 0,
    "provider_ms_sum_p95": 0,
    "estimated_usd": 0.0,
    "new_estimated_usd": 0.0,
    "errors": 0
  },
  "source_first_320": {
    "queries": 24,
    "details_retained": 40,
    "details_expected": 40,
    "fully_answerable_contexts": 16,
    "irrelevant_items": 195,
    "redundant_items": 4,
    "correct_empty": 0,
    "unanswerable": 8,
    "mean_context_tokens": 314.7083333333333,
    "provider_ms_sum_p50": 0,
    "provider_ms_sum_p95": 0,
    "estimated_usd": 0.0,
    "new_estimated_usd": 0.0,
    "errors": 0
  },
  "contribution_320": {
    "queries": 24,
    "details_retained": 39,
    "details_expected": 40,
    "fully_answerable_contexts": 15,
    "irrelevant_items": 0,
    "redundant_items": 21,
    "correct_empty": 8,
    "unanswerable": 8,
    "mean_context_tokens": 70.375,
    "provider_ms_sum_p50": 0,
    "provider_ms_sum_p95": 0,
    "estimated_usd": 0.0,
    "new_estimated_usd": 0.0,
    "errors": 0
  },
  "contribution_source_first_320": {
    "queries": 24,
    "details_retained": 39,
    "details_expected": 40,
    "fully_answerable_contexts": 15,
    "irrelevant_items": 0,
    "redundant_items": 24,
    "correct_empty": 8,
    "unanswerable": 8,
    "mean_context_tokens": 70.375,
    "provider_ms_sum_p50": 0,
    "provider_ms_sum_p95": 0,
    "estimated_usd": 0.0,
    "new_estimated_usd": 0.0,
    "errors": 0
  }
}
```

## Limits and decision context

- Reuses the exact runtime candidates and judgments; no independent new evidence.
- Zero recorded cost means offline replay, not free original semantic inference.

[Exact results](artifact.json.gz) · [Provenance and slices](manifest.json)
