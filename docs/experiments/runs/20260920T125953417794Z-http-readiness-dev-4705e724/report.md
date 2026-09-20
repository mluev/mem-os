# http-readiness-dev

Decision: **observe**. Technology: BGE-M3 + PostgreSQL + Qdrant HTTP. Models: BAAI/bge-m3.

The shipping HTTP context path preserves facts and bounds context under concurrent load.

Labels: frozen author-labeled synthetic scenarios; no independent review. Data: synthetic. Split: dev; repeats: 2 (not independent examples).

## Results

```json
{
  "current/facts/concurrency-1": {
    "requests": 20,
    "http_errors": 0,
    "details_found": 18,
    "details_expected": 24,
    "irrelevant_items": 110,
    "unanswerable_queries": 6,
    "correct_abstentions": 0,
    "budget_violations": 0,
    "limit_violations": 0,
    "wall_ms_p50": 55.47,
    "wall_ms_p95": 67.43,
    "requests_per_second": 17.45
  },
  "current/facts/concurrency-4": {
    "requests": 20,
    "http_errors": 0,
    "details_found": 18,
    "details_expected": 24,
    "irrelevant_items": 110,
    "unanswerable_queries": 6,
    "correct_abstentions": 0,
    "budget_violations": 0,
    "limit_violations": 0,
    "wall_ms_p50": 177.77,
    "wall_ms_p95": 194.72,
    "requests_per_second": 21.37
  },
  "current/facts/concurrency-8": {
    "requests": 20,
    "http_errors": 0,
    "details_found": 18,
    "details_expected": 24,
    "irrelevant_items": 110,
    "unanswerable_queries": 6,
    "correct_abstentions": 0,
    "budget_violations": 0,
    "limit_violations": 0,
    "wall_ms_p50": 356.03,
    "wall_ms_p95": 369.27,
    "requests_per_second": 21.53
  },
  "current/sources/concurrency-1": {
    "requests": 20,
    "http_errors": 0,
    "details_found": 18,
    "details_expected": 24,
    "irrelevant_items": 114,
    "unanswerable_queries": 6,
    "correct_abstentions": 0,
    "budget_violations": 0,
    "limit_violations": 0,
    "wall_ms_p50": 62.44,
    "wall_ms_p95": 78.33,
    "requests_per_second": 15.32
  },
  "current/sources/concurrency-4": {
    "requests": 20,
    "http_errors": 0,
    "details_found": 18,
    "details_expected": 24,
    "irrelevant_items": 114,
    "unanswerable_queries": 6,
    "correct_abstentions": 0,
    "budget_violations": 0,
    "limit_violations": 0,
    "wall_ms_p50": 188.63,
    "wall_ms_p95": 197.93,
    "requests_per_second": 20.79
  },
  "current/sources/concurrency-8": {
    "requests": 20,
    "http_errors": 0,
    "details_found": 18,
    "details_expected": 24,
    "irrelevant_items": 114,
    "unanswerable_queries": 6,
    "correct_abstentions": 0,
    "budget_violations": 0,
    "limit_violations": 0,
    "wall_ms_p50": 361.49,
    "wall_ms_p95": 377.88,
    "requests_per_second": 21.1
  },
  "current/raw/concurrency-1": {
    "requests": 20,
    "http_errors": 0,
    "details_found": 24,
    "details_expected": 24,
    "irrelevant_items": 98,
    "unanswerable_queries": 6,
    "correct_abstentions": 0,
    "budget_violations": 0,
    "limit_violations": 0,
    "wall_ms_p50": 65.26,
    "wall_ms_p95": 74.39,
    "requests_per_second": 15.23
  },
  "current/raw/concurrency-4": {
    "requests": 20,
    "http_errors": 0,
    "details_found": 24,
    "details_expected": 24,
    "irrelevant_items": 98,
    "unanswerable_queries": 6,
    "correct_abstentions": 0,
    "budget_violations": 0,
    "limit_violations": 0,
    "wall_ms_p50": 189.93,
    "wall_ms_p95": 199.09,
    "requests_per_second": 20.29
  },
  "current/raw/concurrency-8": {
    "requests": 20,
    "http_errors": 0,
    "details_found": 24,
    "details_expected": 24,
    "irrelevant_items": 98,
    "unanswerable_queries": 6,
    "correct_abstentions": 0,
    "budget_violations": 0,
    "limit_violations": 0,
    "wall_ms_p50": 387.78,
    "wall_ms_p95": 408.21,
    "requests_per_second": 19.77
  },
  "current/context/concurrency-1": {
    "requests": 20,
    "http_errors": 0,
    "details_found": 24,
    "details_expected": 24,
    "irrelevant_items": 98,
    "unanswerable_queries": 6,
    "correct_abstentions": 0,
    "budget_violations": 0,
    "limit_violations": 0,
    "wall_ms_p50": 64.63,
    "wall_ms_p95": 72.92,
    "requests_per_second": 15.3
  },
  "current/context/concurrency-4": {
    "requests": 20,
    "http_errors": 0,
    "details_found": 24,
    "details_expected": 24,
    "irrelevant_items": 98,
    "unanswerable_queries": 6,
    "correct_abstentions": 0,
    "budget_violations": 0,
    "limit_violations": 0,
    "wall_ms_p50": 192.3,
    "wall_ms_p95": 203.36,
    "requests_per_second": 20.21
  },
  "current/context/concurrency-8": {
    "requests": 20,
    "http_errors": 0,
    "details_found": 24,
    "details_expected": 24,
    "irrelevant_items": 98,
    "unanswerable_queries": 6,
    "correct_abstentions": 0,
    "budget_violations": 0,
    "limit_violations": 0,
    "wall_ms_p50": 377.98,
    "wall_ms_p95": 395.94,
    "requests_per_second": 20.18
  },
  "current/semantic_outage/concurrency-1": {
    "requests": 20,
    "http_errors": 0,
    "details_found": 24,
    "details_expected": 24,
    "irrelevant_items": 98,
    "unanswerable_queries": 6,
    "correct_abstentions": 0,
    "budget_violations": 0,
    "limit_violations": 0,
    "wall_ms_p50": 72.66,
    "wall_ms_p95": 83.58,
    "requests_per_second": 13.67
  },
  "current/semantic_outage/concurrency-4": {
    "requests": 20,
    "http_errors": 0,
    "details_found": 24,
    "details_expected": 24,
    "irrelevant_items": 98,
    "unanswerable_queries": 6,
    "correct_abstentions": 0,
    "budget_violations": 0,
    "limit_violations": 0,
    "wall_ms_p50": 226.18,
    "wall_ms_p95": 243.82,
    "requests_per_second": 17.71
  },
  "current/semantic_outage/concurrency-8": {
    "requests": 20,
    "http_errors": 0,
    "details_found": 24,
    "details_expected": 24,
    "irrelevant_items": 98,
    "unanswerable_queries": 6,
    "correct_abstentions": 0,
    "budget_violations": 0,
    "limit_violations": 0,
    "wall_ms_p50": 411.08,
    "wall_ms_p95": 423.18,
    "requests_per_second": 18.73
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
