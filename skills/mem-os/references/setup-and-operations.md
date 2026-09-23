# Setup and operations

Read this when Memkit is not connected yet, when the user asks to manage their
account, access or data, or when they ask you to operate a hosted server.
Everything here acts on real accounts and data, so run it only on request. Show
the user what a destructive command will do before running it.

## Connect

Install the CLI either from a release wheel with `uv tool install memos_cli-*.whl`
or `pipx install`, or from a checkout with `uv tool install ./cli`. Then connect
once:

```bash
memos setup --api-key-file ./memos-key --json
memos setup --handle alice --password-file ./password --agents claude codex --json
memos status --json
memos whoami --json
```

- Setup saves a named connection (`--name`, default `default`). With a handle
  and password it creates a device key, and never stores the password.
  `--agents` also installs agent integrations (see below).
- Never ask the user to paste secrets into the chat. Point them to a key or
  password file, or to `-` for stdin in their own terminal.
- `memos status` checks the URL, identity and service readiness together.
  `memos health` and `memos ready` check the service without signing in.

Several servers or identities:

```bash
memos connections list --json
memos connections use work --json
memos connections remove old --json
memos search "on-call rota" --connection work --json
```

- The connection is chosen in this order:
  1. `--connection`
  2. `MEMOS_CONNECTION`
  3. the repository's `.memkit.toml` `connection`
  4. the saved default
- `--url` and `MEMOS_URL` override the URL.

## Agent integrations

```bash
memos agents install --json
memos agents install claude hermes codex --json
memos agents install --skills-dir ~/.config/my-agent/skills --json
memos agents install codex --home ~/.codex-work --json
memos agents status --json
```

- The installer copies this skill (`mem-os/SKILL.md` and `references/`) into
  each agent's `skills` directory, or into any directory with `--skills-dir`.
- Claude also gets capture/recall hooks merged into `settings.json`.
- Hermes gets the Memkit memory provider.
- Existing configuration is preserved, and replaced files are backed up as
  `*.before-memos-*`. Re-running the installer upgrades in place.
- Codex and custom agents get the skill only, so use manual synchronization
  ([synchronization.md](synchronization.md)).
- The legacy server package installer, `memkit install-claude-code`, copies the
  same skill. Its hooks keep working on their own, but the skill needs `memos`
  installed and connected.

Repository defaults live in `.memkit.toml` at the repository root:

- `entity`: default shared scope for saves.
- `capture`: whether conversations here are uploaded.
- `recall`: whether adapters search on each prompt.
- `connection`: which saved connection to use.

## Accounts, keys and users

```bash
memos auth me --json
memos auth login --data @login.json --json
memos auth logout --json
memos auth password --data @password-change.json --json
memos keys list --json
memos keys create --name "ci-runner" --json
memos keys revoke KEY_ID --json
memos users list --json
memos users create --data @new-user.json --json
memos users update USER_ID --disabled --json
memos users erase USER_ID --confirm "ERASE ALL DATA" --json
```

- A new key's secret is shown once; tell the user where it went and never
  print it back unless asked.
- `auth login` and `auth logout` manage browser-style sessions; agents normally
  use the saved key instead.
- `users erase` irreversibly deletes a person's private data. Their authored
  shared memories remain the team's record. Run it only on an explicit request
  and confirm the target first.
- Users can erase themselves; administrators can erase anyone.

## Policies

```bash
memos policies list --kind retrieval --json
memos policies create --data @policy.json --json
```

Policies are versioned configurations for `extraction`, `retrieval`,
`retention` and `consolidation`, optionally per scope. Read
`memos schema policies create --json` before writing one.

## Export

```bash
memos export --output ./memkit-export.json --json
memos jobs download JOB_ID --output ./memkit-export.json --json
```

Export collects everything the user owns or authored. It runs as a job; with
`--output`, the CLI waits for the job and downloads the result.

## Diagnostics and administration

```bash
memos admin health --json
memos admin metrics --json
memos admin stats memories --days 30 --group-by kind --json
memos admin stats pipeline --days 7 --json
memos admin stats retrieval --days 7 --json
memos admin stats review --days 7 --json
memos admin stats users --days 30 --json
memos admin stats entities --limit 20 --json
memos admin judge-runs list --limit 20 --json
memos admin judge-runs get RUN_ID --json
memos admin backups --json
memos admin reindex --json
memos admin consolidate --dry-run --json
memos admin reextract --json
```

- Reindex, consolidation and re-extraction start background jobs. Follow them
  with `memos jobs get JOB_ID --wait 300 --json`.
- Admin commands need an administrator identity. A refusal is an answer, not
  something to work around.

## Hosted server (over SSH)

```bash
memos server install --host deploy@server --image ghcr.io/mluev/mem-os:memos-v0.1.0 --password-file ./admin-password --provider-key-file ./gemini-key
memos server status
memos server start
memos server doctor
memos server logs --limit 100
memos server restart
memos server upgrade --image ghcr.io/mluev/mem-os:memos-vNEXT
memos server tunnel
memos server reindex
memos server drain-index --limit 100
memos server consolidate --merge
memos server reextract-report
memos server eval --target memories --limit 50
memos server bench
memos server import-claude-code --path /srv/transcripts --user alice --apply
memos server import-sqlite --path /srv/old-memkit.db --user alice --pending
memos server stop
```

- Server commands orchestrate Docker Compose on the remote host through SSH;
  nothing runs in local Docker.
- Always use a versioned image, never `latest`.
- Imports read files on the server. `import-claude-code` previews unless
  `--apply` is given.

Backups:

```bash
memos server backup create --protected
memos server backup list
memos server backup verify ARTIFACT_ID
memos server backup download ARTIFACT_ID --output ./memory.dump
memos server backup prune
memos server backup restore ARTIFACT_ID --confirm RESTORE
```

Restore replaces all server data with the backup. Verify the backup first,
confirm with the user, and pass `--confirm RESTORE` only after they agree.

## Discovering everything else

```bash
memos commands --json
memos schema memories update --json
memos schema server backup restore --json
memos memories search --help
```

- `commands` lists every operation and local command.
- `schema` prints exact arguments, types and referenced definitions.
- Exit codes:
  - `2`: invalid input
  - `3`: authentication needed
  - `4`: forbidden
  - `5`: not found
  - `6`: revision conflict
  - `7`: service failure
  - `8`: timeout (inspect the job before retrying)
  - `9`: job failed
