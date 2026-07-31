# 0025 — The embedder loads before the API accepts traffic

    Status:        accepted
    Date:          2026-07-31
    Supersedes:    —
    Superseded by: —
    Evidence:      ../measurements.md#latency
    Code:          src/memkit/api.py (`lifespan`)
    Contract:      ../01-architecture.md#startup

## Decision

`lifespan` calls `embedder.load()` before yielding, so startup blocks for 11–17
seconds and the service is not reachable until the model is resident.

## Why

Lazy loading moves the cost to the first request, and the first request is the one
that can least afford it. Hermes gives prefetch a 0.4-second budget; a 15-second
first call blows through it, the plugin falls back to an empty memory block by
contract, and the first turn after every restart silently has no memory at all.

That is not hypothetical — it is what happened on the first live run, and it is
why the plugin now also fires a background warm-up in `initialize`
([0040](0040-prefetch-timeout-and-warmup.md)). Two mechanisms, because the failure
is silent and a silent failure deserves belts and braces.

The cost is real: a restart is 15 seconds of downtime rather than instant. For a
single-user local service restarted rarely, that is the right trade.
