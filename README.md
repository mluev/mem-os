# memkit

A local memory service for agents. SQLite is the source of truth, Qdrant is a
derived index, embeddings run locally on Apple Silicon, and an LLM judge (from
stage 2) extracts durable facts from conversation windows.

Design docs live in [`docs/`](docs/); read [`docs/README.md`](docs/README.md)
first. This file covers what is built and how to run it.

## Status: stages 1–3 + local admin complete

Working now: ingest, judged extraction, composite retrieval, rebuild-from-truth,
an eval harness, and a local dashboard for reading and correcting the corpus.

| Stage | Scope | State |
|---|---|---|
| 1 | foundation, transcript importer, eval | **done** |
| 2 | extractor (judge), gate, cost ceiling | **done** — whole history processed, 247 calls, $0.50, 88 facts |
| 3 | score formula, scope filters, dedup, budget fill | **done** |
| 4 | nightly consolidator | **done** — merge, expiry, demotion, launchd at 04:00 |
| 5 | Hermes `MemoryProvider` plugin | **done** — goal verified: a fact from one session surfaced in another |
| 6 | local admin dashboard | **done** |

`POST /v1/admin/reextract` is documented in
[docs/03-api.md](docs/03-api.md) but is not implemented; `memkit backfill` after
resetting `messages.processed` covers the same ground for now.

**On the stage-2 exit gate.** `docs/06-roadmap.md` says the eval must beat stage
1 before moving on. Taken literally it does not: 0.737 MRR against 0.806. Taken
as the question it was asking — is the extractor earning its keep — it does, on
token density, and the remaining gap is attributed to one named defect rather
than to extraction quality. The numbers and the argument are below; decide it on
those, not on the single headline.

If no judge credential is configured, `POST /v1/messages` returns
`extraction_queued: false`; manual memories and retrieval still work. Set
`GEMINI_API_KEY` (default model) or `ANTHROPIC_API_KEY`, then:

```bash
uv run memkit backfill --dry-run
```

## Quick start

