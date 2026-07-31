# memkit

A local memory service for AI agents. SQLite is the source of truth, Qdrant is a
derived index, embeddings run on Apple Silicon, and an LLM extracts durable facts
from conversation windows. One instance serves every agent you run.

Everything on the read path is local, so reading is free and fast enough to do on
every turn. The extractor is the only component that leaves the machine, and there is
a hard monthly spend ceiling enforced in code.

## Status

Stages 0–6 are done; four items are deliberately not started, and there is open work
that is not code. Per-item state is in
[docs/06-roadmap.md](docs/06-roadmap.md); current numbers are in
[docs/measurements.md](docs/measurements.md).

This file covers installing and running it. Everything else lives in
[`docs/`](docs/) — start with [docs/README.md](docs/README.md).

## Quick start

Requires Docker and [uv](https://docs.astral.sh/uv/). Python 3.12 is pinned
deliberately: torch and sentence-transformers have no reliable wheels for 3.14.

```bash
cp .env.example .env          # then set MEMKIT_API_KEY
docker compose up -d          # Qdrant on 127.0.0.1:6333
uv sync
uv run memkit bench           # stage-0 gate: must be under 100 ms on MPS
```

`memkit bench` exits non-zero if the embedding dimension is not 1024. That check
exists because a silent model swap would make every stored vector incomparable and
nothing else would notice.

Import your Claude Code history and check retrieval:

```bash
uv run memkit import-claude-code --dry-run   # classification report, writes nothing
uv run memkit import-claude-code
uv run memkit eval --compare
uv run memkit serve                          # 127.0.0.1:8077
```

The dashboard is at `http://127.0.0.1:8077/ui/`.

Extraction needs a judge credential. Set `GEMINI_API_KEY` (the default model) or
`ANTHROPIC_API_KEY`, then:

```bash
uv run memkit backfill --dry-run             # prices it before spending anything
```

Without one, `POST /v1/messages` returns `extraction_queued: false` and manual
memories and retrieval still work — a supported mode, not a degraded one.

## Running it

| command | does |
|---|---|
| `memkit serve` | run the API and the dashboard |
| `memkit bench` | embedder latency gate |
| `memkit import-claude-code` | import transcripts; `--dry-run` writes nothing |
| `memkit backfill` | extract from unprocessed history; `--dry-run` prices it |
| `memkit eval --compare` | retrieval eval, both targets over the shared case set |
| `memkit consolidate --dry-run` | preview the nightly merge pass |
| `memkit reindex` | rebuild Qdrant from SQLite |
| `memkit judge-runs` | recent extractions with operations and stated reasons |
| `memkit install-hermes` | install the plugin into `$HERMES_HOME/plugins/` |

Every command that spends money prints an estimate first and refuses without the
right credential.

Reading `memkit judge-runs` by eye daily for the first week is the highest-value
work in the project. It is the only way to see what the extractor thinks it is
doing.

### Frontend development

```bash
pnpm --dir web install
pnpm --dir web dev            # 127.0.0.1:5173/ui/
```

The Vite proxy injects the API key from the root `.env`. The production build asks
once and keeps the key in browser local storage.

### Scheduled jobs

`deploy/` holds two launchd agents: nightly consolidation at 04:00, and the service
itself. Both hardcode absolute paths and pick up `.env` from their working directory;
install them by copying into `~/Library/LaunchAgents/` and editing the paths.

Neither loads automatically. The consolidation agent has `RunAtLoad=false` on purpose
— loading an agent should not spend money.

## Tests

```bash
.venv/bin/python -m unittest discover -s tests -t .
```

Stdlib `unittest`, no pytest, entirely offline. The frontend uses vitest
(`pnpm --dir web test`).

Documentation is partly checked too — the schema, route table, vocabularies,
retrieval constants and configuration defaults in `docs/` are generated from the code
and compared on every run:

```bash
python -m tools.docblocks --check
```

What that can and cannot cover is spelled out in
[docs/08-testing.md](docs/08-testing.md), along with the layers, the known gaps, and
why some of them are gaps rather than oversights.

## Backups

The SQLite file is the only thing that must survive; Qdrant rebuilds from it with
`memkit reindex`.

```bash
sqlite3 data/memkit.db "PRAGMA wal_checkpoint(TRUNCATE)"
sqlite3 data/memkit.db ".backup 'data/memkit.db.bak-$(date +%F)'"
gzip -9 data/memkit.db.bak-$(date +%F)
```

Checkpoint first or the copy loses whatever is still in the write-ahead log. **Gzip
the result**: `init_db` migrates whatever database it is pointed at, including a
backup, which would destroy the rollback path — and compression makes a backup
un-openable by any tool that might try.

## What's where

| | |
|---|---|
| [docs/README.md](docs/README.md) | the design, the five invariants, reading order |
| [docs/measurements.md](docs/measurements.md) | every measured number, dated, with its command |
| [docs/decisions/](docs/decisions/) | why things are as they are, including what was declined |
| [docs/experiments/](docs/experiments/) | dated lab notebooks; frozen results |
| [docs/archive/](docs/archive/) | the original pre-implementation spec, non-normative |

This file makes no claims about the system's behaviour beyond how to start it. That
is deliberate: it used to carry its own status table, endpoint list and measurement
set, all of which drifted from `docs/` and from the code. One home per fact —
[docs/decisions/0002](docs/decisions/0002-four-genre-documentation.md).
