# 0082 — Assistant info is evidence under prompt v12, and nothing else the assistant says

    Status:        accepted
    Date:          2026-10-19
    Supersedes:    0006, in part (only for memories extracted under v12)
    Evidence:      to be measured; see ../measurements.md#to-be-re-measured
    Code:          prompts.py (V12, ASSISTANT_EVIDENCE, ASSISTANT_CHARS), provenance.py, extract.py (apply_ops, plan_dedup), judge.py (render_window), store.py (raw_indexable, recount_mentions), retrieval.py, profiles.py
    Contract:      ../04-judge.md, ../02-data-model.md, ../05-retrieval.md

## Decision

Under prompt v12 the assistant's own words may support one kind of memory:
assistant info — a specific answer, recommendation, list or plan the assistant
gave because the user asked, written as what the assistant said ("The assistant
recommended Hotel Lisboa Plaza for the user's March trip"). Every safeguard is
keyed on the prompt version that produced the operations, so v10 and v11 replay
exactly as before:

- any cited assistant span labels the memory `source_role='assistant'`, so a
  user's "ok" beside the assistant's paragraph cannot launder it into a
  user-sourced fact;
- such a memory is pending like every extracted one, ranks 0.05 below stated
  claims until a person confirms it (`core-retrieval-v3`, decisions/0084), and
  joins a profile only once confirmed; v1 and v2 do not return it at all;
- it cannot revise or delete a memory a person stated
  (`assistant_cannot_revise_stated`);
- restating something already remembered links the evidence and does not count
  as another mention: an assistant memory's `source_count` is always 1;
- it is never a dreaming premise (`dream.PREMISE_ROLES`).

The window shows 1,200 characters of each assistant turn instead of 220, so the
answer is visible to cite. Assistant turns can be raw-indexed too, behind
`MEMKIT_INDEX_ASSISTANT_TURNS`, and are returned only to a policy that trusts the
role.

## Why

LongMemEval's single-session-assistant questions ("which hotel did you
suggest?") are where Supermemory scores 100 and Mem OS scored nothing, by design.
The question is legitimate: a person asking what they were told is asking about
their own conversation. What 0006 protected against was different — the
assistant's assertions about the user or the world coming back as established
fact and gaining confidence by repetition. That loop is broken here by
construction: the memory says it is the assistant's, it can never be a premise,
it can never be reinforced, and it can never displace what a person said.

0006's text is kept as written. Three of its statements are no longer true and
are corrected here rather than there: `source_role` *is* in the Qdrant payload
and is filtered on; the extraction-path guard *does* fire, because every
operation now cites its own evidence; and Hermes' `memkit_remember` tool writes
`manual`, only the `on_memory_write` mirror writes `assistant`.

## Alternatives and why not

**Supermemory's stance unqualified** — assistant words as ordinary evidence. A
recommendation would then be indistinguishable from the user's own preference
and could supersede it.

**Raw passages only** — index assistant turns but never extract from them. It
answers the benchmark question in hybrid mode only, and leaves "what did you
recommend" out of the memory a profile or a search returns by default.

**A new role, `assistant_info`.** The existing `assistant` label already means
"the assistant's words", is constrained in the schema, and is what the Hermes
mirror writes; a second label would be a migration for a distinction the text
itself already carries.
