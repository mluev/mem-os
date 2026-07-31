# The judge

Two jobs, one table. The **extractor** reads a window of conversation and emits
operations on the memory store. The **consolidator** merges near-duplicate facts on a
nightly pass. Both log every call to `judge_runs`, so cost and behaviour are
auditable after the fact.

Note the name is historical: this is an extractor, not a scorer. There is no rubric
and no per-memory quality grade. What it "judges" is whether anything in a window is
worth remembering — and the answer is usually no.

## Model and provider

<!-- generated:judge-models -->
| model | provider | $/Mtok in | $/Mtok out | note |
|---|---|---|---|---|
| `gemini-3.5-flash-lite` | gemini | 0.30 | 2.50 | **default** |
| `gemini-3.1-flash-lite` | gemini | 0.30 | 2.50 | price unverified |
| `gemini-3-flash-preview` | gemini | 0.30 | 2.50 | price unverified |
| `gemini-3.5-flash` | gemini | 0.60 | 3.50 | price unverified |
| `claude-haiku-4-5` | anthropic | 1.00 | 5.00 | — |
| `claude-sonnet-5` | anthropic | 2.00 | 10.00 | introductory until 2026-08-31, then $3.00/$15.00 |
| `claude-opus-5` | anthropic | 5.00 | 25.00 | — |

An unknown model is priced at the most expensive known pair rather than at zero, so an unrecognised name cannot make a run look free.
<!-- /generated:judge-models -->

The default is reached through the **Gemini Developer API**: an API key alone, no GCP
project and no gcloud. Vertex AI is a second supported path, needing
`VERTEX_PROJECT` and `VERTEX_LOCATION` — not a requirement, and the SDK rejects an
API key passed together with a location, so it is one or the other.

Claude models stay wired so prompt versions can be compared on one eval.

Bigger models measured **worse** here, which is worth stating plainly because it is
counterintuitive: the larger ones invented facts from work logs and wrote whole
session changelogs as single memories. For a task that is mostly about declining to
store things, eagerness is the failure mode. See
[decisions/0008](decisions/0008-judge-model.md).

## Structured output

The output schema is enforced by the provider, not by parsing prose.

- **Gemini**: `response_mime_type="application/json"` plus `response_json_schema`.
- **Anthropic**: tool use with `"strict": true` and
  `"additionalProperties": false`.

The claim that tool use makes malformed JSON impossible holds **only in strict
mode**. Strict also requires every property in `required`, so optional fields are
declared nullable rather than omitted — which is why the operation schema has eleven
always-present fields, several of which are usually `null`.

Cross-field rules cannot be expressed in any JSON schema: `text` is required for ADD,
`id` for UPDATE and DELETE. Those are enforced in `judge.Op.parse`, which also:

- rejects an operation outside `ADD`/`UPDATE`/`DELETE`,
- rejects an ADD whose `type` is outside the vocabulary,
- clamps `importance` and `confidence` into `[0, 1]`,
- coerces an out-of-vocabulary `scope` to `user` rather than storing it,
- and applies the **travel test**: if the model answered that a fact would still be
  true in a different project, a `project` scope is promoted to `user`. One
  direction only, in code, not trusted to the prompt.

That last one is the interesting case. Asking the model "would this still be true
elsewhere?" as a required schema field, and acting on the answer in code, worked where
instructing it about scope in prose did not.

## The prompt

**The prompt text lives in `prompts.REGISTRY` and nowhere else.** This document
describes its shape; it does not reproduce it. See
[decisions/0016](decisions/0016-one-home-for-prompt-text.md) for why that rule is
structural rather than a matter of tidiness — a prose copy of the prompt was wrong
for weeks, and production ran a version nobody had measured.

The active version and the registry are generated into
[experiments/extractor-prompts.md](experiments/extractor-prompts.md).

### What the prompt is made of

- **The three-month test.** Would this still be worth knowing in three months? If it
  is only true of this session's work, it is not a memory. A changelog is not a
  memory.
- **One fact per operation, under 200 characters.** A cap, not a suggestion: without
  it the model produced 2,161-character session summaries stored as single memories.
- **Self-containment.** No "he", no "it", no "this project". Name the repository only
  when the fact is about the repository; a preference is not owned by the codebase it
  was discovered in.
- **Absolute dates.** The window carries the date the conversation happened, not just
  today's, so "last month" resolves against the right month when replaying history.
- **Assistant turns are context, never source.** They are there so pronouns resolve.
  This rule is good and is not sufficient on its own — the enforcement is at the
  write ([02-data-model.md](02-data-model.md)).
