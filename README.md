# Mem OS

Single-owner memory infrastructure for agents. It stores source evidence, durable observations, profiles, and schema-defined records. It deliberately does not manage tasks, status, schedules, or workflows.

SQLite is authoritative. Transactional FTS5 and bounded Qdrant candidates are fused by a versioned retrieval policy. Secrets are removed before persistence and before any model call.

## Install

Production installation requires Python 3.12, `uv`, Docker, and the packaged wheel. The dashboard and Hermes adapter are bundled; Node, pnpm, and a repository checkout are not required.

```bash
uv tool install ./memkit-0.2.0-py3-none-any.whl
memkit setup
memkit doctor
```

The API is at `http://127.0.0.1:8077`; the bundled dashboard is at `/ui/`. `/healthz` is public and minimal. `/readyz` checks dependencies. Detailed health and metrics require the API key.

`memkit setup` creates restricted production configuration and a generated API key, validates pinned Qdrant `1.18.2`, initializes SQLite, installs the bundled Hermes adapter and macOS launchd services, warms the embedding model, creates a verified backup, and runs the final diagnostic. On Linux, run `memkit serve` with your process supervisor; automatic Linux service installation is intentionally not included in this release.

## Operations

```bash
uv run memkit import-claude-code --dry-run
uv run memkit import-claude-code
uv run memkit drain-index
uv run memkit reindex
uv run memkit consolidate             # dry-run, reports semantic clusters
uv run memkit consolidate --apply
uv run memkit consolidate --apply --merge   # LLM-confirmed near-duplicate merge
uv run memkit eval --compare          # retrieval eval, repo checkout only
uv run memkit export
uv run memkit replay-report            # non-mutating legacy replay plan
uv run memkit erase --confirm ERASE
uv run memkit install-hermes
uv run memkit install-claude-code     # mem-os skill + hooks for Claude Code
uv run memkit doctor --json
uv run memkit service status
uv run memkit backup create
uv run memkit backup list
uv run memkit backup verify --id BACKUP_ID
uv run memkit backup restore --id BACKUP_ID --confirm RESTORE
uv run memkit benchmark-retrieval
uv run memkit policy-sweep
```

Long API operations return a durable `job_id`; inspect or cancel them through `/v1/jobs/{id}`. The startup worker recovers expired job, message, outbox, and budget leases. `POST /v1/admin/reextract` with `{"apply": true}` creates a resumable shadow replay and review batch; it never mutates live memory. Reindex builds validated generation collections and switches aliases only after the exact SQLite ID set is present.

## Backup, restore, and promotion

Schema migrations create and verify an online pre-migration backup, then run SQLite integrity and foreign-key checks before and after each checksummed migration. Daily backup scheduling keeps seven daily and four weekly recovery points; migration and promotion checkpoints are protected separately.

```bash
memkit backup create
memkit backup prune
```

Restore validates the selected artifact, retains an emergency copy, replaces SQLite atomically, rebuilds Qdrant, and restores the emergency copy if rebuilding fails. Real replay promotion requires the immutable approval checksum and `confirm="PROMOTE"`; it uses a protected checkpoint, a maximum 15-minute maintenance window, exact-ID generation validation, and automatic SQLite/Qdrant rollback. Retired vector generations remain available for seven days.

The tested pair is Qdrant server `1.18.2` with `qdrant-client==1.18.0`; the BGE-M3 repository commit is pinned in configuration. For upgrades: back up SQLite, read the release notes, update the tested pair explicitly, run `uv sync --all-groups`, rebuild the frontend, start the service (migrations run once), verify `/readyz`, then reindex if the embedding revision changed. Upgrade Qdrant one minor version at a time when its release notes require it.

## Verify and package

```bash
uv run pytest -q
uv run ruff check src tests tools integrations/hermes eval
uv run ruff format --check src tests tools integrations/hermes eval
uv run pytest -q --cov=memkit --cov-fail-under=75
uv run python -m eval.golden --schema-only
pnpm --dir web lint
pnpm --dir web typecheck
pnpm --dir web test
pnpm --dir web test:e2e
pnpm --dir web build
uv run python tools/export_openapi.py
uv build
```

The OpenAPI-generated SDKs live in `sdk/python` and `sdk/typescript`. CI regenerates both, builds clean packages, checks the `X-API-Key` contract, and consumer-tests the packaged TypeScript declarations. See [docs/README.md](docs/README.md) for the architecture and contracts.
