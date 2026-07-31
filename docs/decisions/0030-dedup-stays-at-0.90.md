# 0030 — Read-path dedup stays at 0.90

    Status:        accepted with doubt
    Date:          2026-07-31
    Supersedes:    —
    Superseded by: —
    Evidence:      ../measurements.md#frozen-results
    Code:          src/memkit/config.py (`dedup_cosine`)
    Contract:      ../05-retrieval.md#dedup

## Decision

The read-path dedup threshold is 0.90, exposed as `MEMKIT_DEDUP_COSINE` so it can
be swept by the eval rather than edited in code.

## The doubt, stated

Measured on BGE-M3 against this corpus:

| cosine | pair |
|---|---|
| 1.0000 | an exact restatement |
| 0.8979 | "prefers pnpm over npm for all projects" / "prefers pnpm rather than npm everywhere" |
| 0.8871 | "Lives in Tashkent" / "Lives in Tashkent, Uzbekistan" |
| 0.8620 | "Writes Vue 3 with TypeScript" / "Uses Vue 3 and TypeScript on the frontend" |
| 0.7422 | "Prefers pnpm" / "Prefers pytest" |

0.90 catches near-verbatim duplicates and **misses a genuine paraphrase by
0.002**. Something near 0.85 would catch paraphrases while still separating two
distinct tool preferences at 0.7422. So the current value is probably a little too
strict, and it is kept anyway.

The reason is that this is a read-path threshold and the eval is how it should be
decided. Lowering it on the strength of five hand-picked pairs would be adjusting a
retrieval parameter by feel, which is exactly what the setting exists to prevent.
Five pairs is an intuition, not a sweep.

## Revisit when

Someone sweeps it. `memkit eval --compare` is the instrument; the specific thing to
watch is whether recall holds while mean tokens fall, which is the shape a correct
dedup improvement has. Until then this entry is a record that the value is
suspected wrong and was left alone deliberately.
