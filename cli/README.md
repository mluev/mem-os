# memos

The lightweight client for hosted Mem OS. Your laptop runs only the CLI and
small agent adapters. Databases, Docker, embeddings, extraction, indexing and
backups run on the server.

## Install and connect

Requires Python 3.11 or newer. From this checkout:

```sh
uv tool install ./cli
memos setup --url https://memory.example.com
memos agents install claude hermes codex
memos status
```

For a built release, install its `memos_cli-*.whl` with `uv tool install` or
`pipx install`. The CLI depends only on HTTPX and PyYAML, plus their small
dependencies. It does not install the `memkit` server package.

Setup asks for your handle and password, creates a device API key, and discards
the login session. For automation use `--handle alice --password-file /path/to/file`
or `--api-key-file /path/to/key`; `-` reads the secret from stdin. Avoid placing
credentials in command arguments. Existing `~/.config/memkit/client.env` and
`~/.memkit` settings are imported without deleting the originals.

Connections are saved in `~/.config/memkit/connections.json` with owner-only
permissions. `MEMOS_CONFIG_DIR` overrides this directory for tests or isolation.

```sh
memos setup --name work --url https://memory.example.com
memos connections list
memos connections use work
memos --connection work search "release decision"
```

Selection order: `--connection`, `MEMOS_CONNECTION`, repository connection,
saved default. URL overrides are `--url`, `MEMOS_URL`, `MEMKIT_BASE_URL`; key
overrides are `MEMOS_API_KEY`, `MEMKIT_API_KEY`. Otherwise use the selected
connection's URL and key. No key is displayed by connection listings or status.

## Everyday use

```sh
memos remember "Use pnpm for this project"
memos search "What did we decide about authentication?" --include-sources
memos profile
memos memories get MEMORY_ID
memos memories update MEMORY_ID --text "Updated decision" --expected-revision 3
memos forget MEMORY_ID
memos memories restore MEMORY_ID
memos review list
memos entities resolve --name Sasha
memos export --wait 60 --output ./my-memory.json
```

`remember` means the user explicitly asked to save the fact. An agent saving
on its own must pass `--source-role agent`. Search follows the service's trust
rules; no results is a successful response. Forgetting archives reversibly.
Erasing a user requires `--confirm 'ERASE ALL DATA'` and server authorization.

Update reads the current revision if omitted, and reports a conflict if another
writer changes it. Passing a revision from an earlier read also protects the
time spent considering an edit. Scope moves still require `--move-scope`.

Repository settings live in `.memkit.toml` and are discovered up to the Git root:

```toml
[memkit]
connection = "work"
entity = "project-slug"
capture = true
recall = true
```

Omit `entity` for private explicit saves. Scope controls who can read a fact;
subject only identifies whom it concerns. Explicitly configured scopes are sent
for server authorization; a forbidden destination fails without saving privately.
Implicit repository-alias discovery still falls back to private when no writable
match exists. Shared writes may be pending review while already retrievable.

## Complete API access and automation

```sh
memos commands --json
memos schema memories update --json
memos memories update --help
memos memories list --limit 100 --all --wait 120
memos evidence batch --data @events.json
memos jobs get JOB_ID --wait 60
memos jobs download JOB_ID --output ./export.json
```

Every API operation has a named command. Groups cover memories, entities,
users, keys, evidence, sessions, review, attention, profiles, retrieval,
policies, jobs and administration. Ordinary fields have flags; object/array
flags accept JSON. `--data @file` and `--data -` accept complete JSON bodies;
explicit flags override corresponding body fields. Never interpolate user
text into shell code.

Explicit JSON `null` on object/array flags overrides a value supplied through
`--data`. Use `--` before positional text that looks like an option, for example
`memos --json remember -- --json`. For text fields, `--text=--json` saves the
literal value `--json`.

Terminal output is readable text; redirected output is JSON. Force a format
with `--json` or a trailing `--text` (or place `--text` before the command).
`--text VALUE` on a memory command is its text field. Global options also
include `--connection`, `--url`, and `--timeout` (default 15 seconds).

JSON success is `{"ok":true,"data":...}`. Failure is
`{"ok":false,"error":{"code":"...","message":"...","status":...}}`.
Diagnostics go to stderr. Noninteractive invocations never ask questions.
Failed server diagnostics retain the sanitized check report in `error.details`
and return exit 7. Malformed server responses also return exit 7; invalid local
configuration returns exit 2. SSH tunnel and download timeouts return exit 8.

| Exit | Meaning |
|---|---|
| 0 | Success, including empty search |
| 2 | Invalid input or configuration |
| 3 | Authentication needed |
| 4 | Forbidden |
| 5 | Not found |
| 6 | Revision/conflict |
| 7 | Service, rate limit, or remote failure |
| 8 | Timeout; inspect a queued job before retrying |
| 9 | Background job failed or was cancelled |
| 130 | Interrupted |

Writes are not automatically retried. `--wait` is bounded to at most one hour;
timing out does not cancel a server job. `--all` is supported on APIs with offset
pagination and includes the first API request in its `--wait` budget (60 seconds
by default). Timeout and wait values must be finite. API request bodies
are limited to 2 MB; split large evidence uploads into batches of at most 100.

## Agents

`memos agents install` detects installed agents. Pass names explicitly or use
`--skills-dir /path/to/skills` for another agent. Installation merges owned hooks
and settings, backs up replaced files, and preserves unrelated configuration.

