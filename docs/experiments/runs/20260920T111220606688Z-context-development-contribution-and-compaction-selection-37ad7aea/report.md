# Context development: contribution and compaction selection

Decision: **observe**. Technology: Jev. Models: BAAI/bge-m3, jev-1.13.0.

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
    "new_estimated_usd": 0.0,
    "errors": 0
  },
  "wide_facts_jev": {
    "queries": 24,
    "details_retained": 8,
    "details_expected": 40,
    "fully_answerable_contexts": 0,
    "irrelevant_items": 0,
    "redundant_items": 22,
    "correct_empty": 8,
    "unanswerable": 8,
    "mean_context_tokens": 29.75,
    "provider_ms_sum_p50": 821.0154580010567,
    "provider_ms_sum_p95": 1605.7175419991836,
    "estimated_usd": 0.0070875,
    "new_estimated_usd": 0.006386394,
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
    "new_estimated_usd": 0.0,
    "errors": 0
  },
  "evidence_batches": {
    "queries": 24,
    "details_retained": 36,
    "details_expected": 40,
    "fully_answerable_contexts": 13,
    "irrelevant_items": 0,
    "redundant_items": 25,
    "correct_empty": 8,
    "unanswerable": 8,
    "mean_context_tokens": 63.333333333333336,
    "provider_ms_sum_p50": 712.8548750042683,
    "provider_ms_sum_p95": 1026.449249999132,
    "estimated_usd": 0.008048922,
    "new_estimated_usd": 0.007625982000000001,
    "errors": 0
  },
  "evidence_compact": {
    "queries": 24,
    "details_retained": 40,
    "details_expected": 40,
    "fully_answerable_contexts": 16,
    "irrelevant_items": 0,
    "redundant_items": 10,
    "correct_empty": 8,
    "unanswerable": 8,
    "mean_context_tokens": 57.041666666666664,
    "provider_ms_sum_p50": 911.0328329916229,
    "provider_ms_sum_p95": 2816.267416004848,
    "estimated_usd": 0.009336432,
    "new_estimated_usd": 0.0010194240000000001,
    "errors": 0
  }
}
```

## Limits and decision context

- Eight authored scenario families per split; queries within a family are dependent.
- Separate experimental rows for evidence; not a production raw-message retrieval benchmark.
- Local exact Qdrant and disposable PostgreSQL; no production ANN/load claim.
- Cached calls reuse identical judgments. Summed provider latency is not end-to-end latency.

[Exact results](artifact.json.gz) · [Provenance and slices](manifest.json)
