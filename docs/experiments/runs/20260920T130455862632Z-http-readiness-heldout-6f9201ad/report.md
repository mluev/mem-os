# http-readiness-heldout

Decision: **observe**. Technology: BGE-M3 + PostgreSQL + Qdrant HTTP. Models: BAAI/bge-m3.

The shipping HTTP context path preserves facts and bounds context under concurrent load.

Labels: frozen author-labeled synthetic scenarios; no independent review. Data: synthetic. Split: heldout; repeats: 2 (not independent examples).

## Results

```json
{
  "current/facts/concurrency-1": {
    "requests": 22,
    "http_errors": 0,
    "details_found": 22,
    "details_expected": 26,
    "irrelevant_items": 112,
    "unanswerable_queries": 6,
    "correct_abstentions": 0,
    "budget_violations": 0,
    "limit_violations": 0,
    "wall_ms_p50": 55.04,
    "wall_ms_p95": 65.38,
    "requests_per_second": 17.8
  },
  "current/facts/concurrency-4": {
    "requests": 22,
    "http_errors": 0,
    "details_found": 22,
    "details_expected": 26,
    "irrelevant_items": 112,
    "unanswerable_queries": 6,
    "correct_abstentions": 0,
    "budget_violations": 0,
    "limit_violations": 0,
    "wall_ms_p50": 171.97,
    "wall_ms_p95": 191.19,
    "requests_per_second": 22.43
  },
  "current/facts/concurrency-8": {
    "requests": 22,
    "http_errors": 0,
    "details_found": 22,
    "details_expected": 26,
    "irrelevant_items": 112,
    "unanswerable_queries": 6,
    "correct_abstentions": 0,
    "budget_violations": 0,
    "limit_violations": 0,
    "wall_ms_p50": 343.85,
    "wall_ms_p95": 356.83,
    "requests_per_second": 22.26
  },
  "current/sources/concurrency-1": {
    "requests": 22,
    "http_errors": 0,
    "details_found": 22,
    "details_expected": 26,
    "irrelevant_items": 114,
    "unanswerable_queries": 6,
    "correct_abstentions": 0,
    "budget_violations": 0,
    "limit_violations": 0,
    "wall_ms_p50": 57.36,
    "wall_ms_p95": 66.89,
    "requests_per_second": 17.1
  },
  "current/sources/concurrency-4": {
    "requests": 22,
    "http_errors": 0,
    "details_found": 22,
    "details_expected": 26,
    "irrelevant_items": 114,
    "unanswerable_queries": 6,
    "correct_abstentions": 0,
    "budget_violations": 0,
    "limit_violations": 0,
    "wall_ms_p50": 183.44,
    "wall_ms_p95": 199.12,
    "requests_per_second": 21.6
  },
  "current/sources/concurrency-8": {
    "requests": 22,
    "http_errors": 0,
    "details_found": 22,
    "details_expected": 26,
    "irrelevant_items": 114,
    "unanswerable_queries": 6,
    "correct_abstentions": 0,
    "budget_violations": 0,
    "limit_violations": 0,
    "wall_ms_p50": 335.45,
    "wall_ms_p95": 357.7,
    "requests_per_second": 22.63
  },
  "current/raw/concurrency-1": {
    "requests": 22,
    "http_errors": 0,
    "details_found": 26,
    "details_expected": 26,
    "irrelevant_items": 102,
    "unanswerable_queries": 6,
    "correct_abstentions": 0,
    "budget_violations": 0,
    "limit_violations": 0,
    "wall_ms_p50": 63.1,
    "wall_ms_p95": 74.09,
    "requests_per_second": 15.5
  },
  "current/raw/concurrency-4": {
    "requests": 22,
    "http_errors": 0,
    "details_found": 26,
    "details_expected": 26,
    "irrelevant_items": 102,
    "unanswerable_queries": 6,
    "correct_abstentions": 0,
    "budget_violations": 0,
    "limit_violations": 0,
    "wall_ms_p50": 188.83,
    "wall_ms_p95": 202.95,
    "requests_per_second": 20.77
  },
  "current/raw/concurrency-8": {
    "requests": 22,
    "http_errors": 0,
    "details_found": 26,
    "details_expected": 26,
    "irrelevant_items": 102,
    "unanswerable_queries": 6,
    "correct_abstentions": 0,
    "budget_violations": 0,
    "limit_violations": 0,
    "wall_ms_p50": 355.05,
    "wall_ms_p95": 385.17,
    "requests_per_second": 21.24
  },
  "current/context/concurrency-1": {
    "requests": 22,
    "http_errors": 0,
    "details_found": 26,
    "details_expected": 26,
    "irrelevant_items": 104,
    "unanswerable_queries": 6,
    "correct_abstentions": 0,
    "budget_violations": 0,
    "limit_violations": 0,
    "wall_ms_p50": 61.21,
    "wall_ms_p95": 74.11,
    "requests_per_second": 15.86
  },
  "current/context/concurrency-4": {
    "requests": 22,
    "http_errors": 0,
    "details_found": 26,
    "details_expected": 26,
    "irrelevant_items": 104,
    "unanswerable_queries": 6,
    "correct_abstentions": 0,
    "budget_violations": 0,
    "limit_violations": 0,
    "wall_ms_p50": 180.58,
    "wall_ms_p95": 210.49,
    "requests_per_second": 21.08
  },
  "current/context/concurrency-8": {
    "requests": 22,
    "http_errors": 0,
    "details_found": 26,
    "details_expected": 26,
    "irrelevant_items": 104,
    "unanswerable_queries": 6,
    "correct_abstentions": 0,
    "budget_violations": 0,
    "limit_violations": 0,
    "wall_ms_p50": 368.17,
    "wall_ms_p95": 381.24,
    "requests_per_second": 21.04
  },
  "current/semantic_outage/concurrency-1": {
    "requests": 22,
    "http_errors": 0,
    "details_found": 26,
    "details_expected": 26,
    "irrelevant_items": 104,
    "unanswerable_queries": 6,
    "correct_abstentions": 0,
    "budget_violations": 0,
    "limit_violations": 0,
    "wall_ms_p50": 72.75,
    "wall_ms_p95": 84.12,
    "requests_per_second": 13.76
  },
  "current/semantic_outage/concurrency-4": {
    "requests": 22,
    "http_errors": 0,
    "details_found": 26,
    "details_expected": 26,
    "irrelevant_items": 104,
    "unanswerable_queries": 6,
    "correct_abstentions": 0,
    "budget_violations": 0,
    "limit_violations": 0,
    "wall_ms_p50": 192.91,
    "wall_ms_p95": 214.53,
    "requests_per_second": 19.73
  },
  "current/semantic_outage/concurrency-8": {
    "requests": 22,
    "http_errors": 0,
    "details_found": 26,
    "details_expected": 26,
    "irrelevant_items": 104,
    "unanswerable_queries": 6,
    "correct_abstentions": 0,
    "budget_violations": 0,
    "limit_violations": 0,
    "wall_ms_p50": 396.62,
    "wall_ms_p95": 410.93,
    "requests_per_second": 19.52
  }
}
```

## Limits and decision context

- Synthetic diagnostic; repeated requests do not create independent quality samples.
- Fixture memories are authored and corrected through HTTP; extraction model quality is excluded.
- Source links are seeded directly because the default does not call a paid extractor.
- Single-process local service and a disposable Qdrant server; production topology and long histories differ.
- A Qdrant server run does not establish ANN recall without a separate exact-neighbor comparison.
- The semantic_outage variant injects deterministic provider failure and makes no provider request.
- This report never promotes a candidate policy; tuning after opening heldout requires a fresh heldout corpus.

[Exact results](artifact.json.gz) · [Provenance and slices](manifest.json)