Every target receives the same agent-neutral Memkit skill: `mem-os/SKILL.md`
plus its `references/`. The canonical source is
[`skills/mem-os`](../skills/mem-os/SKILL.md); the wheel ships a copy that
`tools/sync_cli_assets.py --check` keeps identical, flagging missing, changed
and stale files. The skill drives memory only through `memos` and has no HTTP
fallback. Upgrades rewrite changed files, back up replaced ones, and remove the
obsolete `HTTP.md` from earlier releases. `memos agents status` reports whether
each agent's skill is complete (`skill`) and current (`skill_current`).

- Claude: profile at session start and after compaction; gated recall;
  incremental capture at Stop, PreCompact and SessionEnd.
- Hermes: existing search/remember tools and lifecycle callbacks, connected
  through the installed CLI. The bridge uses the CLI's connection and identity;
  old plugin-specific URL/key settings are replaced during installation.
- Codex and other agents: portable skill plus full CLI access. Automatic
  lifecycle capture requires an adapter; installing a skill alone cannot add it.

Agent hooks fail open when the service is unavailable. Explicit commands report
errors. Run `memos agents status` to inspect installation and connection health.
Capture retains only cursors and small metadata caches locally, not a memory
database. Source transcripts remain owned by the agent. No offline sync is added.

Both client and server packages ship the same Claude hook, transcript classifier
and Hermes provider sources. Their small runtime wrappers preserve existing
credentials and defaults: `memos` enables gated Claude recall and keeps cursors
per connection; legacy `memkit` installs retain opt-in recall and their original
cursor directory. Reinstalling an adapter does not reset either directory.
Session close waits for pending evidence within a bounded deadline. If delivery
fails or remains incomplete, the adapter reports it and leaves the session open.

## Hosted server management

These commands require Linux, Python 3 and Docker Compose **on the SSH server**,
and SSH access from the client. They never invoke local Docker. SSH uses your
existing keys, host aliases and known-host configuration in noninteractive mode.

```sh
memos server install --host deploy@server \
  --image ghcr.io/mluev/mem-os:memos-v0.1.0 \
  --password-file ./admin-password --provider-key-file ./gemini-key
memos server status
memos server logs --limit 100
memos server doctor
memos server restart
memos server upgrade --image ghcr.io/mluev/mem-os:memos-vNEXT
memos server backup create --protected
memos server backup list
memos server backup verify ARTIFACT_ID
memos server backup download ARTIFACT_ID --output ./memory.dump
memos server backup restore ARTIFACT_ID --confirm RESTORE
memos server stop
```

Image tags above illustrate the release convention; they exist only after the
release workflow succeeds. For an unreleased checkout already on the server,
pass `--source /srv/mem-os --image memos-dev:VERSION`; the build runs remotely.

Install creates an isolated Compose project under `~/.local/share/memos/server`,
generates server secrets, creates persistent storage and the initial user, then
saves the client connection. Repeated installation preserves existing users,
credentials and data. A Gemini provider key enables automatic extraction; without
one, manual memory operations remain available but model extraction is not ready.
Reinstallation also preserves a named connection's saved ports, URL, and device
key when those options are omitted. Conflicting remote ports or URL modes are
rejected. `--remote-port` and `--local-port` belong to `server install`;
the remote port comes from deployment metadata when reconnecting to an existing
deployment. Changing a local tunnel port preserves the key for that deployment.

The app binds only to server loopback. By default the CLI opens an SSH tunnel
to local port 18077. Supply `--url https://memory.example.com` when an existing
HTTPS reverse proxy is configured. `memos server tunnel --close` closes the
tunnel; normal API commands reopen a saved tunnel when needed.

Upgrade makes a verified protected backup and checks readiness. If the new
image fails, it restores the old image; schema-changing upgrades require a
separate migration procedure and are refused. Restore verifies the checksum,
takes a recovery backup, stops app writers, refuses other active database
clients, restores Postgres, rebuilds Qdrant and checks readiness. On restore
failure, inspect server status before restarting.

Backup metadata also lives in a private catalog on the server, outside Postgres.
Recovery backups remain discoverable after restoring an older database or while
the normal app is stopped. Backup operations run in temporary server containers.

Other hosted operations include `reindex`, `drain-index`, `consolidate`,
`reextract-report`, `bench`, `eval`, `import-claude-code`, and `import-sqlite`.
Import paths are remote paths beneath the deployment's `imports` directory;
files must be readable by the app container user. Claude imports default to
dry-run until `--apply`; `--limit` bounds both preview and applied imports and
defaults to 100. Existing platform-managed deployments remain usable
through the API; deployment commands refuse to take over an unmanaged directory.

Use `server doctor --load-model` for an actual model check,
`server drain-index --retry-now` to retry delayed index work, and
`server backup create --kind daily` to select a backup category. Each option is
also listed by `schema` and command-specific `--help`.

## Development and verification

```sh
uv run --project cli --with pytest python -m pytest cli/tests
python tools/sync_cli_assets.py --check
uv build --project cli
```

Canonical OpenAPI and existing adapter/classifier sources generate the packaged
snapshots via `tools/sync_cli_assets.py`. CI checks snapshot drift and complete
operation coverage. New export routes require regenerating the server OpenAPI
and both SDKs before syncing CLI assets.

`memos-cli.yml` validates client-only installations on Python 3.11–3.13. Its
opt-in remote smoke job provisions a disposable CI runner over SSH and tests
install, restart, repeated setup, upgrade, backup/restore, and export. It does
not run Docker on the developer's machine.

`memos-release.yml` builds the hosted image and attaches CLI distributions on
`memos-v*` tags matching the CLI version. No release is published by local builds.
