# Mem OS

Team memory infrastructure for agents. Several people and their agents share one instance: each person has a private scope, the team has a shared one, and a fact about a teammate is attributed to that teammate rather than buried in whoever happened to mention it. It stores source evidence, durable facts, and session profiles. It deliberately does not manage tasks, status, schedules, or workflows.

Postgres is authoritative. A generated `tsvector` column and bounded Qdrant candidates are fused by a versioned retrieval policy that is allowed to return nothing. Secrets are removed before persistence and before any model call. Every request resolves to one principal, and a scope that principal does not hold is refused rather than quietly filtered away.

## How it works

**Evidence.** Agents post conversation turns to `/v1/evidence/events` (or a batch of up to a hundred). Each turn is redacted, stored against a session whose user, scope, and agent are fixed at creation, and — for user turns over the length floor — queued for the raw index. Evidence is never rewritten: every future change to the extractor prompt must be able to replay the same history.

**Extraction.** When ten messages have accumulated, a session closes, or somebody says "remember this", a durable job leases exactly one ten-message window and calls the judge once. The model receives the window, candidate memories it may correct, the session's recording date as the anchor for relative time, and a numbered list of the entities the speaker can see. It must cite an exact span of a *user* message for every claim; the service re-slices that span, hashes it, and refuses anything it cannot verify. A fact supported only by the assistant's own words is rejected at the write, because a model reading its own claim back as established fact is a loop with no visible beginning.

**Routing.** The same call decides where the fact belongs, by number. A fact about the speaker stays private — the default. A fact about a listed teammate goes to the **team** scope with that person as subject, so the team can see it and the person can delete it. A fact about a project or a rule stated for everyone goes to that scope. A name nobody can place keeps the fact private and unattributed and raises a review item asking a human who was meant: guessing which teammate was intended puts a claim on the wrong person's profile.

**Memory.** The fact lands live and `pending`. It is retrievable immediately — an unconfirmed fact is still the best thing known — and appears in one queue with unresolved names, failed jobs, and budget warnings. Confirming clears it; declining archives it; undo restores it. A memory you save yourself, in your own scope, is confirmed on arrival, because you just said it. Every change bumps a revision and appends an immutable one, so a correction can be applied from a search result and rolled back from history.

**Retrieval.** A search embeds the query once and runs three bounded arms — dense cosine over Qdrant, `ts_rank_cd` over the Russian-stemmed full-text column, and trigram matching for identifiers a stemmer cannot reach — each filtered to the scopes the caller holds, then fuses them at 0.60/0.30/0.10 and adds importance and recency. Below the policy's relevance floor it returns nothing rather than the least-distant fact. Results carry their scope and subject, so the caller can tell "the team decided" from "you decided", and `include_sources` attaches hash-verified verbatim spans.

**Profile.** At session start an agent asks for a profile instead of a query: five budgeted blocks — who you are, how you like to work, the team's rules, this project, and what changed lately — assembled in one bounded query per block, because this runs before the user has typed anything.

## Quickstart

You need Docker, a `.env` with `POSTGRES_PASSWORD`, a `MEMKIT_TELEMETRY_HMAC_KEY` of at least 32 characters, and a `GEMINI_API_KEY` (see [`.env.example`](.env.example)). Then:

```bash
docker compose up -d                     # app + postgres:16 + qdrant:v1.18.2
curl -fsS localhost:8077/readyz          # first boot downloads the embedding model
```

Create the first person and a key for their agents. Both talk to the database directly, so they run in the app container:

```bash
docker compose exec app memkit users create alice --name "Alice" --admin
docker compose exec app memkit api-keys create --user alice --name laptop
```

The key is printed once. Put it where agents and hooks look for it:

```bash
mkdir -p ~/.config/memkit && chmod 700 ~/.config/memkit
cat > ~/.config/memkit/client.env <<'EOF'
MEMKIT_BASE_URL=http://127.0.0.1:8077
MEMKIT_API_KEY=mk_…
EOF
chmod 600 ~/.config/memkit/client.env
```

Save a fact and find it again:

```bash
export MEMKIT_API_KEY=mk_…
curl -fsS localhost:8077/v1/memories -H "X-API-Key: $MEMKIT_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"text":"Alice prefers pnpm over npm","kind":"preference","source_role":"manual"}'

curl -fsS localhost:8077/v1/memories/search -H "X-API-Key: $MEMKIT_API_KEY" \
  -H 'Content-Type: application/json' -d '{"query":"pnpm"}'
```

