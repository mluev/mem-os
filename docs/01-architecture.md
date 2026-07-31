# Architecture

One HTTP service. Agents never touch SQLite or Qdrant directly — only the API. A
single instance serves the chat assistant, the coding agent, the research agent and
anything else, because a memory that only one agent can read is a worse version of
that agent's own scratchpad.

## Components

| what | where | why there |
|---|---|---|
| SQLite | local file | source of truth; one file to back up |
| Qdrant | local Docker, loopback only | vector index, rebuildable from SQLite |
| BGE-M3 embeddings | local, Apple Silicon MPS | called on every message and every search, so it cannot be a network hop |
| judge (extractor) | cloud API | called rarely; needs language understanding and strict JSON |

The judge is the only component that leaves the machine, and it is the only one
that costs money. Everything on the read path is local, which is what makes reading
free and fast enough to do on every turn.

Hardware constraint: a 16 GB MacBook Pro. No local LLM — the memory a useful one
would need is memory the embedder and Qdrant are already using.

## The write path

1. An agent posts a message to `POST /v1/messages`. It is written to SQLite
   synchronously and the endpoint returns.
2. User turns at or above 25 characters are embedded and indexed into the `raw`
   collection. Assistant turns are stored and never indexed: they are context for
   resolving pronouns, not claims about the user.
3. A gate decides whether to call the judge: the session closed, ten unprocessed
   messages have accumulated, or the text contains an explicit request to remember.
4. If the gate opens, extraction runs as a **background task** — not through a
   queue ([decisions/0018](decisions/0018-background-tasks-not-a-queue.md)). The
   agent never waits on the judge.
5. Extraction takes a window of ten messages, retrieves up to eight existing
   candidate facts, and asks the judge for operations.
6. Operations are validated in code, checked against the provenance guard, and
   applied to SQLite and Qdrant. Messages are marked processed only after the
   window has been applied, so an interrupted extraction retries.

The gate is the main cost lever and it is also what makes extraction *good*: a
ten-message window resolves pronouns that a single line cannot.

Windows containing no user turn are skipped without calling the judge. On this
corpus assistant turns outnumber user turns roughly ten to one, so this is not an
edge case — measured before the fix, 44% of windows were assistant-only.

## The read path

`POST /v1/search`, entirely local and with no model call:

1. Embed the query.
2. Query Qdrant with a filter that requires the owner and `status='active'`, and
   admits a fact only if its scope matches the request — user-scoped always,
   project-scoped when the key matches, task-scoped when unkeyed or matching.
   Foreign-project facts are excluded **at Qdrant**, not down-weighted.
3. Rescore in process: similarity, importance, recency by type, scope boost.
4. Drop near-duplicates.
5. Fill the token budget in descending score order.

Details and the scoring constants are in [05-retrieval.md](05-retrieval.md).

## Startup

`lifespan` runs migrations, builds a connection pool with one connection per
thread, connects to Qdrant, ensures both collections exist, and **loads the
embedding model before accepting traffic**. That costs 11–17 seconds and is
deliberate: lazy loading moves the cost onto the first request, which is the one
that can least afford it ([decisions/0025](decisions/0025-eager-embedder-load.md)).

One connection per thread rather than one shared: FastAPI runs synchronous
endpoints in a threadpool with background extraction alongside them, and
`transaction()` commits the connection rather than the block — so a shared
connection lets one request commit another's half-written work.

## What this is not for

| goes in memory | does not |
|---|---|
| what is worth remembering about the user and their world | what can be looked up |
| preferences, decisions, identity, constraints, working style | documentation, code, API references |
| things that will still matter in three months | what happened in this session |

The boundary matters because the failure mode is not "memory is empty" but "memory
is full of noise and every answer is worse for it". A retrieval-augmented search
over documentation is a different system with different scoring; if one is wanted,
it gets its own collection so that documentation cannot leak into memory results.

## Configuration

Every setting, its environment variable and its default:

<!-- generated:config-defaults -->
| setting | environment variable | default |
|---|---|---|
| `api_key` | `MEMKIT_API_KEY` | `change-me` |
| `anthropic_api_key` | `ANTHROPIC_API_KEY` | `""` (empty) |
| `gemini_api_key` | `GEMINI_API_KEY / GOOGLE_API_KEY / GOOGLE_VERTEX_API_KEY` | `""` (empty) |
| `vertex_project` | `VERTEX_PROJECT / GOOGLE_CLOUD_PROJECT` | `""` (empty) |
| `vertex_location` | `VERTEX_LOCATION` | `""` (empty) |
| `owner_id` | `MEMKIT_OWNER_ID` | `u-1` |
| `owner_name` | `MEMKIT_OWNER_NAME` | `owner` |
| `db_path` | `MEMKIT_DB_PATH` | `data/memkit.db` |
| `qdrant_url` | `MEMKIT_QDRANT_URL` | `http://127.0.0.1:6333` |
| `embed_model` | `MEMKIT_EMBED_MODEL` | `BAAI/bge-m3` |
| `embed_device` | `MEMKIT_EMBED_DEVICE` | `mps` |
| `host` | `MEMKIT_HOST` | `127.0.0.1` |
| `port` | `MEMKIT_PORT` | `8077` |
| `ui_dir` | `MEMKIT_UI_DIR` | `src/memkit/web_dist` |
| `cors_origins` | `MEMKIT_CORS_ORIGINS` | `[]` |
| `expose_docs` | `MEMKIT_EXPOSE_DOCS` | `True` |
| `monthly_cost_limit_usd` | `MEMKIT_MONTHLY_COST_LIMIT_USD` | `15.0` |
| `judge_model` | `MEMKIT_JUDGE_MODEL` | `gemini-3.5-flash-lite` |
| `dedup_cosine` | `MEMKIT_DEDUP_COSINE` | `0.9` |
| `consolidate_cosine` | `MEMKIT_CONSOLIDATE_COSINE` | `0.92` |
| `consolidate_stale_days` | `MEMKIT_CONSOLIDATE_STALE_DAYS` | `90` |
| `consolidate_demotion` | `MEMKIT_CONSOLIDATE_DEMOTION` | `0.1` |
<!-- /generated:config-defaults -->

`.env.example` documents all of these, and
`tests/test_docs_contract.py` fails if a setting exists in code without appearing
there — four consolidation and dedup knobs had gone undocumented, one of which the
retrieval document told readers to set.

Two settings deserve emphasis. `monthly_cost_limit_usd` is a hard ceiling enforced
in code, not a dashboard target: one runaway loop can spend a month's budget in an
hour, and by the time a human notices it is already spent. `api_key` defaults to
`change-me`, which is exactly as insecure as it looks; the service binds to
loopback only, but that is one setting away from not being true.
