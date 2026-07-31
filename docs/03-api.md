# HTTP and CLI contract

Agents reach memkit only through this surface. Authentication is a single static
key in the `X-API-Key` header on every route except `/healthz`.

## The routes

Generated from the running application's own schema, so it cannot omit a route or
misreport a status code — both of which the hand-maintained version did:

<!-- generated:http-routes -->
| endpoint | success | auth |
|---|---|---|
| `GET /healthz` | 200 | — |
| `GET /v1/admin/activity` | 200 | `X-API-Key` |
| `POST /v1/admin/consolidate` | 200 | `X-API-Key` |
| `GET /v1/admin/costs` | 200 | `X-API-Key` |
| `GET /v1/admin/costs/daily` | 200 | `X-API-Key` |
| `GET /v1/admin/facets` | 200 | `X-API-Key` |
| `GET /v1/admin/judge-runs` | 200 | `X-API-Key` |
| `GET /v1/admin/judge-runs/{run_id}` | 200 | `X-API-Key` |
| `POST /v1/admin/memories/bulk` | 200 | `X-API-Key` |
| `GET /v1/admin/messages/{message_id}` | 200 | `X-API-Key` |
| `POST /v1/admin/reextract` | 200 | `X-API-Key` |
| `POST /v1/admin/reindex` | 200 | `X-API-Key` |
| `POST /v1/admin/reindex/start` | 202 | `X-API-Key` |
| `GET /v1/admin/reindex/status` | 200 | `X-API-Key` |
| `POST /v1/admin/search-preview` | 200 | `X-API-Key` |
| `GET /v1/admin/sessions` | 200 | `X-API-Key` |
| `GET /v1/admin/sessions/{session_id}/messages` | 200 | `X-API-Key` |
| `GET /v1/admin/stats` | 200 | `X-API-Key` |
| `POST /v1/admin/tasks` | 201 | `X-API-Key` |
| `GET /v1/admin/tasks/board` | 200 | `X-API-Key` |
| `PATCH /v1/admin/tasks/{memory_id}` | 200 | `X-API-Key` |
| `GET /v1/memories` | 200 | `X-API-Key` |
| `POST /v1/memories` | 201 | `X-API-Key` |
| `DELETE /v1/memories/{memory_id}` | 200 | `X-API-Key` |
| `PATCH /v1/memories/{memory_id}` | 200 | `X-API-Key` |
| `GET /v1/memories/{memory_id}/sources` | 200 | `X-API-Key` |
| `POST /v1/memories/{memory_id}/supersede` | 200 | `X-API-Key` |
| `POST /v1/messages` | 201 | `X-API-Key` |
| `POST /v1/search` | 200 | `X-API-Key` |
| `POST /v1/sessions/{session_id}/close` | 200 | `X-API-Key` |

30 routes, 29 behind the API key. 1 unauthenticated.
<!-- /generated:http-routes -->

The rest of this document covers semantics: what each of the interesting ones
promises, and what it refuses.

## Core

### `POST /v1/messages`

Writes one message and returns **201**. The write is synchronous; extraction is not,
and `extraction_queued` reports whether the gate opened. It is `false` whenever no
judge credential is configured, which is a supported mode — manual memories and
retrieval keep working without any cloud access at all.

**Idempotency.** With `external_source` and `external_id`, a repeated delivery
returns the same `message_id` and `deduplicated: true`. This is not optional
politeness: the Hermes adapter can deliver the same turn through `sync_turn` and
again through `on_session_end`, and without it the corpus double-counts and the
judge pays twice to read the same window.

`role` accepts `user` and `assistant` only. Assistant turns are stored and never
indexed.

### `POST /v1/sessions/{id}/close`

Closes the session and drains the tail: a long session can hold several unprocessed
windows, so this loops until nothing is left to read. Returns the accumulated
counts, including `rejected` — operations the provenance guard refused
([02-data-model.md](02-data-model.md)).

404 for an unknown session. With no judge configured it still closes the session and
returns `extracted: 0` with an explanatory `error`, rather than failing: closing is
useful even when extracting is impossible.

There is no `POST /v1/sessions`. A session is created by its first message.

### `POST /v1/search`

The read path. `scope_key` is **required in practice**, not optional: without it
every project-scoped fact is filtered out, so a request that omits it silently sees
only user-scoped memory. `task_key` is separate because a request is usually inside a
project *and* a task at once.

`budget_tokens` defaults to 800 and `limit` to 30. `include_raw` additionally
searches the raw-turn collection, which is what the eval uses to compare extracted
facts against the messages they came from.

`agent_id` is accepted and currently unused. It is in the request because
per-agent filtering is an obvious future need and removing a field later is worse
than ignoring one now — but nothing filters on it today, and a caller expecting it to
scope results will be disappointed.

### `GET /v1/memories/{id}/sources`

Where a fact came from: the messages, the judge run that agreed, the operations that
run emitted, the supersession chain in both directions, and the provenance label with
a per-role tally of the evidence.

This endpoint looks optional and is not. The first time the service remembers
something absurd about you, the only useful question is which messages produced it —
and "was any of this actually me?" is answered by `source_roles`.

