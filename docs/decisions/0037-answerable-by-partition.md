# 0037 — Eval cases declare which targets can answer them

    Status:        accepted
    Date:          2026-07-31
    Supersedes:    —
    Superseded by: —
    Evidence:      ../measurements.md#retrieval-eval
    Code:          eval/run.py (`Case.answerable_by`)
    Contract:      ../08-testing.md#layer-3-search

## Decision

Each eval case declares `answerable_by`. A question that only a raw transcript can
answer is not scored against the extracted facts. `memkit eval --compare` scores
both targets over the intersection.

## Why

Before the partition, extracted facts scored 0.253 MRR and read as an extractor
failure. Inspecting the misses showed that **19 of 22** were windows the judge had
read and correctly declined — one-off tickets like "the header is too big" and "run
the seeder", which prompt rule 8 forbids storing because they will not matter in
three months.

That is not a retrieval failure. It is a specification conflict: the eval was
penalising the extractor for obeying its instructions. Scoring it that way would
have driven exactly the wrong fix — loosening the rule that keeps the store from
filling with transient detail.

## The trap this creates, and the guard

An `answerable_by` marker is a coverage claim being withdrawn, and it would be very
easy to improve the score by marking every miss unanswerable. Two things make that
visible: the eval prints the count and the names of excluded cases on every run,
and `--compare` prints the size of the shared set against the total. A suppressed
case is never silent.

Sixteen of 47 cases are currently raw-only. That ratio is itself a number to watch:
if it climbs, the question is whether the extractor is declining too much, not
whether the eval should exclude more.
