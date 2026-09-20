# Duplicate width diagnostic: no policy promotion

Decision: **reject**. Technology: Jev. Models: jev-1.13.0.

Broader duplicate proposals verified by Jev recover paraphrases without absorbing new details.

Labels: author-labeled; not independently reviewed. Data: synthetic. Split: opened-context-relation-diagnostic; repeats: 1 (not independent examples).

## Results

```json
{
  "dev": {
    "cosine_only": {
      "n": 48,
      "accuracy": 0.8333333333333334,
      "true_positive": 8,
      "false_positive": 0,
      "false_negative": 8,
      "precision": 1.0,
      "recall": 0.5
    },
    "narrow_verified": {
      "n": 48,
      "accuracy": 0.7291666666666666,
      "true_positive": 3,
      "false_positive": 0,
      "false_negative": 13,
      "precision": 1.0,
      "recall": 0.1875
    },
    "broad_verified": {
      "n": 48,
      "accuracy": 0.8125,
      "true_positive": 7,
      "false_positive": 0,
      "false_negative": 9,
      "precision": 1.0,
      "recall": 0.4375
    },
    "judgment_only": {
      "n": 48,
      "accuracy": 0.8125,
      "true_positive": 7,
      "false_positive": 0,
      "false_negative": 9,
      "precision": 1.0,
      "recall": 0.4375
    }
  },
  "confirmation": {
    "cosine_only": {
      "n": 48,
      "accuracy": 0.7291666666666666,
      "true_positive": 4,
      "false_positive": 1,
      "false_negative": 12,
      "precision": 0.8,
      "recall": 0.25
    },
    "narrow_verified": {
      "n": 48,
      "accuracy": 0.6666666666666666,
      "true_positive": 0,
      "false_positive": 0,
      "false_negative": 16,
      "precision": null,
      "recall": 0.0
    },
    "broad_verified": {
      "n": 48,
      "accuracy": 0.7083333333333334,
      "true_positive": 2,
      "false_positive": 0,
      "false_negative": 14,
      "precision": 1.0,
      "recall": 0.125
    },
    "judgment_only": {
      "n": 48,
      "accuracy": 0.7083333333333334,
      "true_positive": 2,
      "false_positive": 0,
      "false_negative": 14,
      "precision": 1.0,
      "recall": 0.125
    }
  }
}
```

## Limits and decision context

- Opened synthetic scenario families, not independent heldout relation evidence.
- All pairs judged for paired ablation; estimates are not production candidate-search costs.
- Measures pair decisions, not actual extraction writes or database races.
- Facet-level paraphrase labels are not independently adjudicated strict equivalence; some pairs differ in modality or normality. Do not use this diagnostic to choose a destructive merge threshold.

[Exact results](artifact.json.gz) · [Provenance and slices](manifest.json)
