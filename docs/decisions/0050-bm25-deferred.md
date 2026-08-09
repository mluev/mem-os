# 0050 — BM25 hybrid retrieval is deferred

    Status:        superseded
    Date:          2026-07-31
    Supersedes:    —
    Superseded by: 0051
    Evidence:      ../measurements.md#retrieval-eval
    Code:          src/memkit/vectors.py (sparse slot declared, never written)
    Contract:      ../06-roadmap.md#stage-6

## Decision

Retrieval is dense cosine only. Both collections declare a `bm25` sparse vector
slot at creation, and nothing ever writes to or queries it.

## Why the slot exists anyway

Adding a named vector to an existing Qdrant collection requires recreating it.
Declaring the slot at creation costs nothing and means enabling hybrid search later
is a code change rather than a reindex of the whole store. This is cheap
optionality, and it should not be mistaken for partial implementation — there is no
setting that turns it on, and there is no fusion code.

## Revisit when

The measured trigger already exists: relevant facts sit at similarity **0.40–0.43**
while rank-1 is around 0.71. That is a narrow band, and it is the specific
weakness lexical matching fixes — an exact term match ("pnpm", "OTP", a filename)
is precisely what a dense embedding blurs.

The trigger to act is a *precision* regression on the eval that scope filtering does
not explain, or eval misses that are visibly exact-term lookups. Of the five current
misses, `mem-page-titles` and `code-review-comments` are plausible candidates. One
more such case and this is worth building.

Enabling it means writing sparse vectors on every upsert, adding a fusion step
(reciprocal rank fusion, most likely), and extending the eval to report both
retrieval arms separately — otherwise a hybrid result that improves overall while
degrading the dense arm is indistinguishable from one that improves both.
