# 0039 — Legacy over-scoped facts are relabelled by a human

    Status:        accepted, open
    Date:          2026-07-31
    Supersedes:    —
    Superseded by: —
    Evidence:      ../measurements.md#snapshot-corpus-and-store
    Code:          eval/scope_review.py
    Contract:      ../06-roadmap.md#open-work

## Decision

Facts extracted under prompt v4 carry `scope='project'` more often than they
should, which makes them unreachable unless the caller names that project.
Reclassifying them is a manual review, assisted by `eval/scope_review.py`, which
emits a ready-to-post bulk payload but decides nothing.

## Why not automate it

The obvious move is a second model pass over the existing facts, asking each time
whether this is really about the repository. The judge already answered that
question once and got it wrong; asking the same class of model the same question at
a different layer is the same mistake with an extra step, and this time it would be
applied to the whole store at once rather than one window at a time.

`scope_review.py` therefore classifies with two regexes into `PROMOTE?`, `look` and
`keep`, prints the reachable share, and stops. A human decides.

## Why it stays open

Roughly 60 of 97 active facts are project-scoped, and by inspection a meaningful
share of those read as facts about the person rather than the codebase. Three of
the five current eval misses look like this defect rather than extraction failure,
which means it is also distorting the stage-2 gate numbers
([0038](0038-stage-2-exit-gate.md)).

New facts extracted under v6 do not have the problem: v6 made the repository-naming
rule conditional, and its measured user-scope share is roughly double v4's. So this
is a backlog of legacy rows, not an ongoing leak — which is the reason it is
acceptable to leave open.
