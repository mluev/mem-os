# 0073 — Contribution judgments and a shared fact/source context budget

    Status:        accepted
    Date:          2026-09-20
    Supersedes:    — (extends 0072 with independent opt-in modes)
    Evidence:      ../experiments/context-details.md
    Code:          context_selection.py, context_assembly.py, semantic_runtime.py
    Contract:      ../05-retrieval.md

## Decision

Add explicit contribution filtering and optional source context assembly. Keep
all distributed defaults off. The experimental local profile may opt in after
paired evaluations; this is not automatic deployment or production validation.

A contribution Noul asks whether a candidate supplies any applicable answer
detail. This avoids an observed mismatch between Score's partial-answer level 2
and a minimum expected Score of 2, which rejected many useful partial answers.
The existing Score path remains available for comparison and rollback.

With `include_raw=true` and `semantic_context=select|compact`, gather at most 60
facts and original user passages, interleaving the two candidate arms rather than
comparing incompatible scores. Re-fetch raw IDs from authoritative storage and
check current scope, user role and requested filters before provider egress.
Messages remain verbatim evidence; they are not promoted into current facts.

Both outputs share one token budget, including supplemental cited excerpts when
requested. Compaction only changes returned context; it cannot merge or delete
stored memory. It compares each candidate against already-kept candidates so a
discarded item cannot become the only support for dropping a later item.

Provider failure preserves baseline candidate order; interrupted compaction
preserves the relevance-ranked list. Work is bounded by candidate, batch, step
and time limits. The between-call deadline is not hard cancellation of an active
HTTP request. Observations record version, usage, counts and failures without
source or query text. A key alone enables nothing.

## Alternatives and evidence

On the frozen confirmation split, evidence-aware Contribution retained 36/40
details versus 27/40 without Jev; irrelevant returns fell from 79 to 1. On the
real two-collection integration path, optional compaction retained 37/40 versus
34/40 without Jev and removed all 70 irrelevant returns. These are small authored
synthetic studies, with local exact Qdrant, not user or server ANN measurements.

Source priority without Jev retained 40/40 but returned 74 irrelevant items.
It is a completeness/precision tradeoff, not an unconditional model advantage.
Source priority after Jev is promising but was explored after opening the test
split, so it is not silently promoted. Coverage retry and broader write-time
deduplication were not justified by these experiments and remain unchanged.
