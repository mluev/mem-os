---
name: mem-os
description: >-
  Long-term memory for this user via the local Mem OS service. Use when the
  user says "remember this / запомни", asks "what do you know about me", "what
  did I decide about X", wants past context, preferences, or decisions
  recalled, asks to save this conversation to memory, or wants their profile
  loaded. Provides save, search (find context), conversation capture, and
  profile rendering over a local HTTP API.
---

# Mem OS — save, find, capture, profile

Mem OS is the user's single-owner memory service (SQLite-authoritative, local).
Every operation below is one `curl` against it. Degrade silently: if the
service is down, say memory is unavailable and continue the actual task —
never block on it, never retry in a loop.

## Configuration

Resolve the endpoint and key once per session, in this order:

```bash
[ -f ~/.memkit ] && . ~/.memkit
BASE="${MEMKIT_BASE_URL:-http://127.0.0.1:8077}"
KEY="$MEMKIT_API_KEY"
```

`~/.memkit` is a plain `KEY=VALUE` file (`MEMKIT_API_KEY=...`, optionally
`MEMKIT_BASE_URL=...`). If no key is found, tell the user to create it —
never guess or invent one.

Health preamble before the first call of a session:

```bash
curl -sf --max-time 2 "$BASE/healthz" >/dev/null || echo "Mem OS is not running — start it with 'memkit serve'"
```

## 1. Save a memory

Provenance matters and is enforced server-side; be honest about who is
asserting the fact:

- The **user told you to remember something** → `"source_role": "manual"`
  (a key-holder assertion; trusted by retrieval). Prefer the user's verbatim
  words in `text`, under 200 characters, self-contained, no credentials.
- **You decided on your own** something is worth keeping →
  `"source_role": "agent"`. These are excluded from normal retrieval by
  design — they only surface with `include_untrusted: true`.

```bash
curl -sf -X POST "$BASE/v1/memories" -H "X-API-Key: $KEY" -H 'Content-Type: application/json' -d '{
  "text": "Prefers pnpm over npm in every project",
  "kind": "preference",
  "context": {},
  "source_role": "manual",
  "importance": 0.7
}'
```

`kind` is free-form (use `preference`, `fact`, or one concise noun). Leave
`context` empty for global facts about the user; set
`{"source_workspace": "<repo name>"}` only when the claim is true just for
this codebase.

## 2. Find context (search)

```bash
curl -sf -X POST "$BASE/v1/memories/search" -H "X-API-Key: $KEY" -H 'Content-Type: application/json' -d '{
  "query": "what package manager does the user prefer",
  "include_sources": true,
  "limit": 10
}'
```

Read `memories[]`: each has `text`, `kind`, `context`, `score`, and (with
`include_sources`) `sources[]` — hash-verified verbatim quotes from the
original conversation, useful when the user asks "when/where did I say that".
**An empty result means "no memory", not an error** — the service abstains on
weak matches by design; say you don't have that in memory. To scope to this
repo add `"filter": {"field": "context.source_workspace", "op": "eq",
"value": "<repo name>"}`.

## 3. Capture conversation as evidence

For "save this conversation / remember what we discussed": do NOT hand-write
many individual memories. Post the turns as evidence — the service extracts
durable memories with full citations server-side (and redacts secrets):

```bash
curl -sf -X POST "$BASE/v1/evidence/events:batch" -H "X-API-Key: $KEY" -H 'Content-Type: application/json' -d '{
  "events": [
    {"session_id": "<session id>", "agent_id": "claude-code", "role": "user",
     "content": "<what the user said>", "external_source": "claude-code",
     "external_id": "<stable unique id per turn>",
     "context": {"source_workspace": "<repo name>"}}
  ]
}'
```

Batch up to 100 events; `external_id` makes re-sends idempotent. Then force
extraction of the tail by closing the session:

```bash
curl -sf -X POST "$BASE/v1/sessions/<session id>/close" -H "X-API-Key: $KEY"
```

(If the memkit Claude Code hooks are installed, capture happens automatically
on session stop — only do this manually when the user explicitly asks.)

## 4. Load the user's profile

```bash
curl -sf -X POST "$BASE/v1/profiles/render" -H "X-API-Key: $KEY" -H 'Content-Type: application/json' -d '{"budget_tokens": 600}'
```

`stable[]` holds identity and preferences; `dynamic[]` recent context. Use it
at the start of work that benefits from knowing the user.

## Corrections

If the user says a remembered fact is wrong, find it (search results carry
`revision`, or read one fact with `GET "$BASE/v1/memories/<id>"`), then either
archive it, reversibly:

```bash
curl -sf -X DELETE "$BASE/v1/memories/<id>" -H "X-API-Key: $KEY"
```

or correct the text, passing the `revision` you just read as
`expected_revision`. A stale precondition returns 409 rather than overwriting
someone else's edit:

```bash
curl -sf -X PATCH "$BASE/v1/memories/<id>" -H "X-API-Key: $KEY" -H 'Content-Type: application/json' \
  -d '{"expected_revision": 1, "text": "Prefers pnpm over npm on every project"}'
```

Never bulk-delete.
