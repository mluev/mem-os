# 0077 — Retrieval policy v2: time, order, decay, mentions and inference

    Status:        accepted
    Date:          2026-09-29
    Supersedes:    — (core-retrieval-neutral-v1 stays, unchanged and selectable)
    Evidence:      to be measured with eval/bench (0081); see ../measurements.md#to-be-re-measured
    Code:          retrieval.py, temporal.py, graph.py, store.py (evidence_excerpts), routers/memory.py
    Contract:      ../05-retrieval.md

## Decision

`core-retrieval-v2` becomes the search default. It keeps v1's fusion weights
and relevance floor and adds signals that are all zero under v1: a time window
parsed from the query (English and Russian, resolved against `as_of`, the
question's date) boosts memories whose event — or, lacking one, whose saying —
overlaps it; "first/earliest" and "latest/current" order relevant claims by
time; ordinary episodes decay from when they happened with a 60-day half-life
unless marked significant; mentions across sessions add up to +0.05; an
unconfirmed inference loses 0.08, and `inference` becomes a trusted role.

Search also accepts `since`/`until` as a hard window, and can attach the
memories a result replaced (`include_history`), memories linked to it
(`include_related`) and the passage around each cited span
(`source_context_chars`). Search runs on atomic claims; neighbours and source
chunks carry the detail, and all of it spends one token budget.

## Alternatives and why not

**Tune v1 in place.** Policies are versioned so a ranking change can be rolled
back by name; `neutral-v1` still reproduces the previous order exactly.

**A model-based time parser.** It would put a model call before every search.
The rule parser recognises phrases with one unambiguous window and says
nothing otherwise, because a wrong window boosts the wrong facts.

**Unmeasured weights.** The values are starting points chosen so no signal can
outweigh relevance (the floor still applies first). The benchmark harness is
the measurement that sets them; until it runs they stand on reasoning only.
