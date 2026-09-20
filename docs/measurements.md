# Measurements

Every number produced by running something lives here, and only here. If a
figure appears in a numbered document, it is a configured constant — a threshold,
a port, a budget — not a measurement.

This rule exists because it was broken. Before this file, the same figures were
written into whichever document was open at the time, and the project ended up
asserting 87, 88 and 89 active facts; 247, 249 and 250 judge calls; 392, 395 and
408 mean eval tokens; and four different corpus sizes. None of them were lies.
They were snapshots of a moving system, recorded as though they were properties
of it.

Two consequences of that, both load-bearing:

**Every section carries a date and the command that produced it.** A reader who
wants to know whether a number still holds should be able to re-run it rather
than trust it. A measurement without a reproduction command is an anecdote.

**The corpus is live.** memkit ingests real conversations continuously, so every
count below moves. Treat them as an order of magnitude and a shape, not as a
fixed quantity. Anything that depends on an exact count should read it from
`GET /v1/admin/metrics` and `GET /v1/admin/health`.

Results that cannot be reproduced — because they measured a prompt version no
longer in production, or a one-off run — are not here. They are dated and frozen
in [`experiments/`](experiments/). The dividing line: **if a standing command
reproduces it, it belongs here and gets refreshed; if it was a one-off, it lives
in `experiments/` and is never updated.**

---

## Status, 2026-09-04

Every measurement below was taken on the single-owner build: SQLite as the source
of truth, an FTS5 lexical arm with no stemming, one owner, and a Mac with Metal.
That system no longer exists. The sections marked **superseded** are kept for the
shape they show and the reasoning that was built on them; **none of their numbers
describe the current system**, and none of the commands that produced them will
run — `sqlite3 data/memkit.db` has no database to open, `/v1/admin/stats` is now
`/v1/admin/metrics` and `/v1/admin/health`, and `/healthz` returns `{"ok": true}`
and nothing else.

