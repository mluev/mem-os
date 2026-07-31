# 0040 — Prefetch gets 0.4 s and a background warm-up

    Status:        accepted
    Date:          2026-07-31
    Supersedes:    ../archive/2026-07-original-spec/07-hermes-adapter.md (0.15 s)
    Superseded by: —
    Evidence:      ../measurements.md#frozen-results
    Code:          integrations/hermes/memkit/__init__.py
    Contract:      ../07-hermes-adapter.md#prefetch

## Decision

`prefetch` has a 0.4-second timeout (`prefetch_timeout`), and `initialize` fires a
background warm-up query. On timeout the plugin serves a cached block, then an
empty string. It never raises.

## Alternatives and why not

The archived spec budgeted 0.15 s, reasoning from BGE-M3 on MPS at ~30 ms plus
Qdrant at ~10 ms. That arithmetic was right about the components and wrong about
the measurement: it costed the in-process work, not an HTTP round trip to a service
that may have just started. Measured live: **~840 ms cold, 75–93 ms warm.**

The fix is not a longer timeout. A timeout wide enough for the cold case (1 s+)
would make every warm turn wait on a budget it does not need, and would put a
visible pause in front of the user's first message. Instead the cold call is paid
for out of band by the warm-up in `initialize`, and the timeout stays tight for the
steady state.

Without the warm-up the first turn after every restart silently has no memory —
which is exactly what happened on the first live run. Related:
[0025](0025-eager-embedder-load.md), which addresses the same failure from the
service side.
