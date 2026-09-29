# 0079 — Optional query rewrites fused by rank; optional local cross-encoder

    Status:        accepted
    Date:          2026-09-29
    Supersedes:    —
    Evidence:      to be measured with eval/bench (0081)
    Code:          rewrite.py, retrieval.py (fuse), rerank.py, api.py
    Contract:      ../05-retrieval.md

## Decision

`rewrite_query` asks the judge for up to three rephrasings of a search, runs
each with the same scopes, filters, policy and question date, and fuses the
lists by reciprocal rank (k = 60). Any failure searches the original alone.
Rewrites are returned to the caller and never stored, because retrieval
telemetry keeps only an HMAC of the query.

`MEMKIT_RERANK_MODEL` enables a local cross-encoder over the head (30) of the
hybrid list, blended 0.7/0.3 with the fused score. It loads lazily and keeps
the hybrid order on any failure. A configured semantic retrieval block takes
precedence. Both are off by default.

## Alternatives and why not

**Rewrite by default.** It adds a model call to every read.

**Replace the fused score with the cross-encoder's.** The fused score carries
importance, time and mentions the cross-encoder cannot see.
