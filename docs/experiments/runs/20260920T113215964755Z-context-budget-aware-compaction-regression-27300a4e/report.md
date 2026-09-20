# Context budget-aware compaction regression

Decision: **observe**. Technology: Jev. Models: jev-1.13.0.

Removing redundancy against only passages that fit the remaining budget preserves the opened runtime corpus result.

Labels: Frozen authored context-details-v1 facets. Data: synthetic. Split: runtime-diagnostic-confirmation; repeats: 1 (not independent examples).

## Results

```json
{
  "facts_hybrid": {
    "queries": 24,
    "details_retained": 8,
    "details_expected": 40,
    "fully_answerable_contexts": 0,
    "irrelevant_items": 109,
    "redundant_items": 63,
    "correct_empty": 0,
    "unanswerable": 8,
    "mean_context_tokens": 153.125,
    "provider_ms_sum_p50": 0,
    "provider_ms_sum_p95": 0,
    "estimated_usd": 0.0,
    "new_estimated_usd": 0.0,
    "errors": 0,
    "wall_ms_p50": 49.571959003515076,
    "wall_ms_p95": 80.61516599991592
  },
  "raw_hybrid": {
    "queries": 24,
    "details_retained": 34,
    "details_expected": 40,
    "fully_answerable_contexts": 11,
    "irrelevant_items": 70,
    "redundant_items": 32,
    "correct_empty": 0,
    "unanswerable": 8,
    "mean_context_tokens": 156.125,
    "provider_ms_sum_p50": 0,
    "provider_ms_sum_p95": 0,
    "estimated_usd": 0.0,
    "new_estimated_usd": 0.0,
    "errors": 0,
    "wall_ms_p50": 52.667126001324505,
    "wall_ms_p95": 83.57287499529775
  },
  "raw_select": {
    "queries": 24,
    "details_retained": 36,
    "details_expected": 40,
    "fully_answerable_contexts": 12,
    "irrelevant_items": 0,
    "redundant_items": 11,
    "correct_empty": 8,
    "unanswerable": 8,
    "mean_context_tokens": 59.375,
    "provider_ms_sum_p50": 840.2268339996226,
    "provider_ms_sum_p95": 1070.6491250020918,
    "estimated_usd": 0.010123512000000001,
    "new_estimated_usd": 0.0,
    "errors": 0,
    "wall_ms_p50": 53.47733400412835,
    "wall_ms_p95": 84.46004099823767
  },
  "raw_compact": {
    "queries": 24,
    "details_retained": 37,
    "details_expected": 40,
    "fully_answerable_contexts": 13,
    "irrelevant_items": 0,
    "redundant_items": 1,
    "correct_empty": 8,
    "unanswerable": 8,
    "mean_context_tokens": 52.833333333333336,
    "provider_ms_sum_p50": 1042.1941250024247,
    "provider_ms_sum_p95": 3304.4656670026598,
    "estimated_usd": 0.011125884,
    "new_estimated_usd": 0.0,
    "errors": 0,
    "wall_ms_p50": 52.947916999983136,
    "wall_ms_p95": 83.67154099687468
  }
}
```

## Limits and decision context

- Previously opened synthetic corpus; this is regression evidence, not new heldout evidence.
- All model judgments came from exact request caches; no new provider latency or model accuracy is established.
- The oversize-passage failure is covered by deterministic regression tests, not by this corpus.

[Exact results](artifact.json.gz) · [Provenance and slices](manifest.json)
