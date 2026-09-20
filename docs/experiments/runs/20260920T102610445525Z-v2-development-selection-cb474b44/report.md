# v2 development selection

Decision: **observe**. Technology: Jev. Models: jev-1.13.0.

Improve reference resolution and relation criteria while retaining labels and thresholds.

Labels: author-labeled; not independently reviewed. Data: synthetic. Split: dev; repeats: 2 (not independent examples).

## Results

```json
{
  "cases": 100,
  "service_errors": 0,
  "support": {
    "n": 40,
    "accuracy": 0.95,
    "true_positive": 12,
    "false_positive": 0,
    "false_negative": 2,
    "precision": 1.0,
    "recall": 0.8571428571428571
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
    "correct": 35
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
  "input_tokens": 59748,
  "output_tokens": 4970,
  "median_request_ms": 360.19129199848976
}
```

## Limits and decision context

- Development was used for selection and cannot certify generalization.
- Historical artifacts without recorded execution provenance are explicitly marked unknown; archive-time source hashes do not reconstruct that history.

[Exact results](artifact.json) · [Provenance and slices](manifest.json)
