# 0019 — Qdrant holds two collections, `memories` and `raw`

    Status:        accepted
    Date:          2026-07-31
    Supersedes:    ../archive/2026-07-original-spec/06-roadmap.md, phase 1
    Superseded by: —
    Evidence:      ../measurements.md#index-consistency
    Code:          src/memkit/vectors.py
    Contract:      ../02-data-model.md#qdrant

## Decision

`memories` holds one point per active fact. `raw` holds indexed user turns. They
are separate collections.

## Alternatives and why not

The roadmap proposed putting raw messages into Qdrant "as they are", which read
naturally as one collection. That breaks the invariant the read path depends on:
one point per active fact. Mixing turns and facts means a search cannot tell
whether a hit is something the user said once or something concluded about them,
and the scoring formula — which weights importance, recency by type, and scope —
has no meaning for a raw turn.

The `raw` collection is not vestigial. It is the stage-1 baseline the eval compares
against ([0037](0037-answerable-by-partition.md),
[0038](0038-stage-2-exit-gate.md)), and it answers the class of question the
extractor is correct to decline: one-off details that were true on a Tuesday.

Two collections also make the reindex asymmetry explicit: `memories` reloads only
`status='active'` ([0020](0020-reindex-loads-active-only.md)), while `raw` reloads
every user turn over the length floor. One filters, one does not.
