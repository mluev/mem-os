# 0032 — Clusters are connected components, capped at six, partitioned by type

    Status:        accepted; the type partition is superseded by 0056
    Date:          2026-07-31
    Supersedes:    —
    Superseded by: 0056 (type partition dropped)
    Evidence:      ../measurements.md#consolidation
    Code:          src/memkit/consolidate.py (`_semantic_groups`, `MAX_CLUSTER_MEMBERS`)
    Contract:      ../04-judge.md#the-consolidator

## Decision

Clusters are connected components of the "at least as similar as the threshold"
graph, computed with union-find, restricted to facts sharing an `owner_id` **and**
a `type`. Components larger than six members are logged and skipped.

## Alternatives and why not

**Pairwise merging** would merge A with B and separately B with C, leaving three
facts where there should be one and a supersession chain that forks. Transitive
closure is what "these are the same fact" actually means.

**No size cap.** A component of twenty means the threshold is wrong for that
region of the corpus, not that twenty facts are one fact. Merging them would
produce a single memory summarising a fifth of the store, and the merge is
permanent. Skipping and logging leaves the evidence visible and the store intact.

## The type partition, and its cost

Restricting to a shared `type` prevents merging a `preference` with a `decision`
that happen to be worded similarly — a real risk, since the type carries the
recency half-life and merging across types would silently change how fast a fact
decays.

It also blocks correct merges, measurably. A live pair at cosine **0.9821** —
"Vibe OS idea: preserve global workflow context…" and "Vibe OS concept: retain
global workflow context…" — will never be considered, because the agent that wrote
both labelled one `project` and one `fact`. The threshold is not the binding
constraint there; the partition is.

This is accepted rather than fixed because the alternative is worse in a way that
is harder to see: allowing cross-type merges makes the survivor's type arbitrary,
and the type determines decay. A better fix is upstream — the same claim should
not receive two types — which is [0006](0006-source-role-and-may-write.md)'s
territory, since both writes came from the model's own path.

## What shipped, and when

The size cap was stated here in 2026-07 and not implemented: `_connected_components`
returned components of any size, and `merge_cap` bounded the *number* of clusters
per run, not the members of one. Until 2026-09 a transitive chain could therefore
serialise arbitrarily many facts into a prompt whose answer must fit 200
characters. It is now `consolidate.MAX_CLUSTER_MEMBERS = 6`; oversized components
are reported as `oversized_groups` and never sent to a provider.

The type partition described below was dropped by
[0056](0056-semantic-consolidation-merge.md), which clusters within a context
instead. The 0.9821 pair cited here is the measurement that motivated that
change.

## Revisit when

A count of near-duplicate pairs blocked solely by the type partition is worth
having. If it grows, the answer is probably to merge within a type-compatibility
class rather than to drop the partition.
