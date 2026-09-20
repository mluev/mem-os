# Context development: original score and strict compaction

Decision: **reject**. Technology: Jev. Models: BAAI/bge-m3, jev-1.13.0.

Evidence-aware selection preserves reasons and exceptions at a fixed context budget.

Labels: author-labeled; not independently reviewed. Data: synthetic. Split: dev; repeats: 1 (not independent examples).

## Results

```json
{
  "facts_hybrid": {
    "queries": 24,
    "details_retained": 8,
    "details_expected": 40,
    "fully_answerable_contexts": 0,
    "irrelevant_items": 113,
    "redundant_items": 68,
    "correct_empty": 0,
    "unanswerable": 8,
    "mean_context_tokens": 153.66666666666666,
    "provider_ms_sum_p50": 0,
    "provider_ms_sum_p95": 0,
    "estimated_usd": 0.0,
    "new_estimated_usd": 0.0,
    "errors": 0
  },
  "facts_jev": {
    "queries": 24,
    "details_retained": 2,
    "details_expected": 40,
    "fully_answerable_contexts": 0,
    "irrelevant_items": 1,
    "redundant_items": 6,
    "correct_empty": 8,
    "unanswerable": 8,
    "mean_context_tokens": 11.875,
    "provider_ms_sum_p50": 401.62054100073874,
    "provider_ms_sum_p95": 1175.4004999966128,
    "estimated_usd": 0.004216422,
    "new_estimated_usd": 0.004216422,
    "errors": 0
  },
  "wide_facts_jev": {
    "queries": 24,
    "details_retained": 2,
    "details_expected": 40,
    "fully_answerable_contexts": 0,
    "irrelevant_items": 0,
    "redundant_items": 6,
    "correct_empty": 8,
    "unanswerable": 8,
    "mean_context_tokens": 9.291666666666666,
    "provider_ms_sum_p50": 1472.9471250029746,
    "provider_ms_sum_p95": 1611.6076659891405,
    "estimated_usd": 0.0072681840000000004,
    "new_estimated_usd": 0.0072681840000000004,
    "errors": 0
  },
  "evidence_hybrid": {
    "queries": 24,
    "details_retained": 33,
    "details_expected": 40,
    "fully_answerable_contexts": 11,
    "irrelevant_items": 75,
    "redundant_items": 44,
    "correct_empty": 0,
    "unanswerable": 8,
    "mean_context_tokens": 155.45833333333334,
    "provider_ms_sum_p50": 0,
    "provider_ms_sum_p95": 0,
    "estimated_usd": 0.0,
    "new_estimated_usd": 0.0,
    "errors": 0
  },
  "evidence_jev": {
    "queries": 24,
    "details_retained": 32,
    "details_expected": 40,
    "fully_answerable_contexts": 10,
    "irrelevant_items": 1,
    "redundant_items": 10,
    "correct_empty": 8,
    "unanswerable": 8,
    "mean_context_tokens": 49.458333333333336,
    "provider_ms_sum_p50": 384.63995899655856,
    "provider_ms_sum_p95": 453.8369590009097,
    "estimated_usd": 0.005690706,
    "new_estimated_usd": 0.005690706,
    "errors": 0
  },
  "evidence_batches": {
    "queries": 24,
    "details_retained": 32,
    "details_expected": 40,
    "fully_answerable_contexts": 11,
    "irrelevant_items": 0,
    "redundant_items": 7,
    "correct_empty": 8,
    "unanswerable": 8,
    "mean_context_tokens": 46.291666666666664,
    "provider_ms_sum_p50": 1501.969625998754,
    "provider_ms_sum_p95": 2567.9569999920204,
    "estimated_usd": 0.008312262,
    "new_estimated_usd": 0.008312262,
    "errors": 0
  },
  "evidence_compact": {
    "queries": 24,
    "details_retained": 32,
    "details_expected": 40,
    "fully_answerable_contexts": 11,
    "irrelevant_items": 0,
    "redundant_items": 7,
    "correct_empty": 8,
    "unanswerable": 8,
    "mean_context_tokens": 46.291666666666664,
    "provider_ms_sum_p50": 1906.6431249957532,
    "provider_ms_sum_p95": 3147.987333999481,
    "estimated_usd": 0.00891513,
    "new_estimated_usd": 0.000602868,
    "errors": 0
  },
  "coverage_signal": {
    "cases": 48,
    "missing_detected": 24,
    "missing_total": 24,
    "false_alarms": 1,
    "covered_total": 24,
    "usage": {
      "calls": 48,
      "errors": 0,
      "cache_hits": 0,
      "input_tokens": 24120,
      "new_input_tokens": 24120,
      "estimated_usd": 0.00101304,
      "new_estimated_usd": 0.00101304,
      "provider_ms_sum": 17546.35574898566
    }
  }
}
```

## Limits and decision context

- Eight authored scenario families per split; queries within a family are dependent.
- Separate experimental rows for evidence; not a production raw-message retrieval benchmark.
- Local exact Qdrant and disposable PostgreSQL; no production ANN/load claim.
- Cached calls reuse identical judgments. Summed provider latency is not end-to-end latency.

[Exact results](artifact.json.gz) · [Provenance and slices](manifest.json)