Requires Docker and [uv](https://docs.astral.sh/uv/). Python 3.12 is pinned
deliberately: torch and sentence-transformers have no reliable wheels for 3.14.

```bash
cp .env.example .env          # then set MEMKIT_API_KEY
docker compose up -d          # Qdrant on 127.0.0.1:6333
uv sync
uv run memkit bench           # phase-0 gate: must be under 100 ms on MPS
```

Import your Claude Code history and check retrieval:

```bash
uv run memkit import-claude-code --dry-run   # classification report, writes nothing
uv run memkit import-claude-code
uv run memkit eval
uv run memkit serve                          # 127.0.0.1:8077
```

The built admin opens at `http://127.0.0.1:8077/ui/`. For frontend development:

```bash
pnpm --dir web install
pnpm --dir web dev                            # 127.0.0.1:5173/ui/
```

The Vite proxy injects the API key from the root `.env`; production asks once
and keeps the key in browser local storage.

## Endpoints

All `/v1` routes require an `X-API-Key` header. The service binds loopback only.

| Method | Path | Notes |
|---|---|---|
| GET | `/healthz` | no auth; reports Qdrant, embedder device, point counts |
| POST | `/v1/messages` | idempotent when given `external_source` + `external_id` |
| POST | `/v1/search` | stage 1 returns raw turns under `raw`; `memories` stays empty |
| POST | `/v1/memories` | add a fact by hand, bypassing the judge |
| GET | `/v1/memories` | paginated listing with filters and stable sorting |
| PATCH / DELETE | `/v1/memories/{id}` | edit, expire/restore, or hard delete |
| GET | `/v1/memories/{id}/sources` | provenance: source messages + the judge run |
| POST | `/v1/sessions/{id}/close` | close a session, force extraction from the tail |
| POST | `/v1/admin/search-preview` | explain ranking without recording retrieval |
| GET | `/v1/admin/stats` | overview, backlog, spend, and index drift |
| GET | `/v1/admin/judge-runs` | paginated extraction audit |
| GET | `/v1/admin/sessions` | sessions and immutable messages |
| GET | `/v1/admin/costs` | spend by kind, month-to-date against the ceiling |
| POST | `/v1/admin/reindex` | rebuild Qdrant from SQLite |
| POST | `/v1/admin/reindex/start` | asynchronous rebuild with progress polling |

Commands: `serve`, `bench`, `import-claude-code`, `backfill`, `judge-runs`,
`reindex`, `eval`. `judge-runs` prints recent extractions with each operation and
the model's stated reason — `06-roadmap.md` is right that reading these by eye
daily for the first week is the highest-value work in the project.

## Measured on this machine

An M1 Pro / 16 GB, against 394 real Claude Code transcripts.

| | |
|---|---|
| embedding latency | **35.8 ms** median, MPS, 1024-dim |
| corpus | 58,666 lines -> 4,411 turns kept (406 user, 4,005 assistant) |
| indexable user turns | 304, across 87 sessions and 15 projects |
| search latency | ~145 ms end-to-end over HTTP |
| full reindex | 132 s for 304 raw turns |

### Eval: raw turns against extracted facts

The whole history is now processed -- 247 judge calls, $0.50, one error -- so the
comparison the project rests on can finally be made. Both numbers come from
`eval/queries.yaml`; the 31 cases below are the ones answerable by either target
(the other 16 ask about one-off tickets, which memory is right not to store --
see the header of that file).

| on the 31 shared cases | raw turns | extracted facts |
|---|---|---|
| recall@10 | 0.90 | 0.87 |
| MRR | 0.806 | **0.737** |
| top-1 | 23/31 | 21/31 |
| reject violations | 0 | 0 |
| mean tokens | 1771 | **392** |

```bash
uv run memkit eval --target raw
uv run memkit eval --target memories
```

**Read this honestly: facts do not beat raw turns on rank.** What they do is
deliver 91% of the MRR on 22% of the tokens -- 4.5x denser, which is 3.8x more
MRR per token. `docs/05-retrieval.md` puts the useful memory block at 600-1000
tokens; raw turns cannot fit in that budget at all (1771) and facts sit
comfortably inside it (392). That density, not the rank, is what the extractor
buys.

Two caveats against over-reading the gap. The assertions are regexes over the
user's own phrasing, which structurally favours a transcript search. And three of
the four remaining misses are one fixable defect, not weak extraction: the fact
exists but is scoped to a project, so a general question about the person never
reaches it (see *Scope drift* below).

`recall@10` on raw is no longer pegged at 1.00 only because the query set grew;
it remains a weak discriminator at k=10 over 306 documents, which is why MRR and
top-1 are reported beside it.

### Scope drift: diagnosed, fixed in v6, existing facts still to migrate

Of 62 facts extracted by v4, **41 are `scope=project` and only 21 are
`scope=user`, so just 34% of the store is reachable without naming a project.**
By hand-reading the 41, roughly 17 are phrased as facts about the person --
"prefers modal dialogs with tabs", "expects thorough, objective code reviews",
"prefers omitting page title and subtitle" -- and would still be true in another
repository, which is `prompts.V5` rule 5's own test for `scope=user`.

This is the priming failure `docs/08-extractor-experiments.md` diagnosed in v3
and believed v4 had fixed. On a 20-window bench it looked fixed. On the full
corpus it is not: v4's explicit warning that naming the project "does NOT tell
you the scope" reduces the drift without eliminating it.

Proof that it is scope and not extraction: three eval cases miss with no project
supplied and hit at rank 1 when one is. They are deliberately left failing so the
defect stays measurable.

**Root cause, and the fix.** The drift is in the *wording*, not in the `scope`
field. v4 rule 2 said "never write 'this project' — name the project", so the model
wrote "For frontend-second, prefers modal editors" — and every decision downstream
then correctly followed that phrasing. Asked whether the sentence holds in another
repository, the model says no, because the sentence it wrote names the repository.
Rule 2 was fighting rule 5.

v6 makes rule 2 conditional: name the repository only when the fact is about that
repository; for a fact about the person, do not mention it at all. Pooled over two
paired runs on 51 real windows, the reachable share went 26% → 54% with recall
inside the noise band. Two earlier hypotheses were measured and rejected first —
one of them cost 5x recall. `docs/08` records all three.

The 88 facts already in the store were extracted under v4 and still carry the old
scopes. `eval/scope_review.py` lists the project-scoped ones with a hint per fact
and emits a ready payload for `POST /v1/admin/memories/bulk`; the call is left to a
human, since the judge already got these wrong once.

Also measured, and less serious than it looks: 20% of user input is Russian but
only 6% of facts are, so prompt rule 9 ("same language the user used") is largely
ignored. Retrieval is unaffected -- a Russian query reaches the matching English
fact at rank 1, which is what BGE-M3 was chosen for -- so this is a display
concern, not a recall one.

### Stage 5: the Hermes provider

```bash
uv run memkit install-hermes        # copies into $HERMES_HOME/plugins/memkit
```

Source lives in [integrations/hermes/memkit](integrations/hermes/memkit) so it is
versioned and tested with the service. Loads through Hermes's own discovery,
`is_available()` true, both tools exposed. Measured against the running service:
prefetch **75–93 ms** steady state, ~840 ms on the first call — so the timeout is
0.4 s and the cold call is absorbed by a background warm-up in `initialize`, not by
a longer budget. `docs/07` had budgeted 0.15 s from in-process latency, which HTTP
does not deliver.

`docs/07-hermes-adapter.md` was unimplementable as written — four abstract methods
against the two it described, the wrong plugin directory, `input_schema` instead of
`parameters`. It is now rewritten against the real ABC, with a table of every place
the doc was wrong.

Two checklist items earned their keep by failing. The secret-redaction test leaked a
key pasted mid-sentence, because the pattern was anchored to line start and the unit
test that "covered" it had obligingly put the key on its own line. And the live
prefetch returned nothing at first, which is what surfaced the 0.15 s budget.

**The goal itself is verified.** `docs/06-roadmap.md` defines stage 5 as done when a
fact said in one place surfaces in another — "ради этого всё и строилось". Checked
through Hermes's own `MemoryManager`, in a sandbox `HERMES_HOME` so the live config
was untouched: one session says *"я всегда ставлю ширину бокового редактора в 880
пикселей"*, the real judge extracts it, and a **different** session's
`prefetch_all` returns it first:

```
- Prefers a side drawer editor width of 880px as a personal standard across projects
```

That line is also v6 working — `scope=user`, no repository in the wording. Under v4
it would most likely have been filed under the project and been unreachable from a
general question.

### Stage 4: what the first real consolidation did

```bash
uv run memkit consolidate --dry-run   # prints clusters, costs nothing
uv run memkit consolidate
```

One cluster on 88 facts: two garbled variants of the owner's name, cosine 0.9278.
Merged for $0.00025 — 88 → 87 active, 2 superseded with `superseded_by` set, Qdrant
drift 0, and the merged fact inherited all 20 source messages so
`/v1/memories/{id}/sources` still answers. A second run finds nothing, which is the
idempotency check. `MRR` went **0.737 → 0.759**: the duplicate had been consuming a
result slot.

Nothing was expired or demoted, correctly — no fact carries a `valid_until`, and
every fact is younger than the 90-day staleness window.

One honest note on the merge itself. Rule 2 of the merge prompt says preserve
specifics, so the survivor reads "User's name is Maga (also known as MagaLoviev or
Maga Luev)" — it faithfully kept both variants, and both were wrong to begin with
(the real surname is Lutfullaev). The consolidator did its job; the extractor
mangling proper nouns is a separate defect, and merging cannot fix bad input.

