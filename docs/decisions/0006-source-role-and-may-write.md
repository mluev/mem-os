# 0006 — A fact may not derive solely from assistant turns

    Status:        accepted
    Date:          2026-07-31
    Supersedes:    ../archive/2026-07-original-spec/02-data-model.md §"Запрет на самоотравление"
    Superseded by: —
    Evidence:      ../measurements.md#model-authored-writes
    Code:          src/memkit/provenance.py, src/memkit/db.py (schema 3)
    Contract:      ../02-data-model.md#provenance

## Decision

`memories.source_role` records where each fact came from: `user`, `assistant`,
`tool` or `manual`. It is `NOT NULL`, `CHECK`-constrained, and has no `DEFAULT` —
an insert that forgets provenance fails rather than quietly claiming a human
typed it. `provenance.may_write` refuses any ADD or UPDATE whose only evidence is
assistant text. Callers writing on a model's behalf declare it: the Hermes plugin
sends `source_role="assistant"` from both `on_memory_write` and the
`memkit_remember` tool.

The loop this breaks: a model asserts something, the assertion is stored, the
stored fact is prefetched into the next prompt, and the model reads its own claim
back as established and restates it with more confidence. Once that starts there
is no way to find the beginning of it, because the memory looks exactly like one
the user stated.

## Why the prompt rule was not enough

The extractor prompt already says it — v6 rule 4, "the assistant's turns are
context only, never source material" — and that rule is good. But a prompt is a
request. The archived specification made the argument better than this document
can: a check in the prompt is enforced by the thing being checked.

The live evidence settles it. Of eight facts added to the store in one session,
seven were written by the agent through Hermes at importance 0.8–0.95, bypassing
the judge and the prompt entirely, and landing as `extraction_version='manual'`
— indistinguishable from something typed by hand. Four of them described the
same project; two pairs sat at cosine 0.9925 and 0.9821. The prompt rule was
never consulted on any of them, because that write path does not go through the
prompt.

## What this buys, and what it does not

Stated plainly, because a guard whose limits are undocumented gets mistaken for
a guarantee.

**On the API path it is load-bearing today.** Model-authored writes are now
countable and filterable, and `GET /v1/admin/stats` reports `by_source_role`. "The
agent wrote thirty facts about me this week" went from invisible to a number.

**On the extraction path it cannot currently fire.** `apply_ops` links the entire
window to every fact it creates, and `fast_forward_to_user_turn` guarantees each
window holds a user turn, so the roles are always `{user, assistant}`. There it is
a fail-closed regression detector, not a running defence. It starts doing real
work the day the judge cites its own evidence per operation, or the day someone
narrows the window to save money. `tests/test_provenance.py` asserts this limit
explicitly, so nobody reads the passing assistant-only test and concludes the
system is defended.

**The retrospective backfill is honest but blind.** It derives each label from
`memory_sources` joined to `messages.role`, which is the only evidence available
after the fact — `extraction_version` cannot tell a human API write from an
agent's. So the six model-authored facts already in the store are labelled
`manual`, not `assistant`. Only writes made after this change carry the truthful
label.

## Alternatives and why not

**Restore the archived predicate verbatim.** It reads `roles <= {"assistant"}`,
which is `True` for the empty set, so it refuses every write citing no messages —
including all manual API writes and most of this repository's own test suite. The
implemented predicate exempts empty evidence and labels it `manual`, where the
authority is the API-key holder rather than a message.

**Add `source_message_ids` to the judge's operation schema**, so the model cites
the evidence for each fact and the guard becomes live on the extraction path.
This is the right end state and is not done here. The extractor experiments record
that a previous operation-schema change collapsed recall fivefold, so this needs a
paired eval run rather than a confident edit.

**Reject model-authored API writes instead of labelling them.** That would
silently break two shipped Hermes features, and a configuration flag to switch it
is a flag nobody sets. A declared label is exactly as trustworthy as the
`owner_id` the same caller declares — and unlike a rejection, it produces a
number someone can watch.

**Put `source_role` in the Qdrant payload.** It has no read-path use, and adding
it would leave every existing point stale until a full reindex.

## Related

The archived spec logged refusals into an `events` journal, which
[0007](0007-no-events-journal.md) declines. Refusals therefore surface on
`ExtractionOutcome.rejected` — visible in the session-close response — and in a
warning log line carrying the same reason string the archived spec used, so the
two are greppable together.
