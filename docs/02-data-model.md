# Data model

SQLite is the source of truth. Qdrant is a derived index that must be
reconstructible from it with one command. That asymmetry is the first invariant in
[README.md](README.md), and it is what makes the embedding model and the extractor
prompt safe to change: if the index were authoritative for anything, changing
either would become irreversible.

## SQLite

The tables below are the ones `init_db` produces, read from a freshly migrated
database rather than transcribed by hand:

<!-- generated:sqlite-schema -->
`db.SCHEMA_VERSION = 3`, stored in `PRAGMA user_version`.

| table | columns |
|---|---|
| `judge_runs` | id, kind, model, prompt_version, input_json, output_json, error, input_tokens, output_tokens, cost_usd, latency_ms, created_at |
| `memories` | id, owner_id, agent_id, scope, scope_key, type, text, importance, confidence, status, superseded_by, valid_from, valid_until, created_at, updated_at, last_retrieved_at, retrieval_count, extraction_version, judge_run_id, source_role |
| `memory_sources` | memory_id, message_id |
| `messages` | id, session_id, role, content, created_at, processed, external_source, external_id |
| `owners` | id, name, created_at |
| `sessions` | id, owner_id, agent_id, started_at, ended_at, meta |
| `task_board` | memory_id, workflow_status, project_key, position, version, created_at, updated_at |

Indexes: `idx_judge_runs_created`, `idx_memories_owner`, `idx_memories_scope`, `idx_messages_external`, `idx_messages_session`, `idx_messages_unprocessed`, `idx_sessions_owner`, `idx_task_board_order`.
<!-- /generated:sqlite-schema -->

Per-column commentary lives in `src/memkit/db.py`, beside the DDL, rather than
being restated here. Reproducing DDL in prose is how a document ends up describing
a schema that no longer exists.

### Why each table earns its place

**`owners`** exists from day one with one row. `owner_id` is on every table and in
every Qdrant payload from the start, so adding a second user is an authentication
change rather than a data migration and a rewrite of every query.

**`sessions`** carries `meta` as JSON, holding `project` and `git_branch`. The
project is what scope filtering matches against, so it has to be recorded at
ingest — it cannot be recovered afterwards.

**`messages`** is append-only. Nothing deletes a raw message, ever, because the
extractor prompt will be rewritten many times and each rewrite has to be able to
replay the whole history. `external_source` and `external_id` carry a unique
partial index, so the same turn delivered twice leaves one row — see
[03-api.md](03-api.md).

**`judge_runs`** logs every model call: input, raw output, tokens, cost, latency
and error. It is what makes spend auditable, and what
[decisions/0007](decisions/0007-no-events-journal.md) relies on when declining a
separate audit journal. `kind` separates `extract` from `consolidate`, so per-kind
spend is a `GROUP BY`.

**`memories`** holds the facts. `updated_at` is what retrieval ages from, not
`created_at`: a fact the user confirms again today is fresh again. `status` moves
between `active`, `expired` and `superseded`; the normal path hard-deletes nothing.

**`task_board`** is separate from `memories` on purpose. Moving a card must not
touch `memories.updated_at`, because retrieval reads recency from that column and a
drag would otherwise make a stale task look freshly relevant. Ordering is a
fractional `position REAL`; concurrent edits are caught by `version`.

**`memory_sources`** links each fact to the messages behind it. Without it,
`GET /v1/memories/{id}/sources` cannot answer the only question worth asking the
first time the service remembers something absurd: which messages produced this.

### Provenance

`memories.source_role` records where a claim came from — the highest-authority role
among the messages the fact cites, or `manual` when it cites none and the caller
asserted it. It is `NOT NULL` and `CHECK`-constrained, with **no `DEFAULT`**: an
insert that omits it fails, because a default would let a forgotten column label
model-authored text as something a human typed, which is precisely the failure the
column exists to detect.

`provenance.may_write` refuses any ADD or UPDATE whose only evidence is assistant
text. UPDATE is guarded as well as ADD, because confirmation is the loop and not
just creation: left open, a model agrees with its own stored claim, the judge emits
UPDATE, `updated_at` moves forward, and retrieval treats the fact as freshly
confirmed.

The full reasoning — including a candid account of what the guard does **not**
protect today — is
[decisions/0006](decisions/0006-source-role-and-may-write.md). Read it before
relying on this.

`source_role` is deliberately **not** in the Qdrant payload: it has no read-path
use, and adding it would leave every existing point stale until a full reindex.

### Vocabularies

Each of these is declared in several modules. The table below is generated, and
`tests/test_docs_contract.py` additionally asserts that the copies agree with one
another — including that the `CHECK` constraints in the schema match the Python
tuples, which nothing verified before.

