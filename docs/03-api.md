# API

`openapi.json` is canonical and generates both SDKs. Requests and responses have named schemas; request models forbid extra fields, and strings, bounds, numbers, and enumerations are validated. Every handler resolves a `Principal` and takes its scopes from it — no endpoint reads an owner from configuration, and no request body may name one.

## Two authentication shapes

An **API key** (`X-API-Key: mk_<prefix>_<secret>`) is what an agent or hook sends. It is looked up by its clear-text prefix and compared in constant time against the stored sha256, identifies exactly one user, and needs no CSRF defence: nothing else can make the caller attach it. The secret is base64url and contains underscores of its own, so the token splits on exactly two separators.

A **session cookie** (`memkit_session`, HttpOnly, Secure, SameSite=Lax, sliding expiry) is what the dashboard uses. The browser attaches it to any request to this origin, including one a hostile page provokes, so a cookie-authenticated mutation must also carry `X-Requested-With: memkit`. A cross-origin form post or image load cannot set that header and CORS is closed, so its presence is the whole defence and no token round-trip is needed. Safe methods do not require it. When both credentials arrive, the key wins: an agent that sends a key means to act as that key's user.

`POST /v1/auth/login` counts failures per handle and per address and answers identically either way, so it cannot be used to discover which handles exist; five failures in a minute return `429`. Changing a password revokes every other session.

## Groups

- auth: login, logout, `GET /v1/auth/me` (principal, scopes, and which are writable), password change;
- users: list, create, patch (display name, role, disabled). Creating and patching are administrator-only, and the last enabled administrator cannot be disabled. Listing is not: a team memory system is unusable if you cannot see who your teammates are, and any of them can be named as a subject. Only identity is returned, never a credential;
- api-keys: list, create, revoke. A user manages their own; an administrator may mint for another. The secret is returned once;
- entities: list, create, get, patch, archive, aliases, members, `POST /v1/entities/resolve` (a conversational name to an entity), and `GET /v1/entities/{slug}/profile` (what the team knows *about* this entity, and what lives *in* its scope);
- evidence: `POST /v1/evidence/events`, `POST /v1/evidence/events:batch` (up to 100), session close;
- memory: create, patch, archive, restore, review, list, get, sources, history, `POST /v1/memories/search`, retrieval runs, and scoped feedback;
- review: `GET /v1/review` — pending memories, unresolved mentions, conflicts, failed jobs, and budget warnings in one queue, because they share one question;
- attention: `POST /v1/attention/{id}/resolve` — link an unresolved name to an entity (which also teaches the alias, so the same name resolves by itself next time) or dismiss it;
- profiles: `POST /v1/profiles/render`;
- policies: list, create (administrator);
- privacy: `POST /v1/export`, `POST /v1/users/{id}/erase` with `confirm="ERASE ALL DATA"`;
- jobs: list, get, cancel, plus reindex, consolidation, and re-extraction planning;
- operations: administrator health, metrics, backup listing, sessions, messages, and model runs.

## Behaviour the schema does not state

A scope named in a request that the caller does not hold is `403`; a scope that does not exist is `404`. A memory fetched by id from an unreachable scope is `404`, never `403` — otherwise the API is an existence oracle for other people's facts. A memory the caller can read but not write is `403` on mutation, which is a different fact about a row they were allowed to see.

Memory patches require `expected_revision` and return `409` when the row has moved underneath them; `POST /v1/memories/{id}/review` accepts an optional one. Every write bumps the revision and appends an immutable revision row, so a correction found by searching can be applied from the search result — which is why search returns `revision`. Moving a memory between scopes requires `move_scope=true` and changing its context requires `move_context=true`: both change who can read a fact, so they are said out loud rather than inferred from a field appearing in a patch.

Evidence and memory writes report authoritative storage separately from indexing; `stored` is the promise, `indexed` is the state of a derived view. Evidence indexing is the worker's job rather than the request's, because draining inline made a hundred-event hook batch wait for a hundred embeddings.

A manual save into the caller's own scope with `source_role` of `user` or `manual` is stored `confirmed`; anything else is `pending`. An exact duplicate in the same scope, kind, and context returns the existing id with `deduplicated: true` rather than a twin.

Search responses carry component scores, dropped ids by reason, `policy_id`, token use, timings, and an optional `retrieval_id`. `POST /v1/retrieval-runs/{id}/feedback` accepts labels only for a result that run actually returned. The legacy feedback path HMACs its raw query and immediately discards it.

Long operations return a durable `job_id` and are inspected or cancelled through `/v1/jobs/{id}`. `POST /v1/admin/reextract` plans a re-extraction and never rewrites the store.

`GET /healthz` reveals only `{"ok": true}`. `/readyz` is public for orchestration and reports database, index, and embedder separately. Everything under `/v1` requires a credential; the request body limit is 2 MB.
