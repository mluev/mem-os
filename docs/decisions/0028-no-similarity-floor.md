# 0028 — No similarity floor on the read path

    Status:        declined
    Date:          2026-07-31
    Supersedes:    ../archive/2026-07-original-spec/05-retrieval.md §"Порог релевантности"
    Superseded by: —
    Evidence:      ../measurements.md#frozen-results
    Code:          src/memkit/retrieval.py
    Contract:      ../05-retrieval.md#what-is-not-filtered

## Decision

Results are not filtered by a minimum similarity. Ranking, scope filtering, dedup
and the token budget decide what is returned; nothing is dropped for being merely
distant.

## Alternatives and why not

The archived spec put this first and was emphatic: vector search always returns
`k` results however far away they are, so a floor of 0.35 should be applied before
anything else, and an empty result is the correct answer to a question memory
cannot help with.

The reasoning is sound and the measurement did not support it. Swept over 31 eval
questions:

| floor | recall@10 | MRR | mean tokens |
|---|---|---|---|
| off | 0.87 | 0.759 | 395 |
| 0.40 | 0.87 | 0.759 | 362 |
| 0.45 | 0.84 | 0.746 | 289 |
| 0.50 | 0.77 | 0.728 | 166 |

Only 0.40 is quality-neutral, and it buys 8% of tokens. That does not justify
another threshold to maintain, sweep and explain.

The structural reason the floor does less than expected: on a corpus this size,
`0.20 × importance + 0.15 × recency` gives nearly every fact about 0.33 of base
score, which compresses the similarity contribution to roughly
`0.55 × (0.71 − 0.31) ≈ 0.22`. A floor on raw similarity cuts across a ranking
that similarity only partly determines.

The "empty output is correct" half of the argument survives and is honoured
differently: scope filtering discards foreign-project facts outright rather than
down-weighting them ([../05-retrieval.md](../05-retrieval.md)), so an empty result
is reachable and normal — it just is not produced by a distance cutoff.

## Revisit when

Either the corpus grows enough that base score stops dominating similarity, or
the eval shows precision losses that scope filtering does not explain. At that
point sweep again rather than adopting the archived 0.35, which was never
measured.
