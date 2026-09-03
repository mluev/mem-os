# 0056 — Semantic consolidation merge: clustered at 0.92, LLM-confirmed, flag-gated

    Status:        accepted
    Date:          2026-08-28
    Supersedes:    — (implements what 0031 measured and 0032 shaped)
    Superseded by: —
    Evidence:      decisions/0031 cosine measurements; tests/test_consolidate_merge.py
    Code:          src/memkit/consolidate.py, src/memkit/providers.py (call_merge)
    Contract:      ../01-architecture.md, ../06-roadmap.md

## Decision

Consolidation gains a semantic arm, wiring three artifacts that had been dormant
since 0031: `MEMKIT_CONSOLIDATE_COSINE` (0.92), `prompts.CONSOLIDATE_V2`, and
`providers.call_merge`. Every plan computed with an embedder reports
`semantic_groups`: connected components (0032's choice) of same-context active
memories at pairwise cosine ≥ 0.92, minus clusters the exact-duplicate grouping
already owns. Contexts are never crossed.

Merging is doubly gated: it runs only with `--apply --merge` (CLI) or
`{"dry_run": false, "merge": true}` (API), never by default and never from the
nightly schedule. Each cluster goes to the merge model under the same monthly
budget reservation discipline as extraction; the call is logged to `judge_runs`
with `kind='merge'`. A null answer — "these are different things" — is a
first-class result and leaves the cluster alone, as does any provider error.

A confirmed merge inserts one survivor carrying the merged text, the newest
member's kind/context/tags, the members' minimum confidence, and
`provenance.weakest()` of the member roles — a merge is no better sourced than
its worst input, so assistant text can never launder into a user-sourced fact.
Members become `superseded` with `superseded_by` pointing at the survivor, and
every `memory_sources`/`memory_evidence` row is inherited.

## Why

The exact grouping only catches byte-identical restatements; the duplicate class
that actually accumulates is the 0.9278-cosine pair 0031 measured ("User's name
is Maga Luev" / "User's name is Maga (or MagaLoviev)"), which no amount of
normalisation reaches. 0031 also showed why a threshold alone must not merge:
0.92 is a *candidate* bar, and the model's null answer is the safety net for
same-topic-different-claim neighbours.

## Rollback

Free by construction: superseded members keep their full text, provenance, and
`superseded_by`. Reverting a merge is re-activating the members and archiving
the survivor; nothing is destroyed. This is why apply-then-measure is an
acceptable evaluation protocol here where it would not be for erasure.

## Consequences

At most `merge_cap` (20) provider calls per run, each ~$0.001 at Flash-Lite
rates, reserved against the monthly ceiling before the call and reconciled
after. Clusters beyond the cap are reported, never silently dropped. The
roadmap's "no automatic semantic merge" stays true: off by default, explicit
flag, dry-run first.