- **All three scopes matter**, and a window of technical work usually contains both a
  general preference and a decision about this codebase. This clause is also the main
  driver of recall: removing it collapsed extraction fivefold.
- **What to look for.** An explicit list — a stated or implied preference, an opinion,
  a decision and its reason, an identity fact, a constraint, a recurring irritation.
  A correction is the single richest signal: when the user rejects something, the
  reason is almost always a durable preference.
- **An empty list is legitimate** and common, but it should be a conclusion rather
  than a reflex.
- **Never store credentials**, tokens, keys, connection strings, file contents or
  command output. Extract the surrounding intent, never the value.

### Importance bands

`0.9–1.0` identity and hard constraints; `0.7–0.8` strong preferences and skills;
`0.4–0.6` narrow applicability; below that, do not emit at all. The bands exist
because without anchors the model returns 0.6 for everything, and an importance
signal with no variance is not a signal.

## The gate

The judge is called when the session closes, when ten unprocessed messages have
accumulated, or when the text contains an explicit request to remember. The
remember-pattern matches stems rather than whole words, in Russian and English,
because "запомни" alone misses "запомнить".

Windows with no user turn are skipped without a call. Assistant turns outnumber user
turns roughly ten to one on this corpus.

A window that fails three times is abandoned and marked processed. A failed call
normally leaves its messages unprocessed so the window retries once a transient cause
clears — but a systematic failure is not transient, and without a cap every new
message re-pays for the same window until the monthly ceiling stops it. Budget
refusals are deliberately **not** counted as failures, which is what makes them
retryable forever.

## Cost shape

Per-call and total figures are in
[measurements.md](measurements.md#cost). Three structural facts that do not change
with the numbers:

- Output is priced far above input, and on Gemini **reasoning bills as output**. So
  `thinking_level` is `MINIMAL` and fact length is capped
  ([decisions/0010](decisions/0010-minimal-thinking-level.md)).
- Reasoning tokens are counted into the output total. Omitting them would understate
  every cost figure — and the monthly ceiling is enforced against those figures, so an
  undercount disables the budget guard rather than merely misreporting.
- An unknown model name is priced at the most expensive known pair. A run once
  overstated its cost eighteenfold this way, which is the correct direction to be
  wrong in.

The ceiling is checked before each call. On breach the extractor returns
`monthly_cost_limit_reached` **without logging a run**, so the window stays retryable
next month rather than counting toward the abandonment cap.

No prompt caching: the stable prefix is far below every provider's minimum cacheable
length ([decisions/0011](decisions/0011-no-prompt-caching.md)). No Batch API
([decisions/0012](decisions/0012-no-batch-api.md)).

## The consolidator

Runs nightly at 04:00 via launchd, and on demand through
`POST /v1/admin/consolidate`. Four ordered steps:

1. **Expire by validity.** Facts whose `valid_until` has passed become `expired`.
   Before this step existed, date-expired facts were served as live.
2. **Demote the stale.** Facts not retrieved in 90 days lose importance. This is
   where `last_retrieved_at` and `retrieval_count` earn their cost.
3. **Merge near-duplicates.** Clusters are connected components at cosine 0.92,
   partitioned by owner and type, capped at six members
   ([decisions/0031](decisions/0031-consolidate-at-0.92.md),
   [decisions/0032](decisions/0032-cluster-connected-components.md)).
4. **Report.**

Expiry and demotion run **before** merging, so a merge never combines facts that
should already have expired.

The merge prompt's fourth rule is the important one: **if the memories are actually
about different things, return null.** Similar wording is not the same meaning, and
declining is a valid answer — the outcome reports `declined` separately from
`merged`.

A merged fact inherits every source message of its inputs, or
`GET /v1/memories/{id}/sources` breaks for it. It also inherits the **weakest**
provenance label in the cluster, so a merge cannot launder assistant-sourced text
into a user-sourced fact.

Nothing is deleted. Inputs become `superseded` with `superseded_by` set, so the chain
stays walkable and a bad merge is reversible.

### What consolidation cannot do

It combines what it is given; it does not adjudicate. The first real merge preserved
two incorrect spellings of the user's name, because both inputs contained one. A
merge cannot fix bad input, and treating the consolidator as a cleanup pass is a
category error.

It is also currently blocked more often by the type partition than by the threshold —
a live pair at cosine 0.9821 will never merge because the same claim was labelled
`project` on one write and `fact` on another
([measurements.md](measurements.md#consolidation)).