### `POST /v1/memories`

A direct write, bypassing the judge. `source_role` declares who is asserting the
fact; a caller writing on a model's behalf must say so, and the Hermes plugin sends
`"assistant"` from both of its write paths. The reasoning is
[decisions/0006](decisions/0006-source-role-and-may-write.md).

## Mutation

`PATCH` and `DELETE` on a memory, plus `/supersede` and the bulk endpoint.

**Optimistic concurrency.** `PATCH /v1/memories/{id}` accepts
`expected_updated_at`; a mismatch is **409**. Two dashboard tabs editing the same
fact must not silently overwrite each other. The task board has its own independent
lock, `expected_board_version`, because the two tables move independently — a card
can be dragged without the memory changing at all.

**Deletion is soft.** The row survives with `status='expired'` and the Qdrant point
is removed. `?hard=true` deletes the row, unlinks its sources and clears its board
metadata. For a task, soft deletion is archiving; workflow `done` remains a separate
state, because finishing something and forgetting it are different.

**Bulk** supports `expire`, `restore`, `hard_delete`, `set_type`, `set_importance`
and `set_scope` over up to 500 ids. `hard_delete` additionally requires `confirm` and
caps at 100 — the one irreversible operation gets the one extra hurdle.

**While a reindex runs, every mutation answers 409.** Synchronous and asynchronous
reindex share one slot.

## Replay and consolidation

### `POST /v1/admin/reextract`

Replays history under a different prompt version. `dry_run` defaults to **true** and
makes no model call — asserted by a test that patches the judge to raise, rather than
promised in a comment.

Three invariants, each of which was a bug waiting to happen:

- The facts about to be superseded are **excluded from the candidate block**.
  Otherwise the judge sees them, emits UPDATE, and overwrites the old set in place —
  losing exactly the comparison the replay was run for.
- The old set is retired **after** the new one is written. A mid-run failure leaves
  both alive, which is recoverable; the reverse order loses facts.
- Under `max_calls`, only facts whose sources were **all** re-read are retired. A
  fact spanning a re-read window and an untouched one survives.

The response carries `superseded_ids`, so rollback is one bulk call with
`op="restore"`.

`use_batch` is accepted by the schema and answered with **422**. Batch is not
implemented, and silently ignoring the flag would report a discount that was never
applied ([decisions/0012](decisions/0012-no-batch-api.md)).

An unknown `prompt_version` is 422, checked before any call.

### `POST /v1/admin/consolidate`

Stage 4 on demand. `dry_run` defaults to true, again with no model call. `threshold`
overrides `MEMKIT_CONSOLIDATE_COSINE` per request so it can be swept against the
eval without a restart.

Always dry-run first. A merge supersedes its inputs — nothing is deleted, but the
active set it leaves behind is what every later search sees.

## Operations

The remaining `/v1/admin/*` routes are the dashboard's read surface: statistics,
facets, daily activity, cost by kind, judge runs and their detail, sessions and their
messages, and the ranking explainer described in
[05-retrieval.md](05-retrieval.md).

Two worth naming:

`GET /v1/admin/stats` reports `index_drift` (`qdrant_memories - sqlite_active`) and
`by_source_role`. The first tells you the derived index is lying; the second is the
long-run health metric from [08-testing.md](08-testing.md) — watch `assistant`.

`POST /v1/admin/reindex/start` returns **202** and runs in a thread;
`GET /v1/admin/reindex/status` polls it. The synchronous `POST /v1/admin/reindex`
blocks instead. They share one slot, so the second caller gets 409.

## Errors

| status | means |
|---|---|
| 401 | missing or wrong `X-API-Key` |
| 404 | unknown id |
| 409 | lost an optimistic lock, or a mutation during reindex, or a job already running |
| 422 | request the schema accepts but the service refuses — `use_batch`, an unknown prompt version, an unknown sort column, reversed ordering anchors |

422 rather than 400 for the refusals is deliberate: the body was syntactically
valid and semantically rejected, and the distinction tells a caller whether to fix
their serialisation or their intent.

Sort and order parameters are validated against an allowlist before reaching SQL. A
value like `updated_at; DROP TABLE memories` is a 422, and a test asserts the table
is still there afterwards.

## CLI

| command | does |
|---|---|
| `memkit serve` | run the API |
| `memkit bench` | embedder latency gate; exits non-zero if the dimension is not 1024 |
| `memkit import-claude-code` | import transcripts; `--dry-run` reports classification and writes nothing |
| `memkit backfill` | extract from unprocessed history; `--dry-run` prices it first |
| `memkit eval` | retrieval eval; `--compare` for the only valid raw-vs-facts comparison |
| `memkit consolidate` | stage 4; `--dry-run` by default in practice |
| `memkit reindex` | rebuild both collections from SQLite |
| `memkit judge-runs` | print recent judge calls with their operations |
| `memkit install-hermes` | copy the plugin into `$HERMES_HOME/plugins/` |

Every command that spends money prints the estimate first and refuses without the
right credential. `bench` exits non-zero on a wrong dimension because a silent
embedding-model swap would make every stored vector incomparable, and nothing else
would notice.
