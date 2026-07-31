# 0029 — Output size is `budget_tokens`, not an elbow cut

    Status:        declined
    Date:          2026-07-31
    Supersedes:    ../archive/2026-07-original-spec/05-retrieval.md §"Сколько отдавать"
    Superseded by: —
    Evidence:      ../measurements.md#retrieval-eval
    Code:          src/memkit/retrieval.py (`fill_budget`)
    Contract:      ../05-retrieval.md#filling-the-budget

## Decision

The caller supplies `budget_tokens` (default 800) and `limit`. Results are added
in descending score until the next one does not fit; an oversized item is skipped
rather than ending the fill. There is no elbow detection, no `mode` parameter, and
no caller-supplied `max_tokens` ceiling separate from the budget.

## Alternatives and why not

The archived spec designed three mechanisms and argued convincingly that a fixed
budget is wrong in both directions — too much for a narrow question, too little
when several facts genuinely apply:

1. **Elbow cut** — sort by score, cut at the first gap wider than 0.08.
2. **Request modes** — `auto`, `profile` (top-N by importance, ignoring the
   query), `focused` (similarity ≥ 0.55, capped at 5), `off`.
3. **Degenerate-query detection** — a query under 12 characters or with fewer
   than two non-stopwords switches to `profile`, so "ага" and "продолжай" return
   an identity summary instead of noise.

None are built. The reasons differ by mechanism, and only the first is about
evidence:

**Elbow** depends on there being a visible gap in the score distribution. There
is not one: relevant facts sit at 0.40–0.43 similarity against a rank-1 of about
0.71, and after the composite score adds a near-constant base to every fact, the
distribution is smooth. An elbow detector on a smooth curve cuts arbitrarily,
which is worse than cutting at a budget, because it is arbitrary *and*
unpredictable.

**Modes and degenerate detection** were never measured, and the reason they are
declined rather than deferred is that the eval cases which would have justified
them were also dropped — the archived testing strategy asked for three "ага"
cases and two "many relevant results" cases, and `eval/queries.yaml` has neither.
Building the mechanism before the cases exist means shipping a feature no test
can tell is working. The honest order is cases first.

The archived spec's own target was 200–1,200 tokens with a median around 400. The
implemented budget fill lands inside that band on the current eval
([measurements.md](../measurements.md#head-to-head-31-shared-cases)) without any of
the machinery — which is some evidence that the machinery was solving a problem the
budget already handles.

## Revisit when

`eval/queries.yaml` grows the case types that would show the difference: queries
with no useful answer, queries where many facts genuinely apply, and degenerate
queries. Adding those is tracked in [../08-testing.md](../08-testing.md) as a
known gap in the eval's case mix. If the median drifts to the ceiling on those,
the fixed budget is the constraint and this decision should be reopened.
