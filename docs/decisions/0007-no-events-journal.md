# 0007 — No append-only events journal

    Status:        declined
    Date:          2026-07-31
    Supersedes:    ../archive/2026-07-original-spec/02-data-model.md §"Журнал событий"
    Superseded by: —
    Evidence:      —
    Code:          —
    Contract:      ../02-data-model.md#what-is-not-recorded

## Decision

There is no `events` table, no eighteen-value action vocabulary, and no
`POST /v1/admin/events/{id}/redact`. Audit is served by what already exists:
`judge_runs` (every model call with its input, output, tokens and cost),
`memory_sources` (which messages produced which fact),
`memories.superseded_by` (the revision chain), and
`last_retrieved_at`/`retrieval_count` (what has actually been used).

## Alternatives and why not

The archived specification made a strong case: a full journal of creations,
edits, type changes, deletions, retrievals and judge refusals is the material you
improve the system with a year later, and it argued the volume was affordable
(around 2,000 rows a day at 100 searches).

Two reasons it is declined rather than deferred.

**The retrieval events are the bulk and the least useful.** "This fact was
returned for this query at this time" is 95% of the projected volume, and the
questions it answers — which facts are dead weight, which are load-bearing — are
already answered by two columns on the fact itself. A journal would be a
higher-fidelity version of information that is not currently being used at its
existing fidelity.

**The mutation events duplicate existing rows.** Every write already goes through
`mutate`, which enforces optimistic concurrency and returns the before-and-after
row. What is missing is not the data but a place to put it, and adding that place
means touching every write path in six modules for an audit trail with, at
present, one user and no compliance requirement.

The genuinely irreplaceable item was `memory.rejected`: a record of the judge
proposing a fact that the write layer refused. Restoring the guard
([0006](0006-source-role-and-may-write.md)) without a journal would have made
those refusals silent, which is worse than not having the guard. So refusals are
counted on `ExtractionOutcome.rejected`, returned by
`POST /v1/sessions/{id}/close`, and logged with the same `assistant_only_source`
reason string the archived spec used for its event — so a grep finds both.

## Revisit when

A second user exists, or any fact needs to be explained to somebody who was not
present when it was stored. Both make "who changed this and when" a question
someone else asks, which is the point at which a journal stops being for you.

Note that declining this also declines the emergency-erase hatch the archived spec
paired with it. Redaction today means editing or hard-deleting the row, which is
adequate for one local user and would not be for two.
