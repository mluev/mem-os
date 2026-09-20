# v2 evidence with date and entity context

Decision: **reject**. Technology: Jev. Models: gemini-3.5-flash-lite, jev-1.13.0.

Recover source support by supplying the date and known entities.

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
    "found": 14,
    "recall": 0.45161290322580644,
    "false_positives": 0,
    "credential_leaks": 0,
    "invalid_evidence": 0,
    "routing": [
      4,
      5
    ],
    "fabricated_refs": 0,
    "context": [
      7,
      9
    ],
    "kind": [
      4,
      4
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
    "input_tokens": 25000,
    "output_tokens": 1189,
    "requests": 29
  }
}
```

## Limits and decision context

- Retained 14 of 31 expected facts versus baseline 27; a single run cannot attribute the difference from minimal-state v2 solely to state construction.
- Historical artifacts without recorded execution provenance are explicitly marked unknown; archive-time source hashes do not reconstruct that history.

[Exact results](artifact.json) · [Provenance and slices](manifest.json)
