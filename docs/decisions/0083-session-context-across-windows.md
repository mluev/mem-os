# 0083 — The window is preceded by the session before it, never citable

    Status:        accepted
    Date:          2026-10-19
    Supersedes:    —
    Evidence:      to be measured; see ../measurements.md#to-be-re-measured
    Code:          extract.py (prior_messages, run_extraction), judge.py (render_prior), prompts.py (PRIOR_MESSAGES)
    Contract:      ../04-judge.md

## Decision

Under prompt v12 the extractor sees the last four user or assistant messages
before its window as EARLIER IN THIS SESSION, without message numbers, recorded
as `prior_message_ids` on the judge run. A citation of one of them is
`evidence_invalid`, because the citation check accepts only the window's ids. A
window holding only assistant turns is read when the question they answer is in
that earlier context, instead of being marked processed unread.

## Why

Windows are ten contiguous messages that end wherever ten messages end, so "that
hotel" in a window often points at a turn just before it, and an answer whose
question fell in the previous window was skipped outright. Supermemory ingests
whole sessions and resolves references within them. Four messages cover the
boundary at roughly 3–15% more input tokens per call; the whole session would
multiply them.

## Alternatives and why not

**Overlapping windows.** The same message would be extracted twice and its
facts deduplicated after the fact; uncitable context gives the model the
reference without a second chance to extract it.

**Whole-session extraction.** It changes cost, latency and the lease model at
once; measure the boundary fix first.
