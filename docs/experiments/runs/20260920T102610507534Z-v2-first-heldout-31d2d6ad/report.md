# v2 first heldout

Decision: **observe**. Technology: Jev. Models: jev-1.13.0.

Check the selected v2 questions on unopened synthetic examples.

Labels: author-labeled; not independently reviewed. Data: synthetic. Split: heldout; repeats: 3 (not independent examples).

## Results

```json
{
  "cases": 114,
  "service_errors": 0,
  "support": {
    "n": 42,
    "accuracy": 1.0,
    "true_positive": 15,
    "false_positive": 0,
    "false_negative": 0,
    "precision": 1.0,
    "recall": 1.0
  },
  "citation_only_acceptance": {
    "n": 42,
    "accuracy": 0.35714285714285715,
    "true_positive": 15,
    "false_positive": 27,
    "false_negative": 0,
    "precision": 0.35714285714285715,
    "recall": 1.0
  },
  "relation": {
    "n": 36,
    "correct": 30
  },
  "duplicate": {
    "n": 36,
    "accuracy": 1.0,
    "true_positive": 9,
    "false_positive": 0,
    "false_negative": 0,
    "precision": 1.0,
    "recall": 1.0
  },
  "retrieval": {
    "n": 36,
    "answerable": 30,
    "top1": 1.0,
    "mrr": 1.0,
    "unanswerable": 6,
    "correct_abstentions": 6,
    "false_empty": 0,
    "relevant_retained": 33,
    "relevant_total": 33
  },
  "cosine_duplicate_at_0.90": {
    "n": 36,
    "accuracy": 0.4166666666666667,
    "true_positive": 0,
    "false_positive": 12,
    "false_negative": 9,
    "precision": 0.0,
    "recall": 0.0
  },
  "dense_only_retrieval": {
    "n": 36,
    "answerable": 30,
    "top1": 1.0,
    "mrr": 1.0,
    "unanswerable": 6,
    "correct_abstentions": 0,
    "false_empty": 0,
    "relevant_retained": 33,
    "relevant_total": 33
  },
  "input_tokens": 69891,
  "output_tokens": 5586,
  "median_request_ms": 366.9742709971615
}
```

## Limits and decision context

- Thirty-eight unique cases repeated three times; repetitions do not increase the independent sample.
- Historical artifacts without recorded execution provenance are explicitly marked unknown; archive-time source hashes do not reconstruct that history.

[Exact results](artifact.json) · [Provenance and slices](manifest.json)