<!-- generated:vocabularies -->
| vocabulary | values | defined in |
|---|---|---|
| type | `preference`, `fact`, `skill`, `relation`, `project`, `decision`, `task` | `providers.MEMORY_TYPES` |
| scope | `user`, `project`, `task` | `providers.SCOPES` |
| status | `active`, `expired`, `superseded` | `mutate` (literals) |
| workflow_status | `unknown`, `todo`, `doing`, `done` | `taskboard.WORKFLOW_STATUSES` |
| operation | `ADD`, `UPDATE`, `DELETE` | `judge.Op.parse` |
| source_role | `user`, `assistant`, `tool`, `manual` | `provenance.ROLES` |
| judge_runs.kind | `extract`, `consolidate` | `judge`, `consolidate` |
<!-- /generated:vocabularies -->

`scope` and `scope_key` work together: `scope='project'` is meaningless without a
key naming the project, and `scope='user'` must never carry one — a user fact with a
project key is reachable from one repository only. Both write paths normalise this.

### Migrations

One mechanism: an idempotent `CREATE TABLE IF NOT EXISTS` script, then
version-gated backfills, then `PRAGMA user_version` is set. `init_db` refuses to
open a database whose version exceeds `SCHEMA_VERSION`, so rolling the code back
requires a backup rather than optimism.

Schema 3 added `source_role` by **rebuilding the `memories` table**, because SQLite
cannot add a `NOT NULL` column without a `DEFAULT` and cannot add a `CHECK` at all.
Three details in that rebuild are load-bearing and non-obvious, all documented at
the function:

- Foreign keys must be off for the `DROP`. `task_board` references `memories(id)`
  with `ON DELETE CASCADE`, so dropping the old table with them on deletes the
  entire kanban board.
- `PRAGMA foreign_keys` is a no-op inside a transaction, and `executescript`
  issues its own `COMMIT` — so the statements run individually inside an explicit
  `BEGIN`. The first version used `executescript`, and therefore had no transaction
  at all; the migration test is what caught it.
- `PRAGMA foreign_key_check` runs inside the transaction and rolls back on any
  dangling reference, which is what makes the rebuild safe rather than hopeful.

Before running a migration against real data, take a backup and gzip it. `init_db`
migrates whatever database it is pointed at, **including a `.bak` file**, which
destroys the rollback path; gzipping makes a backup un-openable by any tool that
might try.

## Qdrant

**Two collections, not one.** `memories` holds one point per active fact; `raw`
holds indexed user turns. Merging them would break the one-point-per-fact invariant
the read path depends on, and the scoring formula — importance, recency by type,
scope — is meaningless for a raw turn. See
[decisions/0019](decisions/0019-two-qdrant-collections.md).

Both are created with a named dense vector `"dense"` of 1024 dimensions, cosine
distance, and a declared-but-unused `bm25` sparse slot
([decisions/0050](decisions/0050-bm25-deferred.md)).

Payload keyword indexes:

- `memories`: `owner_id`, `agent_id`, `scope`, `scope_key`, `type`, `status`,
  `task_status`
- `raw`: `owner_id`, `agent_id`, `project`, `role`, `session_id`

The fact's `text` is duplicated into the payload deliberately. It costs a little
space and lets the read path build a complete result without a second round trip to
SQLite for every hit.

For `type='task'` the payload always carries `task_status`, and all four workflow
states including `done` stay searchable. Workflow status and lifecycle status are
independent: a finished task is still a fact about what happened.

### Rebuilding the index

`POST /v1/admin/reindex` drops both collections and reloads:

- `memories` — **only `status='active'`**. Reloading everything would resurrect
  every soft-deleted and superseded fact, turning the one operation guaranteed safe
  into the one that silently undoes every correction ever made
  ([decisions/0020](decisions/0020-reindex-loads-active-only.md)).
- `raw` — every user turn at or above the 25-character floor. The same floor the
  importer applies, or a rebuild would silently change the size of the collection.

`GET /v1/admin/stats` reports `index_drift` as `qdrant_memories - sqlite_active`.
Any non-zero value means the derived index disagrees with the source of truth.

While a rebuild runs, mutations answer **409**. They used not to, which meant a
fact written during the window between "drop the collections" and "finish
refilling" got no point and no error, because reindex had already read its source
rows.

## What is not recorded

There is no `events` table and no redaction endpoint. Audit is served by
`judge_runs`, `memory_sources`, the `superseded_by` chain, and
`last_retrieved_at` / `retrieval_count`. The argument, including what is genuinely
lost by declining it, is
[decisions/0007](decisions/0007-no-events-journal.md).
