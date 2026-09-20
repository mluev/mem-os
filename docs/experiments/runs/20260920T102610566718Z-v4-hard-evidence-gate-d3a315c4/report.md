# v4 hard evidence gate

Decision: **reject**. Technology: Jev. Models: gemini-3.5-flash-lite, jev-1.13.0.

Recover supported extractor outputs with binary verification.

Labels: golden regex scorer; author-labeled. Data: synthetic. Split: diagnostic; repeats: 1 (not independent examples).

## Results

```json
{
  "baseline": {
    "model": "gemini-3.5-flash-lite",
    "version": "v10",
    "expected": 31,
    "found": 27,
    "recall": 0.8709677419354839,
    "false_positives": 0,
    "credential_leaks": 0,
    "invalid_evidence": 0,
    "routing": [
      6,
      7
    ],
    "fabricated_refs": 0,
    "context": [
      14,
      17
    ],
    "kind": [
      8,
      8
    ],
    "importance": [
      2,
      2
    ],
    "operations": [
      2,
      2
    ],
    "over_emission": 0,
    "input_tokens": 59619,
    "output_tokens": 7048,
    "cost_usd": 0.0355057,
    "errors": [],
    "safety_passed": true
  },
  "filtered": {
    "model": "gemini-3.5-flash-lite",
    "version": "v10+v4",
    "expected": 31,
    "found": 16,
    "recall": 0.5161290322580645,
    "false_positives": 0,
    "credential_leaks": 0,
    "invalid_evidence": 0,
    "routing": [
      4,
      5
    ],
    "fabricated_refs": 0,
    "context": [
      8,
      11
    ],
    "kind": [
      5,
      5
    ],
    "importance": [
      1,
      1
    ],
    "operations": [
      0,
      0
    ],
    "over_emission": 0,
    "input_tokens": 59619,
    "output_tokens": 7048,
    "cost_usd": 0.0355057,
    "errors": [],
    "safety_passed": true
  },
  "errors": [],
  "jev_usage": {
    "input_tokens": 20454,
    "output_tokens": 580,
    "requests": 29
  }
}
```

## Limits and decision context

- Retained 16 of 31 expected facts versus 27 before filtering; still unsuitable as a hard gate.
- Historical artifacts without recorded execution provenance are explicitly marked unknown; archive-time source hashes do not reconstruct that history.

[Exact results](artifact.json) · [Provenance and slices](manifest.json)