### v4 on the full corpus, against its bench numbers

`docs/08` measured v4 at 0.70 facts per window on 20 hand-picked windows. Over
188 real calls it yields **0.33** -- the bench sample was not representative.
What did carry over is the part that mattered: 21 facts about the person in
absolute terms against v2's 3, importance spread across 0.4-0.9 instead of
collapsing onto 0.6/0.7, and a median fact length of 128 characters. Three facts
of 62 exceed the prompt's 200-character cap (longest 223).

## Deviations from the docs

Defects found while building, fixed here, with the doc amended in the same
commit. The remainder are listed in the plan and land with their stage.

1. **`reindex` loads `status='active'` only.** A soft delete keeps the SQLite
   row, so reloading everything would resurrect every fact ever deleted.
   Verified: an expired fact does not come back.
2. **Eval assertions are content-based, not id-based.** `docs/05-retrieval.md`
   pins memory ids, but `reextract` mints new ids by design, so an id-pinned
   eval invalidates itself the first time the thing it measures runs.
3. **`external_source` / `external_id` are in the base schema**, not a later
   migration as `docs/07-hermes-adapter.md` proposes -- the importer needs them
   on day one. Identity comes from the transcript line `uuid`, not a content
   hash, so a legitimately repeated "ok" is not silently swallowed.
4. **Raw turns live in their own `raw` collection.** Putting them in `memories`
   as `docs/06-roadmap.md` suggests would break the one-point-per-fact invariant
   the data model depends on.
5. **`memories.judge_run_id` exists**, so `GET /v1/memories/{id}/sources` can
   return the judge run it advertises. Nothing linked those tables before.
6. **`scope_key` is accepted by `/v1/search` from stage 1.** The scope rule in
   `docs/05-retrieval.md` is unimplementable without it.
7. **The `bm25` sparse slot is declared at creation.** Qdrant cannot add a named
   vector to an existing collection, so leaving it out costs a full reindex
   later.
