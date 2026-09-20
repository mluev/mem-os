# Context development: contribution in batches of ten

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
    "redundant_items": 21,
    "correct_empty": 8,
    "unanswerable": 8,
    "mean_context_tokens": 28.666666666666668,
    "provider_ms_sum_p50": 1658.8591240069945,
    "provider_ms_sum_p95": 2698.271624998597,
    "estimated_usd": 0.007655256,
    "new_estimated_usd": 0.007655256,
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
    "redundant_items": 21,
    "correct_empty": 8,
    "unanswerable": 8,
    "mean_context_tokens": 62.5,
    "provider_ms_sum_p50": 1610.8569170028204,
    "provider_ms_sum_p95": 2512.9619159924914,
    "estimated_usd": 0.00875175,
    "new_estimated_usd": 0.00875175,
    "errors": 0
  },
  "evidence_compact": {
    "queries": 24,
    "details_retained": 36,
    "details_expected": 40,
    "fully_answerable_contexts": 13,
    "irrelevant_items": 0,
    "redundant_items": 21,
    "correct_empty": 8,
    "unanswerable": 8,
    "mean_context_tokens": 62.5,
    "provider_ms_sum_p50": 1843.6630830183276,
    "provider_ms_sum_p95": 4187.136289991031,
    "estimated_usd": 0.010061688000000001,
    "new_estimated_usd": 0.0011811660000000002,
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
