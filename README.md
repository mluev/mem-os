# Mem OS

Single-owner memory infrastructure for agents. It stores source evidence, durable observations, profiles, and schema-defined records. It deliberately does not manage tasks, status, schedules, or workflows.

SQLite is authoritative. Qdrant is a rebuildable dense index; BM25 is computed locally and fused by a versioned retrieval policy. Secrets are removed before persistence and before any model call.

## Start

Requires Python 3.12, `uv`, Docker, Node 22.12+ and pnpm.

```bash
cp .env.example .env
# Set a strong MEMKIT_API_KEY. "change-me" is refused.
docker compose up -d --wait
uv sync --all-groups
pnpm --dir web install --frozen-lockfile
uv run memkit serve
```

The API is at `http://127.0.0.1:8077`; the bundled dashboard is at `/ui/`. `/healthz` is public and minimal. `/readyz` checks dependencies. Detailed health and metrics require the API key.

## Operations

```bash
uv run memkit import-claude-code --dry-run
uv run memkit import-claude-code
uv run memkit drain-index
uv run memkit reindex
uv run memkit consolidate             # dry-run
uv run memkit consolidate --apply
uv run memkit export
uv run memkit replay-report            # analyzes a temporary DB copy
uv run memkit erase --confirm ERASE
uv run memkit install-hermes
```

Long API operations return a durable `job_id`; inspect or cancel them through `/v1/jobs/{id}`. Reindex builds validated generation collections and switches aliases only after the exact SQLite ID set is present.

## Backup, restore, upgrade

Before every v3→v4 upgrade, Mem OS automatically creates `memkit.db.v3.bak` and `exports/task-board-v3.json`. For routine backup:

```bash
sqlite3 data/memkit.db "PRAGMA wal_checkpoint(TRUNCATE); VACUUM INTO 'data/memkit.backup.db';"
```

Restore with the service stopped: retain the damaged file, copy the backup to the configured database path, start Qdrant, then run `uv run memkit reindex`. Qdrant itself need not be backed up.

The tested pair is Qdrant server `1.18.2` with `qdrant-client==1.18.0`; the BGE-M3 repository commit is pinned in configuration. For upgrades: back up SQLite, read the release notes, update the tested pair explicitly, run `uv sync --all-groups`, rebuild the frontend, start the service (migrations run once), verify `/readyz`, then reindex if the embedding revision changed. Upgrade Qdrant one minor version at a time when its release notes require it.

## Verify and package

```bash
uv run pytest -q
uv run ruff check src tests tools integrations/hermes
uv run ruff format --check src tests tools integrations/hermes
pnpm --dir web lint
pnpm --dir web typecheck
pnpm --dir web test
pnpm --dir web build
uv run python tools/export_openapi.py
uv build
```

The OpenAPI-generated SDKs live in `sdk/python` and `sdk/typescript`. See [docs/README.md](docs/README.md) for the architecture and contracts.
