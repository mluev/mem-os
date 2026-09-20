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
    "wall_ms_p50": 59.85,
    "wall_ms_p95": 67.85,
    "requests_per_second": 16.68
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
    "wall_ms_p50": 178.52,
    "wall_ms_p95": 197.74,
    "requests_per_second": 21.49
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
    "wall_ms_p50": 358.72,
    "wall_ms_p95": 371.4,
    "requests_per_second": 21.39
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
    "wall_ms_p50": 58.75,
    "wall_ms_p95": 64.07,
    "requests_per_second": 17.15
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
    "wall_ms_p50": 181.43,
    "wall_ms_p95": 199.83,
    "requests_per_second": 21.09
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
    "wall_ms_p50": 369.52,
    "wall_ms_p95": 382.18,
    "requests_per_second": 20.81
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
    "wall_ms_p50": 66.87,
    "wall_ms_p95": 76.87,
    "requests_per_second": 14.67
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
    "wall_ms_p50": 196.59,
    "wall_ms_p95": 204.98,
    "requests_per_second": 19.69
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
    "wall_ms_p50": 383.35,
    "wall_ms_p95": 404.31,
    "requests_per_second": 20.04
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
    "wall_ms_p50": 67.29,
    "wall_ms_p95": 77.8,
    "requests_per_second": 14.73
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
    "wall_ms_p50": 191.59,
    "wall_ms_p95": 205.55,
    "requests_per_second": 20.14
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
    "wall_ms_p50": 394.58,
    "wall_ms_p95": 412.84,
    "requests_per_second": 19.42
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
    "wall_ms_p50": 71.1,
    "wall_ms_p95": 84.3,
    "requests_per_second": 14.1
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
    "wall_ms_p50": 202.08,
    "wall_ms_p95": 218.81,
    "requests_per_second": 18.95
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
    "wall_ms_p50": 414.05,
    "wall_ms_p95": 427.53,
    "requests_per_second": 18.61
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
