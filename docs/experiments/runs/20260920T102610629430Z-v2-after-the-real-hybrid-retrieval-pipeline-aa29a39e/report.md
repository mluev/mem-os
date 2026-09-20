# v2 after the real hybrid retrieval pipeline

Decision: **adopt**. Technology: Jev. Models: BAAI/bge-m3, jev-1.13.0.

Reduce irrelevant context after hybrid retrieval while preserving useful facts.

Labels: author-labeled; not independently reviewed. Data: synthetic. Split: diagnostic-hybrid; repeats: 1 (not independent examples).

## Results

```json
{
  "baseline": {
    "queries": 24,
    "answerable": 12,
    "top1_correct": 12,
    "relevant_retained": 21,
    "relevant_total": 21,
    "unanswerable": 12,
    "correct_abstentions": 0,
    "irrelevant_returned": 334
  },
  "filtered": {
    "queries": 24,
    "answerable": 12,
    "top1_correct": 12,
    "relevant_retained": 21,
    "relevant_total": 21,
    "unanswerable": 12,
    "correct_abstentions": 12,
    "irrelevant_returned": 0
  },
  "service_errors": 0
}
```

## Limits and decision context

- Adopt only as an explicit experimental local configuration. Twenty-four reused synthetic queries; PostgreSQL and BGE are real, Qdrant uses its local exact engine. No real-user, server-ANN or load claim.
- Historical artifacts without recorded execution provenance are explicitly marked unknown; archive-time source hashes do not reconstruct that history.

[Exact results](artifact.json) · [Provenance and slices](manifest.json)
