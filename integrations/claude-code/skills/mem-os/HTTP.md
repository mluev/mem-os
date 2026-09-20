# HTTP fallback

Use this only when `memos` is unavailable. The same capability and provenance
rules in [SKILL.md](SKILL.md) apply. No CLI executable is needed.

Read the existing connection: environment first, then the first available
legacy config. Keep the key private; do not print it or invent one.

```bash
ENV_BASE="$MEMKIT_BASE_URL"
ENV_KEY="$MEMKIT_API_KEY"
for f in ~/.config/memkit/client.env ~/.memkit; do [ -f "$f" ] && . "$f" && break; done
BASE="${ENV_BASE:-${MEMKIT_BASE_URL:-http://127.0.0.1:8077}}"
KEY="${ENV_KEY:-$MEMKIT_API_KEY}"
```

If the key is missing, report that the connection is not configured. An operator
can create a personal key with `memkit api-keys create --user <handle>` and save
it as `MEMKIT_API_KEY` in `~/.config/memkit/client.env`.

The examples below illustrate payloads. Replace IDs, revisions and names with
returned values; `mem-os` and `sasha` are example slugs, not assumed identities.
Use a JSON file and `--data-binary @file` for user text, not shell interpolation.
Every request uses `X-API-Key`. A 403 remains a failed operation: do not reroute
its scope. A 409 means read again before reconciling a correction or review.

Discover your identity and available scopes:

```bash
curl -sf --max-time 10 -X GET "$BASE/v1/auth/me" -H "X-API-Key: $KEY"
curl -sf --max-time 10 -X GET "$BASE/v1/entities" -H "X-API-Key: $KEY"
```

Save an explicit request (`manual`); use `agent` for your own inference.
Omitting scope makes a direct HTTP save private. A subject grants no access.

```bash
curl -sf --max-time 10 -X POST "$BASE/v1/memories" -H "X-API-Key: $KEY" -H 'Content-Type: application/json' -d '{"text": "Owns the retrieval pipeline", "kind": "fact", "source_role": "manual", "scope": "mem-os", "subject": "sasha"}'
```

Search (add `"include_untrusted": true` only when those claims are wanted), then
read before editing, citing evidence or reviewing a fact:

```bash
curl -sf --max-time 10 -X POST "$BASE/v1/memories/search" -H "X-API-Key: $KEY" -H 'Content-Type: application/json' -d '{"query": "package manager", "include_sources": true, "budget_tokens": 800}'
curl -sf --max-time 10 -X GET "$BASE/v1/memories/<id>" -H "X-API-Key: $KEY"
curl -sf --max-time 10 -X GET "$BASE/v1/memories/<id>/sources" -H "X-API-Key: $KEY"
curl -sf --max-time 10 -X GET "$BASE/v1/memories/<id>/history" -H "X-API-Key: $KEY"
curl -sf --max-time 10 -X PATCH "$BASE/v1/memories/<id>" -H "X-API-Key: $KEY" -H 'Content-Type: application/json' -d '{"expected_revision": 3, "text": "Prefers pnpm"}'
curl -sf --max-time 10 -X GET "$BASE/v1/review" -H "X-API-Key: $KEY"
curl -sf --max-time 10 -X POST "$BASE/v1/memories/<id>/review" -H "X-API-Key: $KEY" -H 'Content-Type: application/json' -d '{"decision": "confirm", "expected_revision": 3}'
```

Archive reversibly, or restore:

```bash
curl -sf --max-time 10 -X DELETE "$BASE/v1/memories/<id>" -H "X-API-Key: $KEY"
curl -sf --max-time 10 -X POST "$BASE/v1/memories/<id>/restore" -H "X-API-Key: $KEY"
```

Resolve an entity, read its profile, or load the caller's profile if absent:

```bash
curl -sf --max-time 10 -X POST "$BASE/v1/entities/resolve" -H "X-API-Key: $KEY" -H 'Content-Type: application/json' -d '{"name": "Sasha"}'
curl -sf --max-time 10 -X GET "$BASE/v1/entities/<slug>/profile" -H "X-API-Key: $KEY"
curl -sf --max-time 10 -X POST "$BASE/v1/profiles/render" -H "X-API-Key: $KEY" -H 'Content-Type: application/json' -d '{"workspace": "mem-os", "budget_tokens": 600}'
```

Only without automatic capture: send authorized conversation events in batches
of at most 100, using stable `external_source`/`external_id` pairs to deduplicate.
Close the session only after all batches succeed. A failed batch must not be closed.

```bash
curl -sf --max-time 10 -X POST "$BASE/v1/evidence/events:batch" -H "X-API-Key: $KEY" -H 'Content-Type: application/json' -d '{"events": [{"session_id": "example-session", "role": "user", "content": "Prefers pnpm", "external_source": "example-agent", "external_id": "example-turn-1"}]}' && \
curl -sf --max-time 10 -X POST "$BASE/v1/sessions/<id>/close" -H "X-API-Key: $KEY"
```

For other capabilities and exact schemas, read the service's `/openapi.json`.
Check response status and body before claiming success; stop on unavailable or
unauthorized service rather than retrying indefinitely.
