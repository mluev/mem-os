# v2 hard evidence gate

Decision: **reject**. Technology: Jev. Models: gemini-3.5-flash-lite, jev-1.13.0.

Reduce unsupported extraction without losing correct facts.

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
    "version": "v10+v2",
    "expected": 31,
    "found": 15,
    "recall": 0.4838709677419355,
    "false_positives": 0,
    "credential_leaks": 0,
    "invalid_evidence": 0,
    "routing": [
      4,
      5
    ],
    "fabricated_refs": 0,
    "context": [
      6,
      8
    ],
    "kind": [
      3,
      3
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
    "input_tokens": 22107,
    "output_tokens": 1189,
    "requests": 29
  }
}
```

## Limits and decision context

- Retained 15 of 31 expected facts versus 27 before filtering; no measured false-positive benefit.
- Historical artifacts without recorded execution provenance are explicitly marked unknown; archive-time source hashes do not reconstruct that history.

[Exact results](artifact.json) · [Provenance and slices](manifest.json)
