# 0054 — Semantic candidates for extraction, behind an integer remap

    Status:        accepted
    Date:          2026-08-28
    Supersedes:    —
    Superseded by: —
    Evidence:      measurements.md#model-authored-writes (the 0.9821 pair)
    Code:          src/memkit/extract.py (find_candidates), src/memkit/judge.py (extract)
    Contract:      ../04-judge.md

## Decision

`find_candidates` gains a dense arm: when a Qdrant client and embedder are
available, the window's user text is embedded and the top matches across *all*
of the owner's active memories join the same-context recency list, capped at
ten. Every dense hit is re-read from SQLite and dropped unless still active —
the index nominates, the authoritative store confirms.

The judge never sees real memory ids. `judge.extract` renders candidates as
`id=1, id=2, …`, keeps the map, and translates returned UPDATE/DELETE targets
back; an op citing an integer outside the map is dropped before `apply_ops`
and surfaced in the outcome as an `unknown_candidate` rejection. The map is
recorded in `judge_runs.input_json` so logged runs stay explainable.

## Why

Exact-`context_json` recency was the only candidate source, so the judge
almost never saw the memory it should have updated: the corpus's documented
0.9821-cosine duplicate pair never merged because each write ran with the
other candidate invisible. Cross-context visibility is what lets rule 8 and
the v8 transition rule actually fire.

The remap exists because UUIDs shown to an LLM come back subtly mutated often
enough to be a failure class (the same mitigation mem0 ships); with small
integers, anything outside the map is provably fabricated rather than
plausibly mistyped, so it can be rejected with a clean conscience.

## Invariants kept

Cross-context candidates inform dedup and transitions only. `apply_ops` still
rejects an UPDATE/DELETE whose target context differs from the op's context,
and `_context_allowed` still binds op context to the session — context-hopping
writes remain impossible. Absent a client/embedder (offline tests, degraded
index) behaviour is exactly the old recency query.

## Consequences

One extra embedding and one Qdrant round-trip per extraction, both before the
write transaction. UPDATE/DELETE can now fire against paraphrased prior facts,
which the golden set's candidate cases gate (`contradicts-candidate`,
`rename-transition-updates-candidate` pass under v8 with the remap live).
