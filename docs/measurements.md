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

**The corpus is live.** memkit runs as a launchd agent on the author's machine
and ingests real conversations continuously, so every count below moves. Treat
them as an order of magnitude and a shape, not as a fixed quantity. Anything that
depends on an exact count should read it from `GET /v1/admin/stats`.

Results that cannot be reproduced — because they measured a prompt version no
longer in production, or a one-off run — are not here. They are dated and frozen
in [`experiments/`](experiments/). The dividing line: **if a standing command
reproduces it, it belongs here and gets refreshed; if it was a one-off, it lives
in `experiments/` and is never updated.**

---

## Snapshot: corpus and store

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

<!-- measured: 2026-07-31 · uv run memkit eval --compare -->

`eval/queries.yaml` holds 47 cases grounded in the imported corpus. Each declares
`answerable_by`, because a question only a raw transcript can answer must not be
scored against the extracted facts
([`decisions/0037`](decisions/0037-answerable-by-partition.md)).

### Head-to-head, 31 shared cases

This is the comparison the stage-2 gate turns on, and the only one that is valid:
both targets answer the same questions.

| metric | raw turns (stage 1) | extracted facts (stages 2–3) |
|---|---|---|
| recall@10 | 0.90 | 0.84 |
| MRR | **0.790** | **0.728** |
| top-1 hits | 22 | 21 |
| reject violations | 0 | 0 |
| mean tokens | 1,674 | **423** |
| max tokens | 9,829 | 1,045 |
| MRR per 1k tokens | 0.472 | **1.723** |

Extracted facts lose on absolute MRR and win 3.7× on MRR per token. Raw turns
cannot fit the 600–1,000-token budget the read path targets — their mean answer
alone is 1,674 tokens, and their worst is 9,829. What to conclude from that is a
judgement call, argued in the open at
[`decisions/0038`](decisions/0038-stage-2-exit-gate.md), which records that the
gate **as written** was not met.

Current misses:

- raw: `mem-profession`, `mem-over-engineering`, `mem-notiky-login` — all
  memory-shaped questions a transcript search cannot answer
- facts: `lms-module`, `code-review-comments`, `mem-review-expectations`,
  `mem-page-titles`, `mem-migration-style`

### Single-target runs

`memkit eval --target raw` scores all 47 cases (0.94 recall, 0.818 MRR); `--target
memories` scores the 31 it can answer. **Those two printouts are not comparable**
— they cover different question sets. Every raw-vs-facts figure published before
`--compare` existed made that mistake.

---

## Consolidation

<!-- measured: 2026-07-31 · uv run memkit consolidate --dry-run -->

Clustering runs at cosine 0.92 over facts sharing an owner and a `type`.

### Model-authored writes

Six facts in the live store were written by an agent through Hermes rather than
extracted by the judge, at importance 0.8–0.95. Four of them describe the same
project. Pairwise cosines, measured with BGE-M3:

| cosine | pair | outcome |
|---|---|---|
| 0.9925 | two phrasings of "Vibe OS is … a library of vibe-coding skills" | **merges** — both `type=project` |
| 0.9821 | "Vibe OS idea: preserve global workflow context…" / "Vibe OS concept: retain global workflow context…" | **does not merge** |
| 0.6573–0.6801 | the description pair against the concept pair | correctly left alone |

The 0.9821 pair is the finding. It is a near-verbatim duplicate, well above the
threshold, and consolidation will never touch it — because clustering requires a
shared `type`, and the agent labelled the same fact `project` on one write and
`fact` on the other. The threshold is not the binding constraint here; the type
partition is. Recorded at
[`decisions/0032`](decisions/0032-cluster-connected-components.md).

This is also the evidence behind restoring provenance
([`decisions/0006`](decisions/0006-source-role-and-may-write.md)): of eight facts
added in one session, seven came from the agent's own write path, unlabelled and
indistinguishable from something the user typed.

---

## Index consistency

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

<!-- measured: 2026-07-31 · .venv/bin/python -m unittest discover -s tests -t . ; pnpm --dir web test -->

| suite | runner | tests | wall clock |
|---|---|---|---|
| `tests/` | stdlib `unittest` | 399 | ~3 s |
| `web/` | vitest | 6 | ~3 s |

No pytest: it is not a declared dependency and the suite does not need it. What
each layer covers, and what it deliberately does not, is in
[`08-testing.md`](08-testing.md).

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

| what | when | where |
|---|---|---|
| v1→v6 prompt comparisons, per-window recall and scope shares | 2026-07-28 → 07-29 | [`experiments/extractor-prompts.md`](experiments/extractor-prompts.md) |
| full-corpus extraction read: 247 calls, $0.50, 1 error, 88 active facts | 2026-07-29 | [`experiments/extractor-prompts.md`](experiments/extractor-prompts.md) |
| first consolidation run: one cluster at 0.9278, $0.00025, 88 → 87 facts | 2026-07-29 | [`decisions/0031`](decisions/0031-consolidate-at-0.92.md) |
| BGE-M3 dedup cosines: 1.0000 / 0.8979 / 0.8871 / 0.8620 / 0.7422 | 2026-07-29 | [`decisions/0030`](decisions/0030-dedup-stays-at-0.90.md) |
| similarity-floor sweep: off 0.87, 0.40 → 0.87, 0.45 → 0.84, 0.50 → 0.77 | 2026-07-29 | [`decisions/0028`](decisions/0028-no-similarity-floor.md) |
| Hermes prefetch: ~840 ms cold, 75–93 ms warm | 2026-07-30 | [`decisions/0040`](decisions/0040-prefetch-timeout-and-warmup.md) |
| importer classification: 58,666 lines → 4,411 turns kept, 304 indexable | 2026-07-28 | [`decisions/0027`](decisions/0027-importer-two-signals.md) |

The extractor bench has documented run-to-run variance of more than 2× on the
same prompt and corpus (0.24 to 0.60 facts per window across five runs of v4).
Any single run of it distinguishes nothing. This is the main reason measurements
here are dated rather than treated as settled.
