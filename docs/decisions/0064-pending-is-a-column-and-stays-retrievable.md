# 0064 — Automatic writes are pending, retrievable, and derived from a column

    Status:        accepted
    Date:          2026-09-04
    Supersedes:    —
    Superseded by: —
    Evidence:      tests/test_extract_v4.py, tests/test_api_v4.py (review)
    Code:          src/memkit/store.py (add_memory, set_review_status), src/memkit/api.py (/v1/review)
    Contract:      ../01-architecture.md#ownership-and-trust, ../03-api.md

## Decision

`memories.review_status` is `pending`, `confirmed`, or `declined`, and defaults to `pending`. Every automatic write — extraction, and any write into a scope that is not the author's own — is live immediately and pending. A user's own manual save into their own private scope with a `user` or `manual` source role is `confirmed` on arrival. An extraction UPDATE of a confirmed memory keeps the new text live and returns the row to pending, with the previous wording one revision back.

**Pending memories are retrieved.** `store.memory_active` deliberately does not consult review status. Declining archives the row in the same step, so it stops being retrieved; confirming re-activates it, so a decline is reversible from the dashboard rather than only from history.

The queue is a query over that column. There is no `pending_reviews` table.

## Alternatives and why not

**Hold automatic writes back until confirmed.** The safe-sounding option, and it makes the product useless in the gap. Extraction runs while people work; review happens when someone opens the dashboard, which may be days later. A fact nobody has got round to confirming is still the best thing known, and withholding it means the agent answers "I don't know" about something it was told an hour ago. The cost of the alternative is a wrong fact retrieved for a few days; the cost of withholding is every right fact unavailable for the same period, and there are far more of the latter.

**No review at all.** Defensible while the extractor was answering to one person who could correct their own store. Not once a model routes facts into a shared scope and attributes them to colleagues: the person best placed to catch "Саша is on leave until March" being wrong is Саша, and they need somewhere to see it. Review is also the only feedback signal that costs a human nothing extra.

**Confirm manual saves too.** Rejected as noise. A user typing a fact into their own scope has just asserted it; asking them to assert it again teaches them to click confirm without reading, which destroys the value of the click on the writes that need it. The condition is narrow on purpose — own scope, human source role — so an agent writing on the user's behalf into a shared scope still lands pending.

**A work-queue table.** The conventional shape, and it introduces a second truth about the same row. Every confirm has to update two places; a crash between them leaves a queue row pointing at a memory that no longer needs review, or a pending memory nobody is shown. Deriving the queue from the column makes both impossible — there is a partial index on `(scope_id, created_at) WHERE review_status='pending' AND status='active'`, so it costs an index rather than a table and a reconciliation job. `needs_attention` exists alongside it for the things that genuinely are *not* memories: unresolved names, conflicts, failed jobs, budget warnings.

## Consequences

Search results and profile items carry `review_status`, so a caller that wants to hedge on an unconfirmed fact can, and one that does not is unaffected. The review queue shows the author, the subject, and the previous text when a confirmed memory was rewritten, because "what did this used to say" is the question a reviewer actually has. Reviewing takes an optional `expected_revision`, so two people reviewing the same queue cannot silently overwrite each other's decision.
