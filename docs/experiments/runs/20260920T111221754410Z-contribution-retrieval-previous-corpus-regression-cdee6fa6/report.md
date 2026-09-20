# Contribution retrieval: previous corpus regression

Decision: **adopt**. Technology: Jev. Models: BAAI/bge-m3.

Semantic filtering removes irrelevant hybrid results without losing useful context.

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

- Synthetic reused diagnostic cases, not a new independent heldout set.
- Real PostgreSQL and BGE; local exact Qdrant, not server ANN or load behavior.
- Adoption means an explicit experimental code/configuration option, not a production rollout or universal accuracy claim.

[Exact results](artifact.json.gz) · [Provenance and slices](manifest.json)
