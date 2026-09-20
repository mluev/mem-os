# Context confirmation: frozen contribution policy

Decision: **adopt**. Technology: Jev. Models: BAAI/bge-m3, jev-1.13.0.

Evidence-aware selection preserves reasons and exceptions at a fixed context budget.

Labels: author-labeled; not independently reviewed. Data: synthetic. Split: confirmation; repeats: 1 (not independent examples).

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
    "errors": 0
  },
  "facts_jev": {
    "queries": 24,
    "details_retained": 1,
    "details_expected": 40,
    "fully_answerable_contexts": 0,
    "irrelevant_items": 5,
    "redundant_items": 0,
    "correct_empty": 8,
    "unanswerable": 8,
    "mean_context_tokens": 9.583333333333334,
    "provider_ms_sum_p50": 384.27866699930746,
    "provider_ms_sum_p95": 1018.3523750019958,
    "estimated_usd": 0.004348806,
    "new_estimated_usd": 0.004348806,
    "errors": 0
  },
  "wide_facts_jev": {
    "queries": 24,
    "details_retained": 8,
    "details_expected": 40,
    "fully_answerable_contexts": 0,
    "irrelevant_items": 0,
    "redundant_items": 15,
    "correct_empty": 8,
    "unanswerable": 8,
    "mean_context_tokens": 23.125,
    "provider_ms_sum_p50": 746.4509989949875,
    "provider_ms_sum_p95": 1069.0789999935078,
    "estimated_usd": 0.007171080000000001,
    "new_estimated_usd": 0.007171080000000001,
    "errors": 0
  },
  "evidence_hybrid": {
    "queries": 24,
    "details_retained": 27,
    "details_expected": 40,
    "fully_answerable_contexts": 9,
    "irrelevant_items": 79,
    "redundant_items": 49,
    "correct_empty": 0,
    "unanswerable": 8,
    "mean_context_tokens": 154.625,
    "provider_ms_sum_p50": 0,
    "provider_ms_sum_p95": 0,
    "estimated_usd": 0.0,
    "new_estimated_usd": 0.0,
    "errors": 0
  },
  "evidence_jev": {
    "queries": 24,
    "details_retained": 30,
    "details_expected": 40,
    "fully_answerable_contexts": 9,
    "irrelevant_items": 2,
    "redundant_items": 0,
    "correct_empty": 8,
    "unanswerable": 8,
    "mean_context_tokens": 38.875,
    "provider_ms_sum_p50": 390.358999997261,
    "provider_ms_sum_p95": 468.95141700224485,
    "estimated_usd": 0.005457396000000001,
    "new_estimated_usd": 0.005457396000000001,
    "errors": 0
  },
  "evidence_batches": {
    "queries": 24,
    "details_retained": 36,
    "details_expected": 40,
    "fully_answerable_contexts": 13,
    "irrelevant_items": 1,
    "redundant_items": 14,
    "correct_empty": 8,
    "unanswerable": 8,
    "mean_context_tokens": 59.041666666666664,
    "provider_ms_sum_p50": 740.5211250006687,
    "provider_ms_sum_p95": 1139.88041599805,
    "estimated_usd": 0.00799113,
    "new_estimated_usd": 0.00799113,
    "errors": 0
  },
  "evidence_compact": {
    "queries": 24,
    "details_retained": 36,
    "details_expected": 40,
    "fully_answerable_contexts": 13,
    "irrelevant_items": 1,
    "redundant_items": 4,
    "correct_empty": 8,
    "unanswerable": 8,
    "mean_context_tokens": 51.208333333333336,
    "provider_ms_sum_p50": 851.0562089941232,
    "provider_ms_sum_p95": 2627.5052079945453,
    "estimated_usd": 0.009057342000000001,
    "new_estimated_usd": 0.001066212,
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
      "input_tokens": 24612,
      "new_input_tokens": 24612,
      "estimated_usd": 0.0010337039999999999,
      "new_estimated_usd": 0.0010337039999999999,
      "provider_ms_sum": 18071.87079400319
    }
  }
}
```

## Limits and decision context

- Eight authored scenario families per split; queries within a family are dependent.
- Separate experimental rows for evidence; not a production raw-message retrieval benchmark.
- Local exact Qdrant and disposable PostgreSQL; no production ANN/load claim.
- Cached calls reuse identical judgments. Summed provider latency is not end-to-end latency.
- Adoption means an explicit experimental code/configuration option, not a production rollout or universal accuracy claim.

[Exact results](artifact.json.gz) · [Provenance and slices](manifest.json)
