# v2 batched duplicate guard

Decision: **adopt**. Technology: Jev. Models: jev-1.13.0.

Use the actual runtime block to veto false cosine duplicate proposals.

Labels: author-labeled; not independently reviewed. Data: synthetic. Split: diagnostic-runtime-dedup; repeats: 1 (not independent examples).

## Results

```json
{
  "baseline": {
    "n": 24,
    "accuracy": 0.875,
    "true_positive": 11,
    "false_positive": 2,
    "false_negative": 1,
    "precision": 0.8461538461538461,
    "recall": 0.9166666666666666
  },
  "verified": {
    "n": 24,
    "accuracy": 0.875,
    "true_positive": 9,
    "false_positive": 0,
    "false_negative": 3,
    "precision": 1.0,
    "recall": 0.75
  },
  "service_errors": 0
}
```

## Limits and decision context

- Adopt as an optional conservative guard: false merges fell from 2 to 0, but true merges fell from 11 to 9 out of 12. Synthetic pair proposals; database scope/citation/race behavior is tested separately.
- Historical artifacts without recorded execution provenance are explicitly marked unknown; archive-time source hashes do not reconstruct that history.

[Exact results](artifact.json) · [Provenance and slices](manifest.json)
