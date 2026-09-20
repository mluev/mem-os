# v2 across fictional user scenarios

Decision: **observe**. Technology: Jev. Models: jev-1.13.0.

Transfer frozen v2 questions to development, education and personal-assistant scenarios.

Labels: author-labeled; not independently reviewed. Data: synthetic. Split: heldout; repeats: 2 (not independent examples).

## Results

```json
{
  "cases": 144,
  "service_errors": 0,
  "support": {
    "n": 48,
    "accuracy": 0.9791666666666666,
    "true_positive": 23,
    "false_positive": 0,
    "false_negative": 1,
    "precision": 1.0,
    "recall": 0.9583333333333334
  },
  "citation_only_acceptance": {
    "n": 48,
    "accuracy": 0.5,
    "true_positive": 24,
    "false_positive": 24,
    "false_negative": 0,
    "precision": 0.5,
    "recall": 1.0
  },
  "relation": {
    "n": 48,
    "correct": 48
  },
  "duplicate": {
    "n": 48,
    "accuracy": 0.9166666666666666,
    "true_positive": 20,
    "false_positive": 0,
    "false_negative": 4,
    "precision": 1.0,
    "recall": 0.8333333333333334
  },
  "retrieval": {
    "n": 48,
    "answerable": 24,
    "top1": 1.0,
    "mrr": 1.0,
    "unanswerable": 24,
    "correct_abstentions": 24,
    "false_empty": 0,
    "relevant_retained": 42,
    "relevant_total": 42
  },
  "cosine_duplicate_at_0.90": {
    "n": 48,
    "accuracy": 0.875,
    "true_positive": 22,
    "false_positive": 4,
    "false_negative": 2,
    "precision": 0.8461538461538461,
    "recall": 0.9166666666666666
  },
  "dense_only_retrieval": {
    "n": 48,
    "answerable": 24,
    "top1": 1.0,
    "mrr": 1.0,
    "unanswerable": 24,
    "correct_abstentions": 0,
    "false_empty": 0,
    "relevant_retained": 42,
    "relevant_total": 42
  },
  "input_tokens": 91150,
  "output_tokens": 7088,
  "median_request_ms": 368.2851874982589
}
```

## Limits and decision context

- Seventy-two probes derive from twelve related scenario families; labels are author-written and not independently reviewed.
- Historical artifacts without recorded execution provenance are explicitly marked unknown; archive-time source hashes do not reconstruct that history.

[Exact results](artifact.json) · [Provenance and slices](manifest.json)
