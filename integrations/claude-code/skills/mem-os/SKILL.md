---
name: mem-os
description: >-
  Long-term team memory via the Mem OS service. Use when the user says "remember
  this / запомни", asks "what do you know about me", "what did we decide about
  X", "who is <name>", wants past context, preferences or decisions recalled,
  wants a remembered fact corrected or forgotten, or wants their profile loaded.
  Provides save, search, read, correct, forget, identity lookup, and profile
  rendering over an HTTP API.
---

# Mem OS — save, find, correct, forget, look up

Your API key **is your identity**. Every request is made as you, and what you can
read or write follows from your memberships — there is no shared instance key.
Each operation below is one `curl`. Degrade silently: if the service is down, say
memory is unavailable and carry on with the actual task. Never retry in a loop.

## Configuration

```bash
ENV_BASE="$MEMKIT_BASE_URL"; ENV_KEY="$MEMKIT_API_KEY"
for f in ~/.config/memkit/client.env ~/.memkit; do [ -f "$f" ] && . "$f" && break; done
BASE="${ENV_BASE:-${MEMKIT_BASE_URL:-http://127.0.0.1:8077}}"
KEY="${ENV_KEY:-$MEMKIT_API_KEY}"
curl -sf --max-time 2 "$BASE/healthz" >/dev/null || echo "Mem OS is not running"
```

Precedence: the environment, then `~/.config/memkit/client.env`, then the
deprecated `~/.memkit`. With no key, tell the user to run
`memkit api-keys create --user <handle>` and put the key in
`~/.config/memkit/client.env` as `MEMKIT_API_KEY=…`. Never invent one.

## Scope and subject — the two things to get right

- **scope** decides *who can read a fact*. Omit it and the fact is private to the
  user. Give `"scope": "<slug>"` and everyone in that entity can read it.
- **subject** decides *who a fact is about*. It grants nothing. Use it for a fact
  about a person or product: `"subject": "sasha"`.

A write into a shared scope, and any write you decided on yourself, **starts
unconfirmed** and appears in that team's review queue (`GET "$BASE/v1/review"`)
until a human confirms it. It is retrievable in the meantime. Say so when you
write something shared.

`source_role` is a claim about who is asserting the fact, and retrieval trusts it:

- **`manual`** — the user told you to remember this. Trusted by default. Prefer
  their own words, under 200 characters, self-contained, no credentials.
- **`agent`** — you decided on your own it was worth keeping. Excluded from
  normal retrieval by design; it only surfaces with `"include_untrusted": true`.

Do not use `user`: that means message-backed evidence, and a key-holder
assertion has no message behind it.

## 1. Save

Private to the user:

```bash
curl -sf -X POST "$BASE/v1/memories" -H "X-API-Key: $KEY" -H 'Content-Type: application/json' -d '{"text": "Prefers pnpm over npm in every project", "kind": "preference", "source_role": "manual", "importance": 0.7}'
```

Into a shared scope, or about someone — same call, one more field:

```bash
curl -sf -X POST "$BASE/v1/memories" -H "X-API-Key: $KEY" -H 'Content-Type: application/json' -d '{"text": "Releases go out on Thursday, never Friday", "kind": "fact", "scope": "mem-os", "source_role": "manual", "importance": 0.8}'
```

```bash
curl -sf -X POST "$BASE/v1/memories" -H "X-API-Key: $KEY" -H 'Content-Type: application/json' -d '{"text": "Owns the retrieval pipeline", "kind": "fact", "scope": "mem-os", "subject": "sasha", "source_role": "manual", "importance": 0.7}'
```

`kind` is free-form; `preference` and `fact` cover almost everything. A 403 means
you named a scope the user is not in — save it privately instead and say why.

For "remember this whole conversation", do **not** hand-write memories: the hooks
already post the transcript as evidence and the service extracts, cites and
redacts server-side. Only if the hooks are not installed, post the turns to
`POST "$BASE/v1/evidence/events:batch"` (up to 100 events, each with
`session_id`, `role`, `content`, `external_source`, `external_id`, and `scope`
for a shared project) and then `POST "$BASE/v1/sessions/<id>/close"`.

## 2. Find

```bash
curl -sf -X POST "$BASE/v1/memories/search" -H "X-API-Key: $KEY" -H 'Content-Type: application/json' -d '{"query": "what package manager do we use", "limit": 10, "include_sources": true}'
```

Each result carries `id`, `text`, `kind`, `score`, `revision`, `scope`, `subject`
and `review_status`, plus hash-verified `sources[]` quotes when you ask for them.
**An empty result means "no memory", not an error** — the service abstains on
weak matches on purpose. Add `"scopes": ["mem-os"]` to search one project, or
`"subject": "sasha"` for facts about a person.

## 3. Read one

```bash
curl -sf -X GET "$BASE/v1/memories/<id>" -H "X-API-Key: $KEY"
```

Gives the full row including `revision` — which is what a correction needs.

## 4. Correct

Read the memory, then PATCH it with the `revision` you just read as
`expected_revision`. A stale precondition returns 409 instead of overwriting
somebody else's edit.

```bash
curl -sf -X PATCH "$BASE/v1/memories/<id>" -H "X-API-Key: $KEY" -H 'Content-Type: application/json' -d '{"expected_revision": 3, "text": "Prefers pnpm over npm on every project"}'
```

Moving a fact between scopes changes who can read it, so it has to be said out
loud: `{"expected_revision": 3, "scope": "mem-os", "move_scope": true}`.

## 5. Forget

Reversible archive, not a delete. Never bulk-delete.

```bash
curl -sf -X DELETE "$BASE/v1/memories/<id>" -H "X-API-Key: $KEY"
```

## 6. Who or what is this?

Resolve the name first — exact alias match, so `{"entity": null}` means the name
is genuinely unknown and you should say so rather than guess:

```bash
curl -sf -X POST "$BASE/v1/entities/resolve" -H "X-API-Key: $KEY" -H 'Content-Type: application/json' -d '{"name": "Sasha"}'
```

Then read that entity's page by its `slug`. `about[]` is what the team recorded
about it; `in_scope[]` is what lives in its scope (present only where the user is
a member):

```bash
curl -sf -X GET "$BASE/v1/entities/<slug>/profile" -H "X-API-Key: $KEY"
```

## 7. Render the profile

```bash
curl -sf -X POST "$BASE/v1/profiles/render" -H "X-API-Key: $KEY" -H 'Content-Type: application/json' -d '{"blocks": ["about", "style", "team", "project", "recent"], "workspace": "mem-os", "budget_tokens": 600}'
```

Returns `blocks` keyed by those five names: who the user is, how they like to
work, the team's shared rules, what is true about this workspace, and what
changed lately. The session-start hook already injects this — render it by hand
only when the user asks, or when the block is not in context.
