# 0011 — No prompt caching for the extractor

    Status:        declined
    Date:          2026-07-31
    Supersedes:    ../archive/2026-07-original-spec/04-judge.md, prompt caching
    Superseded by: —
    Evidence:      —
    Code:          src/memkit/providers.py
    Contract:      ../04-judge.md#cost-shape

## Decision

Prompt caching is not enabled. Nothing needs to be configured to keep it off.

## Alternatives and why not

The archived spec reached the same conclusion for the wrong reason — that cache
TTLs are short and personal use scatters calls too widely to benefit.

The real reason is that the cache cannot be created at all. The stable prefix of
the extractor prompt is about **350 tokens**, and the minimum cacheable prefix is
1,024 on Sonnet 5, 4,096 on Haiku 4.5 and 512 on Opus 5. The prompt is below every
threshold, so no cache entry is written at any TTL, and the setting would have no
effect rather than a small one.

This matters for a future decision: if the prompt grows past ~1,024 stable tokens,
caching becomes available and this should be reopened. The archived reasoning
would have said no again; the real reasoning says yes.