8. **The extractor tool sets `strict: true` and `additionalProperties: false`.**
   `04-judge.md` claims tool use means the model "physically cannot return
   malformed JSON" — that holds only in strict mode. Cross-field rules strict
   cannot express (`text` required for ADD, `id` for UPDATE/DELETE) are enforced
   in `Op.parse`, and a hallucinated candidate id is dropped rather than becoming
   a new fact.
9. **The judge is `claude-sonnet-5`, not `claude-haiku-4-5`.** The doc's Haiku
   pricing was correct ($1/$5, and Batch really is half price), but on this
   corpus a full backfill costs $0.86 on Haiku against $1.81 on Sonnet 5 — so the
   choice is a quality decision, exactly as `04-judge.md:149` argues. Note the
   models take different request shapes: Sonnet 5 rejects `temperature`,
   `top_p`, `top_k` and `budget_tokens` with a 400 and uses
   `output_config.effort`; Haiku 4.5 is the reverse and rejects `effort`.
10. **Prompt caching is impossible for the extractor at any TTL.** The stable
    prefix is ~350 tokens; the minimum cacheable prefix is 1024 on Sonnet 5
    (4096 on Haiku 4.5). The doc's conclusion was right, its reasoning
    incomplete.
11. **The dedup threshold is a setting, and 0.90 is probably too strict.**
    Measured on BGE-M3: an exact restatement scores 1.0000, but a genuine
    paraphrase of the same fact ("prefers pnpm over npm for all projects" vs
    "prefers pnpm rather than npm everywhere") only **0.8979** — missing the
    threshold by 0.002 — while two genuinely distinct preferences ("pnpm" vs
    "pytest") score 0.7422. So 0.90 catches near-verbatim duplicates only.
    Left at the documented value and exposed as `MEMKIT_DEDUP_COSINE`, because
    `05-retrieval.md` is right that this moves on eval evidence, not on feel.
    The same measurement means the consolidator's 0.92 clustering threshold will
    cluster almost nothing — a problem waiting in stage 4.
12. **The embedder loads at startup, not lazily.** Costs ~11s of boot and saves a
    ~15s first request. `07-hermes-adapter.md` gives `prefetch` a 150ms timeout,
    so lazy loading means the first turn after every restart has no memory.

## Stage 3: how the ranking behaves

Measured on real Qdrant with real embeddings, querying "which package manager do
I use" with `project=memkit`:

| score | similarity | recency | boost | age | type | fact |
|---|---|---|---|---|---|---|
| 0.612 | 0.509 | 0.946 | 0.5 | 10d | project | Uses pnpm workspaces in the memkit repo |
| 0.584 | 0.552 | 0.801 | 0.0 | 120d | preference | Prefers pnpm over npm for all projects |
| 0.498 | 0.360 | 0.801 | 0.0 | 60d | skill | Writes frontend code in Vue 3 with TypeScript |
| 0.385 | 0.481 | **0.000** | 0.0 | 30d | task | Today: fix the pnpm lockfile conflict |

Two things the formula buys that cosine alone cannot. The project fact ranks
first on a **lower** similarity than the fact below it, because it belongs to the
project in hand. And the stale task — which had the second-highest cosine of the
whole set — sinks to last, because 30 days against `task`'s 2-day τ leaves it no
recency at all. A fact from a different project (`notiky`) does not appear at any
rank; it is excluded in the Qdrant filter, not merely down-weighted.

## Transcript classification

The importer's real work. A line whose `type` is `user` usually is not the user:
of 58,666 lines, 22,934 were subagent traffic, 7,891 tool results, 76 interrupt
markers, 57 slash commands and 51 command output. Three copies of one plan
document, at 78k/86k/129k characters, accounted for 63% of all user text on
their own until a 20,000-character ceiling excluded them -- measured against 386
labelled human turns whose maximum is 17,989.

`promptSource` cannot be trusted on its own either. Its `sdk` value is not
programmatic traffic but Claude Desktop input (entrypoint `claude-desktop`,
userType `external`), 419 genuinely human turns; while 211 unlabelled lines are
about 87% machine noise with roughly 20 real turns mixed in. Both a source check
and a content check are needed, which is why
[`src/memkit/importers/claude_code.py`](src/memkit/importers/claude_code.py)
reports a per-bucket breakdown instead of a single total.

Assistant turns are stored but never indexed: stage-2 extraction windows need
them to resolve pronouns, but indexing the model's own words would pollute a
search over the user's history.

## Tests

Stdlib only, no pytest needed:

```bash
python3 -m unittest discover -s tests -t .
```

Every rejection case in the suite was observed in the real corpus.
