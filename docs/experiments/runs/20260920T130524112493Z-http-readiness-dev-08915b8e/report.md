# http-readiness-dev

Decision: **observe**. Technology: BGE-M3 + PostgreSQL + Qdrant HTTP. Models: BAAI/bge-m3.

The shipping HTTP context path preserves facts and bounds context under concurrent load.

Labels: frozen author-labeled synthetic scenarios; no independent review. Data: synthetic. Split: dev; repeats: 1 (not independent examples).

## Results

```json
{
  "current/facts/concurrency-4": {
    "requests": 10,
    "http_errors": 0,
    "details_found": 6,
    "details_expected": 12,
    "irrelevant_items": 4,
    "unanswerable_queries": 3,
    "correct_abstentions": 0,
    "budget_violations": 0,
    "limit_violations": 0,
    "wall_ms_p50": 176.5,
    "wall_ms_p95": 222.65,
    "requests_per_second": 20.34
  },
  "current/sources/concurrency-4": {
    "requests": 10,
    "http_errors": 0,
    "details_found": 6,
    "details_expected": 12,
    "irrelevant_items": 4,
    "unanswerable_queries": 3,
    "correct_abstentions": 0,
    "budget_violations": 0,
    "limit_violations": 0,
    "wall_ms_p50": 178.43,
    "wall_ms_p95": 203.3,
    "requests_per_second": 21.13
  },
  "current/raw/concurrency-4": {
    "requests": 10,
    "http_errors": 0,
    "details_found": 6,
    "details_expected": 12,
    "irrelevant_items": 4,
    "unanswerable_queries": 3,
    "correct_abstentions": 0,
    "budget_violations": 0,
    "limit_violations": 0,
    "wall_ms_p50": 181.68,
    "wall_ms_p95": 209.13,
    "requests_per_second": 20.66
  },
  "current/context/concurrency-4": {
    "requests": 10,
    "http_errors": 0,
    "details_found": 6,
    "details_expected": 12,
    "irrelevant_items": 4,
    "unanswerable_queries": 3,
    "correct_abstentions": 0,
    "budget_violations": 0,
    "limit_violations": 0,
    "wall_ms_p50": 178.67,
    "wall_ms_p95": 208.86,
    "requests_per_second": 20.33
  },
  "current/semantic_outage/concurrency-4": {
    "requests": 10,
    "http_errors": 0,
    "details_found": 6,
    "details_expected": 12,
    "irrelevant_items": 4,
    "unanswerable_queries": 3,
    "correct_abstentions": 0,
    "budget_violations": 0,
    "limit_violations": 0,
    "wall_ms_p50": 202.3,
    "wall_ms_p95": 229.22,
    "requests_per_second": 18.87
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
