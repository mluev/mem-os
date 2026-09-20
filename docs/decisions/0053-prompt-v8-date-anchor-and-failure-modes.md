# 0053 — Prompt v8: session-date anchor and named failure modes

    Status:        accepted
    Date:          2026-08-28
    Supersedes:    —
    Superseded by: —
    Evidence:      the Measured section below; artifacts in data/exports/release-artifacts/golden-v7-20260828T*.json
    Code:          src/memkit/prompts.py, src/memkit/extract.py, eval/golden.py
    Contract:      ../04-judge.md

## Decision

The active extractor prompt becomes v8: v7's full rule set plus a DATES block and
four named failure modes, each taught by one WRONG/RIGHT pair — echo extraction,
meta-extraction, detail contamination, first-topic dominance — and two new rules:
proper nouns are kept verbatim, and stated changes are captured as transitions
(UPDATE of the candidate holding the old truth).

`prompts.render` now formats `today` and `session_date` into versions that
declare those placeholders, and `extract.run_extraction` derives the session
date from the window's first message timestamp. Per-case `session_date` is
supported in the golden set so date behaviour is testable.

Rejected extraction operations now carry a per-op reason
(`evidence_invalid`, `assistant_only_source`, `context_mismatch`,
`target_context_mismatch`) in the job result JSON, and an UPDATE that omits
`valid_until` preserves the existing expiry instead of silently clearing it.

## Why

v7 gave the model no date whatsoever — `prompts.render` deleted both date
arguments, and `run_extraction` never passed the session date in the first
place, while `judge.build_prompt`'s own docstring claimed the opposite. A
relative reference in any backfilled window ("с прошлого месяца") therefore
resolved against nothing: the golden case built for this missed under v7 in
every run and passed under v8 in every run. A memory that says "last month"
is wrong the month after it is written; "2026-02" is true forever.

The failure modes are prompt-encoded bug reports: each names a misfire class
observed in this corpus and in public prompt work on the same task, and a
single concrete pair teaches the boundary more cheaply than a paragraph of
abstract instruction.

## Measured

Golden set, 25 cases, gemini-3.5-flash-lite, 2026-08-28 (two runs; the model is
visibly noisy run to run, so like-for-like runs were compared within the same
invocation): final run v7 21/24 recall, 0 fp, 0 leaks vs v8 21/24, 0 fp,
0 leaks — plus the relative-date case, which v7 cannot answer at all. Cost per
25-case run: $0.0189 (v7) → $0.0220 (v8), ≈$0.0001 more per extraction call.

## Consequences

Facts extracted from backfilled transcripts can carry absolute dates, which is
what makes them durable; the drop-the-relative-phrase rule keeps the rot out of
the text. The prompt is ~40 lines longer, paid on every call. The rejection
trail makes extraction regressions attributable from `/v1/jobs` output without
a new table.
