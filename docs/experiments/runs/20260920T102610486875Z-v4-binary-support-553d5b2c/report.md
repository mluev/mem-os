# v4 binary support

Decision: **reject**. Technology: Jev. Models: jev-1.13.0.

Test whether a binary support primitive improves useful-fact retention.

Labels: author-labeled; not independently reviewed. Data: synthetic. Split: dev; repeats: 2 (not independent examples).

## Results

```json
{
  "cases": 100,
  "service_errors": 0,
  "support": {
    "n": 40,
    "accuracy": 0.9,
    "true_positive": 10,
    "false_positive": 0,
    "false_negative": 4,
    "precision": 1.0,
    "recall": 0.7142857142857143
  },
  "citation_only_acceptance": {
    "n": 40,
    "accuracy": 0.35,
    "true_positive": 14,
    "false_positive": 26,
    "false_negative": 0,
    "precision": 0.35,
    "recall": 1.0
  },
  "relation": {
    "n": 36,
    "correct": 34
  },
  "duplicate": {
    "n": 36,
    "accuracy": 0.9444444444444444,
    "true_positive": 6,
    "false_positive": 0,
    "false_negative": 2,
    "precision": 1.0,
    "recall": 0.75
  },
  "retrieval": {
    "n": 24,
    "answerable": 20,
    "top1": 1.0,
    "mrr": 1.0,
    "unanswerable": 4,
    "correct_abstentions": 4,
    "false_empty": 0,
    "relevant_retained": 20,
    "relevant_total": 20
  },
  "cosine_duplicate_at_0.90": {
    "n": 36,
    "accuracy": 0.8333333333333334,
    "true_positive": 4,
    "false_positive": 2,
    "false_negative": 4,
    "precision": 0.6666666666666666,
    "recall": 0.5
  },
  "dense_only_retrieval": {
    "n": 24,
    "answerable": 20,
    "top1": 0.9,
    "mrr": 0.95,
    "unanswerable": 4,
    "correct_abstentions": 0,
    "false_empty": 0,
    "relevant_retained": 20,
    "relevant_total": 20
  },
  "input_tokens": 57468,
  "output_tokens": 4094,
  "median_request_ms": 354.114687499532
}
```

## Limits and decision context

- No sufficient support improvement; heldout was already opened and was not reused for selection.
- Historical artifacts without recorded execution provenance are explicitly marked unknown; archive-time source hashes do not reconstruct that history.

[Exact results](artifact.json) · [Provenance and slices](manifest.json)