The search returns the fact with its scope, subject, review status, and per-arm scores. Sign in to the dashboard at `/ui/` with the same handle and password; the compose file sets `MEMKIT_COOKIE_SECURE=true` for a TLS-terminating proxy, so on a laptop reaching it over plain http, set it false or the session cookie is never stored.

To let Claude Code write memory by itself, install the CLI on the laptop that runs the agent and let it place the skill and hooks; it prints a `settings.json` snippet rather than editing `~/.claude/settings.json` for you:

```bash
uv tool install ./dist/memkit-0.3.0-py3-none-any.whl   # or `uv run memkit` in a checkout
memkit install-claude-code
```

From then on the session-start hook injects the profile, the stop hook posts the transcript delta as evidence, and extraction happens server-side.

Add the rest of the team with `memkit users create`, and give shared work a scope of its own with `memkit entities create "Shop" --kind project --alias магазин`. Aliases are what let a name in conversation route to an entity.

## Operations

The CLI talks to the database directly — half of it exists to fix an instance whose HTTP layer will not start — so it runs wherever `MEMKIT_DATABASE_URL` resolves: `docker compose exec app memkit …` against a deployment, or a plain shell against a local one.

```bash
memkit doctor --json                  # every dependency, plus schema and index parity
memkit bench                          # embedding latency; non-zero above 300 ms
memkit users list
memkit users disable <handle>         # the last administrator cannot be disabled
memkit api-keys create --user <handle>
memkit api-keys revoke <key-id>
memkit entities create <name> --kind project --alias <alias>
memkit entities member <slug> --user <handle> --role member
memkit import-claude-code --dry-run   # then without --dry-run
memkit import-sqlite <path>           # one-time move from a single-owner v6 database
memkit drain-index
memkit reindex
memkit consolidate                    # dry run; reports semantic clusters
memkit consolidate --apply
memkit consolidate --apply --merge    # LLM-confirmed near-duplicate merge
memkit reextract-report               # cost a prompt change without running it
memkit export --user <handle>
memkit erase --user <handle> --confirm ERASE
memkit backup create | list | verify <path> | prune
memkit install-hermes
memkit install-claude-code
memkit eval --compare                 # repository checkout only
```

Long API operations return a durable `job_id`; inspect or cancel them through `/v1/jobs/{id}`. The worker recovers expired job, message, outbox, and budget leases at startup. Reindex builds a validated generation and switches aliases only once the exact Postgres id set is present; the previous generation stays for seven days.

## Backup and restore

`memkit backup create` runs `pg_dump --format=custom`, checksums the archive, and verifies it with `pg_restore --list`, which parses every object header — so a truncated dump fails at backup time rather than half-way through a recovery. Artifacts are registered in the database with their checksum and protection state; `prune` keeps seven daily and four weekly and never touches a protected one.

Restore is deliberately manual. `pg_restore --clean` drops and recreates every object in the archive, nothing else may hold a connection while it does, and the service cannot promise that about itself — its pool reconnects on demand and the worker runs on a timer. So `memkit backup restore` verifies the archive and hands you the command:

```bash
docker compose stop app
pg_restore --clean --if-exists --no-owner --no-privileges --dbname="$MEMKIT_DATABASE_URL" <archive>
docker compose start app
docker compose exec app memkit reindex   # Qdrant is derived; rebuild it from the restore
```

The tested pair is Qdrant server `1.18.2` with `qdrant-client==1.18.0`, and the BGE-M3 commit is pinned in configuration. Changing the embedding model or its width means a reindex, because the stored vectors are in the old model's space. `pg_dump` must match the server's major version, which is why the image installs `postgresql-client-16` rather than vendoring one.

## Local development

```bash
uv sync --all-groups
docker compose up -d postgres qdrant
export MEMKIT_DATABASE_URL=postgresql://memkit:…@127.0.0.1:5432/memkit
export MEMKIT_COOKIE_SECURE=false          # plain http on loopback
uv run memkit serve --reload
pnpm --dir web dev
```

The schema is created and verified on start; there is no separate migrate step. Tests need a Postgres of their own — set `MEMKIT_TEST_DATABASE_URL`, or let the session fixture start a throwaway cluster:

```bash
uv run pytest -q
uv run ruff check src tests tools integrations/hermes eval
uv run python -m tools.docblocks --check
uv run python tools/export_openapi.py
uv build
```

The OpenAPI-generated SDKs live in `sdk/python` and `sdk/typescript`; CI regenerates both and fails on a diff. See [docs/README.md](docs/README.md) for the architecture and contracts, and [docs/decisions/](docs/decisions/) for why each of them is the way it is.
