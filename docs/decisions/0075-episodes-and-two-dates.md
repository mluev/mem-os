# 0075 — Episodes are memories, and every memory has two dates

    Status:        accepted
    Date:          2026-09-29
    Supersedes:    rule 3 of prompts v7–v10 ("emit nothing for … completed work, schedules")
    Evidence:      ../research/2026-09-29-supermemory.md; to be measured with eval/bench (0081)
    Code:          temporal.py, prompts.py (V11), judge.py (Op), extract.py, store.py, db.py (DDL_V3)
    Contract:      ../02-data-model.md, ../04-judge.md

## Decision

Store what people did and will do. Prompt v11 keeps v10's routing, context and
provenance rules word for word and the exclusion of assistant work logs, and
replaces the blanket refusal of dated content: something a person did,
attended, bought, started, finished or plans at a time is `kind="episode"`
with absolute `event_dates`, and a state with a natural end is a memory whose
`valid_until` is that end.

Every memory carries two dates. `document_date` is when the claim was said —
the earliest cited message's time, never the write time of a backfill — and is
what every relative phrase in it was resolved against. `event_dates` is when
the described thing happened, at the precision the speaker gave (`2026`,
`2026-03`, `2026-03-14`); `event_start`/`event_end` index their interval.
Invalid dates are dropped rather than guessed. Candidates show the model when
each was said. `MEMKIT_PROMPT_VERSION` names an older prompt to roll back
without a deploy.

## Alternatives and why not

**Keep refusing episodes.** Temporal and multi-session questions ("when did
I…", "how many times…", "how long between…") were unanswerable because the
evidence was discarded at the write; the precision it bought is recovered at
read time by decay (0077) instead.

**One timestamp.** Conflating said-at with happened-at is the classic
temporal failure: "on Tuesday I said I moved in March".

**Day precision everywhere.** Inventing the 1st for "in March" makes the store
answer with false confidence.
