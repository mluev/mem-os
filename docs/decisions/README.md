# Decisions

One file per decision, immutable once accepted. Numbers are never reused.

A decision gets an entry here **only if a reader could reasonably ask "why not
the alternative?"** Factual corrections do not: when the Hermes documentation
said `input_schema` and the framework wanted `parameters`, that was simply wrong
and got fixed in the contract document, leaving no trace. Recording every
correction as a decision would bury the twenty that matter under fifty that
don't.

## Why a directory rather than one file

Code comments cite these by id. Before this log, roughly forty comments across
`src/` pointed at documents by path — and one pointed at a specific line number
in a file that has since changed by two hundred lines. A document path is a
maintenance surface; an accepted decision never moves, so `decisions/0031` stays
true forever.

## Format

```
Status:        accepted | declined | deferred | superseded
Date:          when it was decided
Supersedes:    an earlier id, or an archived document
Superseded by: filled in later, if ever
Evidence:      an anchor in ../measurements.md
Code:          where it lives
Contract:      the numbered document that states the outcome
```

Then **Decision** (one paragraph, imperative — what we do), **Alternatives and why
not** (the longer half when the status is `declined`), and for `deferred`, a
**Revisit when** with a stated trigger rather than "if it becomes a problem".

No entry restates a measured value; it links an anchor. `Status` and
`Superseded by` are the only fields ever edited after acceptance.

## The log

| id | decision | status |
|---|---|---|
| [0002](0002-four-genre-documentation.md) | Documentation splits into contract, measurement, decision, investigation | accepted |
| [0006](0006-source-role-and-may-write.md) | A fact may not derive solely from assistant turns, enforced at the write | accepted |
| [0007](0007-no-events-journal.md) | No append-only `events` journal and no redaction endpoint | declined |
| [0008](0008-judge-model.md) | The judge is `gemini-3.5-flash-lite` on the Gemini Developer API | accepted |
| [0010](0010-minimal-thinking-level.md) | `thinking_level=MINIMAL`, because reasoning bills as output | accepted |
| [0011](0011-no-prompt-caching.md) | No prompt caching for the extractor | declined |
| [0012](0012-no-batch-api.md) | Batch API is used nowhere; `use_batch` returns 422 | declined |
| [0015](0015-no-language-rule.md) | The "write in the user's language" prompt rule is removed | declined |
| [0016](0016-one-home-for-prompt-text.md) | `judge.build_prompt()` is the only path to prompt text | accepted |
| [0018](0018-background-tasks-not-a-queue.md) | Extraction runs as a FastAPI background task; there is no queue | accepted |
| [0019](0019-two-qdrant-collections.md) | Qdrant holds two collections, `memories` and `raw` | accepted |
| [0020](0020-reindex-loads-active-only.md) | Reindex loads `status='active'` only | accepted |
| [0025](0025-eager-embedder-load.md) | The embedder loads before the API accepts traffic | accepted |
| [0027](0027-importer-two-signals.md) | The transcript importer trusts two signals, not one | accepted |
| [0028](0028-no-similarity-floor.md) | No similarity floor on the read path | declined |
| [0029](0029-budget-tokens-not-elbow.md) | Output size is `budget_tokens`; no elbow cut, no request modes | declined |
| [0030](0030-dedup-stays-at-0.90.md) | Read-path dedup stays at 0.90 | accepted with doubt |
| [0031](0031-consolidate-at-0.92.md) | Consolidation clusters at cosine 0.92 | accepted |
| [0032](0032-cluster-connected-components.md) | Clusters are connected components, capped at six, partitioned by type | accepted |
| [0036](0036-content-based-eval-assertions.md) | Eval assertions are regexes over text, never memory ids | accepted |
| [0037](0037-answerable-by-partition.md) | Eval cases declare which targets can answer them | accepted |
| [0038](0038-stage-2-exit-gate.md) | Stage 2 was advanced on token density, not absolute MRR | accepted, with dissent |
| [0039](0039-relabel-v4-scoped-facts.md) | Legacy over-scoped facts are relabelled by a human | accepted, open |
| [0040](0040-prefetch-timeout-and-warmup.md) | Prefetch gets 0.4 s and a background warm-up | accepted |
| [0042](0042-no-tool-results-by-default.md) | `send_tool_results` defaults to false | accepted |
| [0050](0050-bm25-deferred.md) | BM25 hybrid retrieval is deferred | deferred |