What has to be re-measured before the next release, and with which command, is at
[the end of this file](#to-be-re-measured). Until each of those is run, the
thresholds they justify — the 0.30 lexical weight, the 0.18 abstention floor, the
0.90 dedup cosine, the 300 ms embedding gate — stand on evidence from a different
system.

---

## Snapshot: corpus and store

**Superseded 2026-09-04.** Counted in SQLite, for one owner, and split by a
`scope` field that no longer means what it meant here (it was the project
context; scope is now the authorization boundary). Re-measure with
`memkit doctor --json` and `curl -H "X-API-Key: …" localhost:8077/v1/admin/metrics`.

<!-- measured: 2026-07-31 · sqlite3 data/memkit.db + curl localhost:8077/v1/admin/stats -->

| | |
|---|---|
| messages | 4,285 |
| — user turns | 410 |
| — indexable user turns (≥25 chars) | 319 |
| — unprocessed | 6 |
| sessions | 91 |
| projects | 14 |
| memories, total | 100 |
| — active | 97 |
| provenance links (`memory_sources`) | 1,077 |

The 6 unprocessed messages are not a backlog to be cleared. The service ingests
continuously, so this number is normally small and non-zero; it is only worth acting
on if it grows without bound, which means the gate has stopped firing or the judge is
failing. A momentary zero is luck, not health.

Active facts by scope: **60 project, 37 user**. The user share is what determines
how much of the store is reachable without naming a project — see
[`decisions/0039`](decisions/0039-relabel-v4-scoped-facts.md) for why it matters
and why closing the gap is a manual job.

Active facts by provenance (`source_role`, added in schema 3):

| label | count | meaning |
|---|---|---|
| `user` | 89 | at least one user turn among the messages the fact cites |
| `manual` | 11 | written through the API with no message evidence |
| `assistant` | 0 | model's own words were the only evidence |

`assistant` at zero is the number to watch, not to celebrate. It is zero partly
because the guard works and partly because the retrospective backfill could not
distinguish an agent's API write from a human's — see the note under
[model-authored writes](#model-authored-writes) below.

Assistant turns outnumber user turns roughly 10:1 (3,875 to 410), which is why
the extractor fast-forwards past assistant-only windows rather than paying to
read them.

---

## Latency

**Superseded 2026-09-04** as a deployment figure. The command still reproduces —
`uv run memkit bench` — but 36.9 ms is BGE-M3 on Apple Metal, and the service now
runs on a CPU VPS where the same model is the one real performance risk
([`decisions/0069`](decisions/0069-docker-compose-on-coolify.md)). The MPS number
describes a development laptop and nothing that serves traffic.

<!-- measured: 2026-07-31 · uv run memkit bench -->

| | |
|---|---|
| embedding, median | **36.9 ms** |
| embedding, min / max | 36.1 / 56.1 ms |
| device | `mps`, BGE-M3, 1024 dimensions |
| cold model load | 11–17 s |

The stage-0 gate is under 100 ms on MPS: **pass**. `memkit bench` exits non-zero
if the dimension is not 1024, because a silent model swap would make every stored
vector incomparable without anyone noticing.

The cold load is why the API loads the embedder before accepting traffic rather
than lazily. See [`decisions/0025`](decisions/0025-eager-embedder-load.md).

Hermes prefetch latency is in [frozen results](#frozen-results) — it was measured
once against a running service and the figure that matters is already encoded as
the `prefetch_timeout` default.

---

## Cost

**Superseded 2026-09-04.** The spend total and the per-call token averages are
from prompt versions up to v8 on a single-owner corpus; v9 adds the ENTITIES
block to every call, so input tokens per call are higher by an unmeasured amount.
Re-measure with
`psql "$MEMKIT_DATABASE_URL" -c "select kind, model, count(*), sum(cost_usd) from judge_runs group by 1,2"`.
The per-model rate card in [`04-judge.md`](04-judge.md) is generated from code and
remains current.

<!-- measured: 2026-07-31 · sqlite3 data/memkit.db "select kind, model, count(*), sum(cost_usd) from judge_runs group by 1,2" -->

Total spend since the project began: **$0.5073** across 254 judge calls, against
a ceiling of $15/month enforced in code.

| kind | model | calls | spend |
|---|---|---|---|
| extract | `gemini-3.5-flash-lite` | 227 | $0.2336 |
| extract | `claude-sonnet-5` | 25 | $0.2683 |
| extract | `claude-haiku-4-5` | 1 | $0.0052 |
| consolidate | `gemini-3.5-flash-lite` | 1 | $0.0003 |

One call in 254 has ever errored.

Per-call cost, measured over successful runs: **~2,992 input / ~91 output
tokens**. Output is a twentieth of input by volume but priced eight times higher
on Flash-Lite, and on Gemini reasoning tokens bill as output — which is why the
prompt caps fact length and sets `thinking_level=MINIMAL`
([`decisions/0010`](decisions/0010-minimal-thinking-level.md)).

The per-model rate card is generated from `judge.MODELS` in
[`04-judge.md`](04-judge.md), not repeated here.

A full re-extraction of the entire corpus costs roughly **$0.29** on the default
model. That number is why Batch API is not implemented: halving $0.29 does not
pay for asynchronous complexity
([`decisions/0012`](decisions/0012-no-batch-api.md)).

---

## Retrieval eval

**Superseded 2026-09-04.** Every figure here was produced against the FTS5
lexical arm, which did no stemming, over a single owner's store. The 0.30-weight
arm now stems Cyrillic and ASCII
([`decisions/0065`](decisions/0065-postgres-russian-fulltext-replaces-fts5.md)),
which changes the input to the fusion the stage-2 gate turns on, and the corpus is
now scope-partitioned. The head-to-head shape — extracted facts beating raw turns
on MRR per token — is the claim worth re-testing, not the digits. Re-measure with
`uv run memkit eval --compare`.

<!-- measured: 2026-08-28 · uv run memkit eval --compare -->

`eval/queries.yaml` holds 47 cases grounded in the imported corpus. Each declares
`answerable_by`, because a question only a raw transcript can answer must not be
scored against the extracted facts
([`decisions/0037`](decisions/0037-answerable-by-partition.md)).

Re-run on 2026-09-03 after the stabilisation batch (profile kinds, session
drain, batched embedding, candidate slots, cluster cap, decay floor): recall
0.77, MRR 0.662, mean 295 tokens, MRR/1k 2.245 — unchanged within rounding, which
is the point. None of those changes was meant to move retrieval, and a change
that moves it unintentionally is a change to investigate. Raw MRR read 0.632
against 0.628, well inside run-to-run noise.

### Head-to-head, 31 shared cases

This is the comparison the stage-2 gate turns on, and the only one that is valid:
both targets answer the same questions.

| metric | raw turns (stage 1) | extracted facts (stages 2–3) |
|---|---|---|
| recall@10 | 0.74 | 0.77 |
| MRR | **0.628** | **0.662** |
| top-1 hits | 17 | 19 |
| reject violations | 0 | 0 |
| mean tokens | 1,299 | **294** |
| max tokens | 9,829 | 806 |
| MRR per 1k tokens | 0.484 | **2.251** |

As of 2026-08-28 (94 active facts, schema v6, FTS5 lexical arm) extracted facts
beat raw turns on every ranking metric for the first time, at 4.7× the MRR per
token. Both absolute MRRs sit below the 2026-07-31 figures (0.790/0.728) because
the corpus and pipeline changed underneath the same 31 questions — the v6
re-extraction replaced the fact set the July numbers were measured on. The
stage-2 judgement call is argued at
[`decisions/0038`](decisions/0038-stage-2-exit-gate.md), which records that the
gate **as written** was not met at the time.

Current misses:

- raw: `enbek-module`, `xling-signing-buttons`, `project-scoped-frontend`,
  `mem-profession`, `mem-over-engineering`, `mem-notiky-login`,
  `mem-attendance-decision`, `mem-project-scoped-portfolio`
- facts: `enbek-module`, `code-review-comments`, `xling-signing-buttons`,
  `project-scoped-frontend`, `mem-notiky-login`, `mem-attendance-decision`,
  `mem-project-scoped-portfolio`

### Single-target runs

`memkit eval --target raw` scores all 47 cases (0.94 recall, 0.818 MRR); `--target
memories` scores the 31 it can answer. **Those two printouts are not comparable**
— they cover different question sets. Every raw-vs-facts figure published before
`--compare` existed made that mistake.

---

## Consolidation

**Superseded 2026-09-04.** Clustering grouped by owner and context; it now groups
by scope and context, so a store with several scopes produces a different cluster
set from the same facts, and the timing was measured on a corpus a tenth the size
a team instance will hold. The BGE-M3 cosines in the sub-section below are a
property of the model, not of the store, and remain valid. Re-measure with
`uv run memkit consolidate` (dry run) and `--apply --merge`.

<!-- measured: 2026-08-28 · uv run memkit consolidate --apply --merge -->

Semantic clustering runs at cosine 0.92 over active facts sharing an owner and a
context, across kinds ([`decisions/0056`](decisions/0056-semantic-consolidation-merge.md)) —
the kind partition that hid the 0.9821 pair below is gone. First live merge run
(2026-08-28): the planner found exactly two clusters, both genuine duplicates
(the 0.9821 "Vibe OS concept/idea" pair below, and an apostrophe-variant pair of
the project description); the model confirmed both; two survivors carry
`consolidate-c2`, `manual` provenance, and every inherited evidence row. The
head-to-head eval re-run after the merge was regression-free (recall 0.77,
MRR 0.662 — identical to the pre-merge baseline) with two duplicate rows gone.
Cost: 2 merge calls, `judge_runs kind='merge'`.

### Model-authored writes

Six facts in the live store were written by an agent through Hermes rather than
extracted by the judge, at importance 0.8–0.95. Four of them describe the same
project. Pairwise cosines, measured with BGE-M3:

| cosine | pair | outcome |
|---|---|---|
| 0.9925 | two phrasings of "Vibe OS is … a library of vibe-coding skills" | **merges** — both `type=project` |
| 0.9821 | "Vibe OS idea: preserve global workflow context…" / "Vibe OS concept: retain global workflow context…" | **does not merge** |
| 0.6573–0.6801 | the description pair against the concept pair | correctly left alone |

The 0.9821 pair was the finding. It is a near-verbatim duplicate, well above the
threshold, and consolidation could never touch it — because clustering required a
shared `type`, and the agent labelled the same fact `project` on one write and
`fact` on the other. The threshold was not the binding constraint; the type
partition was. Recorded at
[`decisions/0032`](decisions/0032-cluster-connected-components.md). Resolved
2026-08-28: [`decisions/0056`](decisions/0056-semantic-consolidation-merge.md)
clusters within a context across kinds, and this exact pair was the first live
merge.

This is also the evidence behind restoring provenance
([`decisions/0006`](decisions/0006-source-role-and-may-write.md)): of eight facts
added in one session, seven came from the agent's own write path, unlabelled and
indistinguishable from something the user typed.

---

## Index consistency

**Superseded 2026-09-04.** The counterpart column is Postgres, not SQLite, and
neither the endpoint nor the field exists: `/healthz` returns `{"ok": true}` and
nothing else, and parity is now `memkit doctor`'s `index_parity` check, which
fails when active memories, indexed points and pending outbox rows disagree.
Re-measure with `memkit doctor --json`.

<!-- measured: 2026-07-31 · curl localhost:8077/healthz -->

| collection | points | SQLite counterpart | drift |
|---|---|---|---|
| `memories` | 97 | 97 active rows | 0 |
| `raw` | 319 | 319 indexable user turns | 0 |

Neither collection has an HNSW index built (`indexed_vectors_count` is 0), so
search is brute force. At this corpus size that is faster than the index would
be, and it is why the latency figures above are as low as they are — do not
expect them to hold at 10,000 facts.

`index_drift` is exposed in `GET /v1/admin/stats` as
`qdrant_memories - sqlite_active`. Any non-zero value means the derived index
disagrees with the source of truth and a `POST /v1/admin/reindex` is due.

---

## Tests

**Superseded 2026-09-04.** The count, the coverage and the wall clock all predate
the port. The suite now requires a real Postgres and truncates between tests
([`08-testing.md`](08-testing.md)), which changes the wall clock, and whole
modules were added for entities, full text and routing while the records-platform
and replay suites were deleted. Re-measure with
`uv run pytest -q --cov=memkit --cov-fail-under=75` and `pnpm --dir web test`.
The reasoning below — why pytest is the runner, and why the harness asserts on
blanked credentials — still holds.

<!-- measured: 2026-09-03 · uv run pytest -q --cov=memkit --cov-fail-under=75 ; pnpm --dir web test -->

| suite | runner | tests | coverage | wall clock |
|---|---|---|---|---|
| `tests/` | pytest | 243 (+1 skipped) | 79.6% | ~14 s |
| `web/` | vitest | 6 | — | ~3 s |

The skipped test is `test_qdrant_integration.py`, which needs a real Qdrant and
runs only with `MEMKIT_QDRANT_INTEGRATION=1`.

pytest is the runner: four suites use `parametrize`, `raises`, `monkeypatch`, or
module-level test functions, which `unittest discover` cannot collect. The
previous entry here claimed 399 tests under `unittest` and that pytest was not a
dependency; both were wrong, and the count could not have been produced by the
command it cited. What each layer covers, and what it deliberately does not, is
in [`08-testing.md`](08-testing.md).

The Python suite runs entirely offline. `tests/httpharness.py` asserts on every
setUp that no judge credential survived into the test settings, because the first
run of the HTTP suite made a real billed API call — the credential fields carry a
`validation_alias`, so the obvious way to blank them silently does nothing.

---

## Frozen results

These cannot be reproduced by a standing command: they measured prompt versions
no longer in production, or a state the system has moved past. They are kept
because the reasoning built on them is still load-bearing, and they are **not
current**.

A frozen result lives **with the decision it justified**, not here. This section is
an index — what was measured, when, and where the values are — deliberately without
the values, so that a one-off number has exactly one home like every other. Anything
below with no destination is one that has not needed a decision written for it yet.

| what was measured | when | values live in |
|---|---|---|
| v1→v6 prompt comparisons: per-window recall, scope shares, fact lengths | 2026-07-28 → 07-29 | [`experiments/extractor-prompts.md`](experiments/extractor-prompts.md) |
| the full-corpus extraction read that disagreed with the bench | 2026-07-29 | [`experiments/extractor-prompts.md`](experiments/extractor-prompts.md) |
| the first consolidation run, and what it revealed about merging | 2026-07-29 | [`decisions/0031`](decisions/0031-consolidate-at-0.92.md) |
| BGE-M3 cosines for restatements, paraphrases and distinct facts | 2026-07-29 | [`decisions/0030`](decisions/0030-dedup-stays-at-0.90.md) |
| the similarity-floor sweep | 2026-07-29 | [`decisions/0028`](decisions/0028-no-similarity-floor.md) |
| Hermes prefetch latency, cold and warm | 2026-07-30 | [`decisions/0040`](decisions/0040-prefetch-timeout-and-warmup.md) |
| golden-set v7 vs v8: recall, fp, leaks, cost per run | 2026-08-28 | [`decisions/0053`](decisions/0053-prompt-v8-date-anchor-and-failure-modes.md) |
| transcript-importer classification and rejection rates | 2026-07-28 | [`decisions/0027`](decisions/0027-importer-two-signals.md) |

The extractor bench has documented run-to-run variance of more than 2× on the
same prompt and corpus (0.24 to 0.60 facts per window across five runs of v4).
Any single run of it distinguishes nothing. This is the main reason measurements
here are dated rather than treated as settled.

---

## To be re-measured

Nothing below has a value yet, deliberately. Each row names what must be run
before the next release and the command that runs it; a row stays empty until
somebody runs it, because a guessed number here is worse than a blank one. Every
one of them was settled on the single-owner build and is now unevidenced.

| what | command | why it cannot be carried over |
|---|---|---|
| CPU embedding latency on the target VPS | `docker compose exec app memkit bench` | The only figure on record is 36.9 ms on Apple Metal. The gate is 300 ms; which rung of the ladder in [`decisions/0069`](decisions/0069-docker-compose-on-coolify.md) is needed — torch CPU, ONNX, more vCPU, a smaller model — is decided by this number and nothing else. Measure a cold load as well: it is what `/readyz` waits for on every redeploy. |
| retrieval eval on Postgres full text | `uv run memkit eval --compare` | The 0.30 lexical weight and the 0.18 abstention floor were tuned against an arm that did no stemming ([`decisions/0065`](decisions/0065-postgres-russian-fulltext-replaces-fts5.md)). Report the arms separately: a fused score that improves while the dense arm degrades is indistinguishable from one that improves both. |
| golden set, v8 against v9 | `uv run python -m eval.golden --variant gemini-3.5-flash-lite:v8 --variant gemini-3.5-flash-lite:v9` (paid; `--budget-usd` caps it) | v9 adds the ENTITIES block and the routing rules to every call. Three things need numbers: recall and false positives against v8, the added input tokens per call, and how often routing sends a fact somewhere the reviewer then moves. |
| consolidation over several scopes | `uv run memkit consolidate` then `--apply --merge` | Clustering is now per scope rather than per owner, so the cluster count and the wall clock both change shape. The 0.92 threshold and the six-member cap are unaffected in principle and unverified in practice. |
| suite size and coverage | `uv run pytest -q --cov=memkit --cov-fail-under=75` | The suite now needs a real Postgres and truncates between tests, whole modules were added and others deleted, so the count, the coverage and the wall clock in [Tests](#tests) are all stale. |

Two further numbers have no home yet and should get one when the instance has
been running for a week: the median and p95 of `/v1/memories/search`
(`retrieval_runs.timings`, which already records every arm separately), and the
share of pending memories a human actually reviews — the review queue is only
worth its complexity if it is read.

## Extractor prompt v8 against v9

<!-- measured: 2026-09-04 · uv run python -m eval.golden --variant gemini-3.5-flash-lite:v8 --variant gemini-3.5-flash-lite:v9 --budget-usd 0.80 -->

| metric | v8 | v9 |
|---|---|---|
| recall | 0.917 (22/24) | 0.917 (22/24) |
| false positives | 0 | 0 |
| credential leaks | 0 | 0 |
| invalid evidence | 0 | 0 |
| context correct | 8/14 | 6/14 |
| input tokens | 33,060 | 38,510 |
| cost | $0.0240 | $0.0257 |

Total spend $0.0496. Artifact `golden-20260904T093215Z.json`.

v9 matches v8 on every safety and recall gate and costs 16% more input tokens
for the entity block, which is the expected price. It is **not** promoted,
for two reasons.

Context accuracy fell from 8/14 to 6/14. The failures are the same class in
both versions -- a preference stated inside a workspace conversation is
recorded against that workspace instead of globally (rule 5) -- but v9 does it
more. That is the predictable cost of telling a model to think about where a
fact belongs: it scopes more things.

And v9's actual purpose, routing a fact to a teammate or an entity, is not
measured at all. The golden harness has no notion of an expected scope or
subject, so the feature that justifies the extra tokens is unverified. A prompt
cannot be promoted on a regression plus an untested claim.

Outstanding: teach the harness `entities`, `scope` and `subject`, add the
routing cases, then re-measure. `DEFAULT_VERSION` stays v8 until a successor
beats it on context and passes routing.

## Extractor prompt v8 against v10

<!-- measured: 2026-09-04 · MEMKIT_DATABASE_URL=postgresql://memkit@127.0.0.1:5433/memkit_golden uv run python -m eval.golden --variant gemini-3.5-flash-lite:v8 --variant gemini-3.5-flash-lite:v10 --budget-usd 1.20 -->

The v8-against-v9 section above ended with three things outstanding: teach the
golden harness `entities`, `scope` and `subject`; add routing cases; re-measure.
All three are done. The golden set is now 32 cases, 7 of them routing cases that
show a numbered ENTITIES block in the shape production builds it, and `routing`
is scored the way `context` is — with the rule that an expectation naming no
scope asserts the model emitted none, since a spurious scope is as wrong as a
missing one.

| metric | v8 | v10 |
|---|---|---|
| recall | 0.903 (28/31) | 0.903 (28/31) |
| false positives | 0 | 0 |
| credential leaks | 0 | 0 |
| invalid evidence | 0 | 0 |
| routing correct | 3/7 | 7/7 |
| fabricated entity numbers | 0 | 0 |
| context correct | 9/17 | 15/18 |
| input tokens | 42,072 | 59,639 |
| cost | $0.0313 | $0.0355 |

Artifact `golden-20260904T100020Z.json`. That run cost $0.0669; the whole
comparison — four full runs, plus six cheap subset runs (`--file` with the
routing cases, or with the routing and context-drift cases) while iterating —
cost $0.347 against a $1.20 cap.

**v10 is promoted.** It clears every gate: no leaks, no false positives, no
invalid evidence, recall equal to v8, routing 7/7 against 3/7, and context
*better* rather than worse — which is the whole point, since context accuracy is
what disqualified v9. It costs 42% more input tokens (13% more total cost, as
output dominates the bill on Flash-Lite).

### Why v10 works where v9 did not

v9 printed ENTITIES and ROUTING *before* CONTEXT, so the model was told to decide
where a fact belongs before it was told that context defaults to empty. Three
changes, each aimed at a measured failure and nothing else:

1. **Routing moved after CONTEXT**, so rule 5 is read first.
2. **Scope and context are named as different fields** — scope is where the
   memory lives, context is a qualifier on when the claim is true, and the
   workspace CONTEXT names is not a scope. v9 never said this, and a model given
   a second placement field used the first one to mean the same thing.
3. **Rule 5 asks a counterfactual** instead of listing phrases to pattern-match:
   said again tomorrow in another repo, would this sentence still hold?

v8's context failures are all one shape and they are visible in every run: a
preference stated while working in one repo gets that repo's context
(`direct-preference`, `preference-buried-in-project-work`,
`drift-working-style-via-correction`, `correction-implies-comment-preference`,
and the new `routing-own-preference-in-a-project-session` all fail this way in
at least three of four runs). v10 gets these right.

### Iterations, and what the measurement said about each

Four full runs, because two of the three changes above were wrong on the first
attempt and the harness said so.

| iteration | change | v10 result |
|---|---|---|
| 1 | routing after CONTEXT, scope≠context, counterfactual rule 5 | routing 6/7, context 16/17, recall 28/31 — but the guard case scoped a personal preference to the session's project |
| 2 | added the WRONG/RIGHT pair for that guard | guard fixed; recall fell to 27/31 |
| 3 | "the test decides the context field, not the wording — never generalise the claim or drop a specific" | recall back to 29/31, context 17/18, routing 5/7 |
| 4 | "the workspace CONTEXT names is not a scope; most operations need none" | recall 28/31, context 15/18, routing 7/7 |

Iteration 2's recall loss is the one worth remembering. Asking the model where a
fact belongs made it write *more general* claims, and a general claim loses
specifics: `drift-reverse-guard-generic-wording` went from "Authentication uses
OTP sent to email with no password; dev@notiky.local in dev" to "In dev, use
dev@notiky.local for login" — the mechanism dropped, the case missed. One clause
saying the counterfactual decides the context field and never the wording
recovered it. Generalisation pressure and recall are the same dial.

A clause that bought nothing was also removed rather than kept: a WRONG/RIGHT
pair for the unlisted-project rule made no difference across two runs, so it does
not earn its tokens.

### What the model still gets wrong

**An unlisted project gets approximated to a listed one.** `cine` appears in the
caller context and in the sentence and has no number in the block;
gemini-3.5-flash-lite scoped that fact to `memkit` — the first listed project —
in seven consecutive runs, with the rule stated three ways, including as a
WRONG/RIGHT pair. It came out right only in the final run. Treat this as unfixed
at this model size: a fact about an entity the instance does not know may land in
the wrong project's scope. `judge.extract` cannot catch it, because the number is
real; only a human reviewing the scope can.

**Run-to-run variance is large enough to matter.** The extractor calls Gemini
with no temperature set, so sampling is at the provider default, and one run of
seven routing cases is not a stable measurement: v10 scored 5/7, 6/7, 6/7, 6/7,
6/7, 7/7 across six measurements of near-identical text. The promotion decision
rests on the final run *and* the fact that v10 beat v8 on routing and on context
in all four full runs. Anyone re-running this should expect ±1 on recall and ±1
on routing, and should not read a single run as a verdict.

**Two cases neither version passes.** `correction-abstraction` (a preference
implied by "зачем? есть же company store") returns nothing under v8 or v10 in any
run, and `mixed-user-and-project` yields the general rule but drops the second,
concrete fact. They are left failing on purpose: both are real corpus shapes, and
a golden case weakened to make a version pass measures nothing.

## Jev semantic judgments: first experiment

<!-- measured: 2026-09-20 · commands and artifacts below -->

**Decision:** retain an explicit experiment component and reranker adapter. Do not
enable a hard evidence gate: its synthetic results did not transfer to the current
extractor outputs. Duplicate verification is the most promising next production
experiment. No production settings, memory rows, or deployed behavior changed.

The [implementation and runbook](experiments/jev.md) cover the component. All calls
resolved to `jev-1.13.0`. The synthetic corpus has **88 unique cases**: 50 development
and 38 heldout. Development versions ran twice each; the selected `v2` ran three
times on heldout. Repeats measure variability, not additional independent samples.
Labels were authored for this experiment, not independently human-adjudicated.

Corpus SHA-256:
`ed15b53c96e6ca3530c924a65b2d07d6c53a8139ad5e9ed40db7effef188be3b`.
Selected question-set SHA-256:
`df06c3fd7ed0eff7ea7a81f9253a0a84f9315e7b9628e3370d3f9cb9bf116e04`.

### Development iterations

Fixed policy thresholds before heldout: supported probability ≥0.90, equivalent
probability ≥0.90, relevance score ≥2 on the 0–3 rubric. No thresholds were lowered
to make a corpus pass. Relation labels themselves are recorded independently from
the high-probability decision to treat two facts as duplicates.

| Measure, repeated development observations | v1 | v2 | v3 |
|---|---:|---:|---:|
| Supported examples accepted | 10/14 | 12/14 | 12/14 |
| Unsupported examples accepted | 0/26 | 0/26 | 0/26 |
| Five-way relation label correct | 33/36 | 35/36 | 33/36 |
| Equivalent pairs accepted as duplicates | 6/8 | 6/8 | 6/8 |
| Non-equivalent pairs accepted as duplicates | 0/28 | 0/28 | 0/28 |
| Answerable queries with relevant top result | 20/20 | 20/20 | 20/20 |
| Unanswerable queries correctly empty | 4/4 | 4/4 | 4/4 |
| Adapter/provider errors after correction | 0 | 0 | 0 |

v2 made subject/reference and explicit-correction semantics clearer. v3 aligned
the support criteria with the permission to resolve contextual references, but did
not improve acceptance. The relation question was unchanged between v2 and v3;
the different label counts therefore also expose model variation near boundaries.
No corpus labels were changed after observing results. The remaining Russian
equivalence example is linguistically ambiguous and needs independent review.

The first v1 attempt rejected 16/100 responses in the adapter, before any question
iteration. Investigation of the actual responses showed separately rounded scores
and probabilities. The adapter now validates within the numerical rounding envelope
instead of demanding exact reconstruction. A captured synthetic response is an
offline regression test. This failed attempt is retained as `data/jev/v1-dev.json`;
the comparable v1 baseline is `data/jev/v1-dev-fixed.json`.

### Heldout results

The following counts are **unique cases**; each result was reproduced across all
three runs, except that the general relation classifications remain subject to the
limitations described below.

| Task | Selected Jev policy | Comparison |
|---|---|---|
| Support classification | 14/14 correct: accepted 5 supported, held 9 unsupported | Exact citation existence alone cannot make this distinction; this is not an end-to-end extractor baseline |
| Equivalent versus non-equivalent | 12/12 correct: found 3 equivalents, accepted 0 of 9 non-equivalents | Cosine ≥0.90 found 0 of the 3 equivalents and accepted 4 non-equivalents |
| Five-way relation label | 10/12 correct | Both mismatches were addition versus unrelated; neither led to a duplicate decision |
| Relevant top result | 10/10 answerable queries | Actual BGE dense-only ordering also scored 10/10 |
| Empty result when nothing answers | 2/2 unanswerable queries | Dense-only ordering without abstention returns candidates by construction |
| Relevant candidate retention | 11/11 across the answerable queries | Includes a query needing two separate facts |

The heldout relation mistakes concerned a person's different residences at
different times, and test versus production databases. The model called them
additions rather than unrelated situations; equivalent probabilities stayed zero.
This supports testing a narrow duplicate decision, not automatically taking actions
from all five labels.

On development, dense-only ordering put the relevant item first in 9/10 answerable
queries; Jev did so in 10/10. **The heldout result does not demonstrate a ranking
gain**, since both methods were already perfect there. Candidate lists contain only
three memories, so this is not a realistic large-corpus retrieval benchmark.

The BGE baseline uses the configured, pinned `BAAI/bge-m3` embeddings, not invented
similarity scores. It compares semantic pairs in isolation and ranks the same
provided shortlists. It does not reproduce production scope/context candidate
selection, hybrid lexical/identifier fusion, or the production relevance floor.
The synthetic pairs are deliberately challenging, so the cosine error rate must
not be presented as the deployed system's error rate.

Heldout language counts: English 26, Russian 6, Uzbek 4, mixed 2. These slices are
too small to establish multilingual reliability. The all-correct binary outcomes
also do not establish a low production error rate.

### Current-extractor transfer check: rejected hard gate

Generated operations with `gemini-3.5-flash-lite` and extractor prompt `v10` on the
existing 32-case golden corpus. Cached those operations once, validated exact user
citations, and evaluated identical outputs with Jev v2 and v3.

| Measure | Current extractor after exact-source checks | With v2 support gate | With v3 support gate |
|---|---:|---:|---:|
| Expected facts retained | 27/31 | 15/31 | 15/31 |
| Golden false positives | 0 | 0 | 0 |
| Semantic judgments | — | 29 | 29 |
| Semantic service errors | — | 0 | 0 |

The gate lost expected facts without fixing a measured false-positive problem in
this run. Numerous straightforward Russian directives paraphrased as memories had
supported probabilities below 0.90. Known aliases and a recording-date anchor were
also absent from the semantic check's state, unlike the generative extractor's
prompt. That is a concrete state-construction limitation, not proof that Jev could
never verify these claims. It is sufficient evidence not to activate this gate.

This transfer set is an additional diagnostic corpus, not a newly independent
heldout sample. The regex-based golden scorer also does not certify every detail
in an emitted claim. The comparison isolates gate retention on fixed extractor
outputs; it does not execute the entire database write path.

A final `v4` experiment changed support to a direct binary Noul question, including
explicit treatment of imperatives as preferences/rules. At the same experimental
0.90 probability threshold it accepted 10/14 repeated supported development
observations, accepted 0/26 unsupported observations, and retained 16/31 expected
facts from the cached extractor outputs. That does not rescue the hard gate.
Because the heldout set had already been opened, v4 was evaluated only on development
and the extractor diagnostic set; it was not promoted using a reused heldout score.
Artifacts: `data/jev/v4-dev.json` and `data/jev/extractor-v4.json`.

### Reproduction and artifacts

```bash
uv run python -m eval.semantic --split dev --version v1 --repeat 2 --embeddings --output data/jev/v1-dev-fixed.json
uv run python -m eval.semantic --split dev --version v2 --repeat 2 --embeddings --output data/jev/v2-dev.json
uv run python -m eval.semantic --split dev --version v3 --repeat 2 --embeddings --output data/jev/v3-dev.json
uv run python -m eval.semantic --split heldout --version v2 --repeat 3 --embeddings --output data/jev/v2-heldout.json
uv run python -m eval.semantic_extraction --version v3 --output data/jev/extractor-v3.json
uv run python -m eval.semantic_extraction --version v2 --output data/jev/extractor-v2.json
uv run python -m eval.semantic --split dev --version v4 --repeat 2 --embeddings --output data/jev/v4-dev.json
uv run python -m eval.semantic_extraction --version v4 --output data/jev/extractor-v4.json
```

Raw artifacts under `data/jev/` are local and gitignored. They retain per-case
judgments, expected labels, language slices, input fingerprints, model identities,
and usage. The original generative outputs are cached in
`data/jev/golden-extractor-outputs.json`. Two extraction reports initially displayed
zero usage because only scoring counters had been populated; their accounting was
corrected from the retained original responses without changing or rerunning any
judgment. The runner now records that usage directly, separately from Jev usage.

### Reliability issue found during regression checks

The full backend regression run exposed an existing window-claim race: competing
workers claimed a ten-message window as separate groups of 9 and 1. A stronger
regression with 25 ordered messages reproduced interleaved windows immediately
before the fix. Row-level `SKIP LOCKED` prevented duplicate rows but did not make
window assembly atomic.

`extract.claim_window` now takes a per-session transaction advisory lock while
assembling and leasing the window, and expired-claim cleanup is scoped to that
session. The lock ends before any model call. A regression runs 12 races with 8
workers and asserts intact contiguous windows; another holds a different session's
lock and expired rows while verifying that the next session can still claim.
This is an ordinary database correctness fix discovered by the experiment's
verification, not a capability delegated to Jev.

Final backend validation: `uv run pytest -q tests --cov=memkit --cov-report=term
--cov-fail-under=75` passed **614 tests and 49 subtests**, with 2 optional tests
skipped. Coverage was **78.43%** overall and **94%** for the semantic adapter.
`uv build`, repository lint, changed-file formatting, golden/semantic corpus
validation, and the documentation contract check passed. A root-level pytest
attempt encountered an independently added CLI package whose import was not
installed in this environment; the reported successful run targets the backend's
`tests/` directory. Unrelated concurrent formatting edits were left untouched.

## Modular semantic blocks and durable reports

Date: 2026-09-20. Model: `jev-1.13.0`; frozen questions `v2`; equivalent-fact
probability floor 0.90 and relevance score floor 2.0. Exact results and provenance
for **13 experiments**, including prior rejected variants, are retained in the
[experiment archive](experiments/README.md). Implementation and configuration:
[ADR 0072](decisions/0072-semantic-blocks-and-experiment-archives.md).

### Transfer across fictional scenarios

`eval/corpora/multiscenario-v1.json` adds 72 authored probes in **12 related scenario
families**, covering development, education and personal assistance in English,
Russian, Uzbek and mixed language. Labels and thresholds were frozen before the
run. Each probe was run twice: 144 observations, not 144 independent cases or users.
No provider errors. The labels have not had independent human review.

- Five-way relation: 48/48 repeated observations correct. With the stricter 0.90
  probability policy, Jev accepted 20/24 true-duplicate observations and 0/24
  nonduplicates. Correct classification alone does not mean a threshold accepts it.
- Cosine at 0.90 accepted 22/24 true duplicates and 4/24 nonduplicates. Jev's
  conservative threshold misses some Russian/Uzbek paraphrases; those facts remain
  separate rather than being discarded.
- Ranking: 24/24 answerable observations had a relevant first result, tied with
  BGE dense ranking. Filtering retained 42/42 labeled relevant fragments and
  abstained on 24/24 unanswerable observations. No ranking advantage is claimed.
- Support: accepted 23/24 supported observations and 0/24 unsupported observations.
  This synthetic result still does not transfer well enough to gate extraction.

### Actual batched duplicate block

A separate live diagnostic used `SemanticBlocks.verify_duplicates`, including its
real batched state/question shape, on the 24 unique relation pairs and measured
BGE proposals. It reuses the opened scenario set and is not fresh heldout evidence.

| Outcome | Cosine proposal | Proposal + Jev verification |
| --- | ---: | ---: |
| True duplicates accepted / 12 | 11 | 9 |
| Nonduplicates incorrectly accepted / 12 | 2 | 0 |
| Precision | 84.6% | 100% |
| Recall | 91.7% | 75.0% |
| Overall binary accuracy | 87.5% | 87.5% |

This is a precision/recall tradeoff, not an accuracy gain. Adopted as an explicitly
configured conservative veto: provider failure or uncertainty keeps a new row.
It does not broaden cosine candidate selection. Source/citation permissions and
same-scope/subject/context/kind/validity constraints are tested separately through
real PostgreSQL. The write transaction rechecks revision and eligibility under a
row lock, preventing a stale comparison from attaching evidence to an edited fact.

### Full hybrid retrieval diagnostic

`eval.semantic_hybrid` executes the actual `retrieval.explain` path in a disposable
PostgreSQL cluster with real configured BGE embeddings and Qdrant's local exact
vector engine. It never opens the configured production database. All 25 fictional
memory texts are in one pool; query-specific expected fragments remain fixed.
The experiment applies the existing relevance floor, hybrid weights, limit 30 and
800-token budget, then compares the optional Jev filter at 2.0.

| Outcome over 24 queries | Hybrid baseline | Hybrid + Jev filter |
| --- | ---: | ---: |
| Relevant first result / 12 answerable queries | 12 | 12 |
| Relevant fragments retained / 21 | 21 | 21 |
| Correct empty results / 12 unanswerable queries | 0 | 12 |
| Irrelevant fragments returned across queries | 334 | 0 |
| Provider errors | — | 0 |

Useful gain: less irrelevant context and correct silence, without a measured loss
on this fixture. This is a small, reused synthetic diagnostic. It does not measure
server ANN recall, production load, independent users or every broad preference
query. Filtering remains an explicit switch with baseline fallback on outages;
the distributed default is off.

### Evidence-state iteration that did not work

`eval.semantic_extraction --version v2 --state-version anchored` reused the exact
32 cached golden extractor outputs and added known entities and recording dates
to the verification state. The baseline retained 27/31 expected facts; a hypothetical
hard gate retained only **14/31**, with 0 false positives before or after and 0
service errors. Minimal-state v2 previously retained 15. One run does not attribute
that difference solely to the state change, but the expanded state clearly did
not rescue the gate. Runtime support is therefore diagnostic only.

### Retention, reproducibility and validation

All live runners now automatically save a new immutable folder under local
`data/experiments/`, containing exact results, a schema-versioned manifest and a
readable report. The manifest retains dataset/question hashes, model IDs, thresholds,
labels, language/scenario/cohort slices, source hashes, errors and decisions.
Execution provenance and archival provenance are distinct. Historical execution
identity is unknown where it was not originally recorded; it is never filled in
with today's code. Public retained reports use synthetic data only.

The same runner accepts external labeled corpora and another TypeSafe model pin;
the archive interface also accepts other technologies' results. Comparison rejects
mismatched dataset identity, split, threshold policy or label provenance. CI checks
both corpora and archived artifact hashes without paid calls.

Reproduce the new live diagnostics:

```bash
uv run python -m eval.semantic --corpus eval/corpora/multiscenario-v1.json --split heldout --version v2 --repeat 2 --embeddings --data-class synthetic
uv run python -m eval.semantic_dedup
uv run python -m eval.semantic_hybrid
uv run python -m eval.semantic_extraction --version v2 --state-version anchored --output data/jev/extractor-v2-anchored.json
```

Backend validation: **636 passed, 2 skipped, 49 subtests**, coverage **79.03%**.
The new tests exercise actual writes under semantic approval, rejection and outage;
shadow/filter/rerank policies; authorization before egress; stale revisions and
changed subject/context/trust/expiry; advisory support through extraction; response
key-order independence; and archive integrity/comparison rules. All ordinary tests
blank credentials and disable runtime semantic switches, even if local `.env`
contains an enabled profile.

Final packaging and configuration check: wheel/sdist built successfully and the
wheel contains all three semantic modules. After enabling the local profile,
59 focused semantic/report tests still passed offline. All 13 public artifact
hashes, both corpus schemas, golden schema, lint, formatting, documentation checks
and `git diff --check` passed. Exact credential scanning found no Jev key in
published reports or semantic sources. The local `.env` profile takes effect on
the next service startup; no service restart or remote deployment was performed.

## Detail-preserving context experiments

2026-09-20: [full report and retained experiments](experiments/context-details.md).
New frozen confirmation scenarios retained 36/40 details with contribution judgments
versus 27/40 with evidence-aware hybrid search; irrelevant returns fell from 79 to 1.
The real two-collection diagnostic retained 37/40 with optional compaction versus
34/40 without Jev, with irrelevant returns falling from 70 to 0. Source-first
selection without Jev retained all 40 details but added 74 irrelevant returns.
These are small authored synthetic fixtures, not production-user measurements.


## Correctness and HTTP readiness, 2026-09-20

[Whole-system review](reviews/2026-09-20-production-readiness.md) and
[frozen HTTP measurements](experiments/http-readiness.md) record the implementation,
reproduction commands, archive provenance, and limitations.

The final full Python gate on PostgreSQL 16.15 with Qdrant 1.18.2 passed 926 tests
and 142 subtests with 85.56% backend coverage. Three additional actual-HTTP client
isolation tests and four subtests then passed on the same database version. These
are 929 distinct Python tests and 146 subtests. Run with disposable service URLs:

```sh
MEMKIT_TEST_DATABASE_URL="$DISPOSABLE_TEST_DATABASE_URL" \
MEMKIT_QDRANT_INTEGRATION=1 \
MEMKIT_QDRANT_TEST_URL="$DISPOSABLE_TEST_QDRANT_URL" \
uv run pytest -q --cov=memkit --cov-report=term --cov-fail-under=75
```

The dashboard passed 79 unit tests and 11 browser tests using `pnpm --dir web test`
and `pnpm --dir web test:e2e`; lint, type checking and build also passed.

Real HTTP retrieval made 680 requests with pinned BGE-M3 on local MPS, PostgreSQL
17.4 with fsync on, and Qdrant 1.18.2. No request, content-budget, or combined-result
limit failures occurred. Facts retained 20/25 unique expected details; including
raw evidence retained 25/25. All representations returned context for all six
unanswerable questions: 0/6 strict empty-context abstentions. Heldout p95 latency
was 65–84 ms at concurrency 1 and 357–411 ms at concurrency 8; throughput plateaued
around 20–23 requests/s. These short synthetic runs do not establish sustained
CPU deployment capacity or answer-generation accuracy. No paid calls, ranking
promotion, or embedding-model change occurred.

```sh
uv run python -m eval.readiness_http --split dev --output docs/experiments/runs
uv run python -m eval.readiness_http --split heldout --output docs/experiments/runs
uv run python -m eval.readiness_http --split dev --budget 32 --limit 1 --concurrency 4 --repeats 1 --output docs/experiments/runs
```

The heldout set has now been inspected; subsequent ranking changes require fresh
heldout data. Locally retained release and schema-v2 rollback artifacts have
checksums and build commands in the [build manifest](releases/2026-09-20-build.json).
