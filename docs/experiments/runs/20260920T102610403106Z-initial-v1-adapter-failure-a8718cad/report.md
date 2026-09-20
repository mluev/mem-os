# Initial v1 adapter failure

Decision: **reject**. Technology: Jev. Models: jev-1.13.0.

Validate Jev response parsing on the development probes.

Labels: author-labeled; not independently reviewed. Data: synthetic. Split: dev; repeats: 2 (not independent examples).

## Results

```json
{
  "cases": 100,
  "service_errors": 16,
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
    "correct": 33
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
    "n": 8,
    "answerable": 8,
    "top1": 1.0,
    "mrr": 1.0,
    "unanswerable": 0,
    "correct_abstentions": 0,
    "false_empty": 0,
    "relevant_retained": 8,
    "relevant_total": 8
  },
  "input_tokens": 39522,
  "output_tokens": 4284,
  "median_request_ms": 363.9572499996575
}
```

## Limits and decision context

- Sixteen responses were rejected by an overly strict local rounding check; this is not model-quality or provider-availability evidence.
- Historical artifacts without recorded execution provenance are explicitly marked unknown; archive-time source hashes do not reconstruct that history.

[Exact results](artifact.json) · [Provenance and slices](manifest.json)
