# 0055 — Write-time dedup at 0.90, extraction path only

    Status:        accepted
    Date:          2026-08-28
    Supersedes:    placement in 0030 (the threshold and its measurements stand)
    Superseded by: 0072 (target eligibility, revision check, optional semantic verification)
    Evidence:      decisions/0030 cosine measurements; tests/test_semantic_candidates.py
    Code:          src/memkit/extract.py (plan_dedup, apply_ops), src/memkit/api.py
    Contract:      ../04-judge.md

## Decision

`MEMKIT_DEDUP_COSINE` (0.90) finally reads for something. Before the write
transaction, each extracted ADD is embedded and searched against the owner's
active memories; a hit at or above the threshold **in the same context**
(canonical `context_json` byte equality) marks that op. Inside the transaction
the marked ADD links its evidence to the existing memory instead of inserting
a twin, counted as `deduplicated` in the job result. The existing row is not
otherwise touched: no text change, no revision, no recency bump — evidence
accrues, nothing rewrites.

Extraction path only. `POST /v1/memories` is a deliberate caller assertion
and is never silently rewritten; `store.add_memory` stays a dumb authoritative
writer. The threshold is a `run_extraction` parameter (None disables), so the
eval can sweep it without env games; the API passes the setting.

## Why

ADR 0030 accepted 0.90 "with doubt" for a read-path hide that was never built.
Write time is the better placement: a duplicate prevented is cheaper than a
duplicate hidden on every query, and the evidence link preserves exactly what
the duplicate contributed — its citations. Semantic candidates (0054) already
let the judge UPDATE instead of re-ADD; this is the backstop for the case
where the model adds anyway.

At 0.90 only near-verbatim text clears the bar (a genuine paraphrase measures
0.8979 on this corpus), so the false-merge risk this threshold was doubted for
barely exists at write time — and unlike consolidation, a wrong skip loses
nothing but a duplicate's twin row, while the evidence still lands.

## Consequences

One embedding and one top-3 dense search per extracted ADD, outside the write
lock (the ADR 0052 discipline applied to local compute). Cross-context twins
still insert — by this repo's model they are two facts; consolidation (0031,
0056) owns anything smarter. If the planned target vanishes between plan and
apply, the ADD proceeds normally.
