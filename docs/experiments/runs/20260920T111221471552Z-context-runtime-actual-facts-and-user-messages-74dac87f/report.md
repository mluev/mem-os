# Context runtime: actual facts and user messages

Decision: **adopt**. Technology: Jev. Models: jev-1.13.0.

The real facts-plus-user-passages path retains the offline context-selection gain.

Labels: author-labeled; not independently reviewed. Data: synthetic. Split: runtime-diagnostic-confirmation; repeats: 1 (not independent examples).

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
    "wall_ms_p50": 126.26124999223975,
    "wall_ms_p95": 170.48787500243634
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
    "wall_ms_p50": 129.29116599843837,
    "wall_ms_p95": 173.7642920052167
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
    "new_estimated_usd": 0.010123512000000001,
    "errors": 0,
    "wall_ms_p50": 1008.3179999928689,
    "wall_ms_p95": 1226.5968749998137
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
    "estimated_usd": 0.011220468,
    "new_estimated_usd": 0.001096956,
    "errors": 0,
    "wall_ms_p50": 176.32374999811873,
    "wall_ms_p95": 2483.920124992437
  }
}
```

## Limits and decision context

- Already opened synthetic scenarios; this is an integration diagnostic.
- Real separate memory/raw collections with local exact Qdrant; no server ANN/load claim.
- Reported wall time includes lookup and selection but excludes service startup.
- Cached judgments, if present, reduce observed wall time; cache hits are recorded.
- Adoption means an explicit experimental code/configuration option, not a production rollout or universal accuracy claim.

[Exact results](artifact.json.gz) · [Provenance and slices](manifest.json)
