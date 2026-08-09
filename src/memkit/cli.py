"""Operational command line for the single-owner memory service."""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sqlite3
import sys
import tempfile
from importlib import resources
from pathlib import Path

from . import consolidate, outbox, privacy, reextract, reindex, store, vectors
from .config import get_settings
from .db import connect, init_db, transaction
from .embed import get_embedder
from .importers.claude_code import ImportStats, iter_turns
from .observability import configure_logging

configure_logging()
for _noisy in ("httpx", "httpcore", "sentence_transformers", "transformers"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)


def _ready() -> tuple[sqlite3.Connection, object]:
    settings = get_settings()
    init_db(settings.db_path)
    return connect(settings.db_path), vectors.get_client(settings.qdrant_url)


def _json(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    settings = get_settings()
    uvicorn.run("memkit.api:app", host=settings.host, port=settings.port, reload=args.reload)
    return 0


def cmd_bench(_args: argparse.Namespace) -> int:
    result = get_embedder().benchmark()
    _json(result)
    return int(result["dim"] != 1024 or result["median_ms"] >= 300)


def cmd_import(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    if not root.is_dir():
        print(f"no such transcript directory: {root}", file=sys.stderr)
        return 1
    stats = ImportStats()
    turns = iter_turns(root, stats)
    if args.limit:
        turns = turns[: args.limit]
    print(stats.render())
    if args.dry_run:
        print(f"dry run: {len(turns)} normalized events; nothing written")
        return 0

    settings = get_settings()
    init_db(settings.db_path)
    conn = connect(settings.db_path)
    inserted = deduplicated = redacted = 0
    with transaction(conn):
        for turn in turns:
            context = {
                "source_workspace": turn.project,
                "source_branch": turn.git_branch,
            }
            _, duplicate, was_redacted = store.add_message(
                conn,
                session_id=turn.session_id,
                owner_id=settings.owner_id,
                agent_id="claude-code",
                role=turn.role,
                content=turn.text,
                created_at=turn.created_at,
                external_source="claude-code",
                external_id=turn.external_id,
                context=context,
            )
            inserted += int(not duplicate)
            deduplicated += int(duplicate)
            redacted += int(was_redacted)
    client = vectors.get_client(settings.qdrant_url)
    delivery = outbox.drain(conn, client, get_embedder(), limit=max(1, inserted))
    conn.close()
    _json(
        {
            "stored": inserted,
            "deduplicated": deduplicated,
            "redacted": redacted,
            "indexed": delivery.applied,
            "index_failed": delivery.failed,
        }
    )
    return int(delivery.failed > 0)


def cmd_drain(args: argparse.Namespace) -> int:
    conn, client = _ready()
    result = outbox.drain(
        conn, client, get_embedder(), limit=args.limit, ignore_schedule=args.retry_now
    )
    pending = outbox.pending_count(conn)
    conn.close()
    _json({"applied": result.applied, "failed": result.failed, "pending": pending})
    return int(result.failed > 0)


def cmd_reindex(_args: argparse.Namespace) -> int:
    conn, client = _ready()
    result = reindex.rebuild(conn, client, get_embedder())
    conn.close()
    _json(result)
    return 0


def cmd_consolidate(args: argparse.Namespace) -> int:
    settings = get_settings()
    init_db(settings.db_path)
    conn = connect(settings.db_path)
    result = consolidate.run(
        conn,
        owner_id=settings.owner_id,
        stale_days=settings.consolidate_stale_days,
        demotion=settings.consolidate_demotion,
        dry_run=not args.apply,
    )
    conn.close()
    _json({"mode": "apply" if args.apply else "dry-run", **result.as_dict()})
    return 0


def cmd_export(_args: argparse.Namespace) -> int:
    settings = get_settings()
    init_db(settings.db_path)
    conn = connect(settings.db_path)
    path = privacy.export_owner(conn, owner_id=settings.owner_id, export_dir=settings.export_dir)
    conn.close()
    print(path.resolve())
    return 0


def cmd_erase(args: argparse.Namespace) -> int:
    if args.confirm != "ERASE":
        print("refusing erasure: pass --confirm ERASE", file=sys.stderr)
        return 2
    settings = get_settings()
    conn, client = _ready()
    result = privacy.erase_owner(conn, client, get_embedder(), owner_id=settings.owner_id)
    conn.close()
    _json(result)
    return 0


def cmd_replay_report(args: argparse.Namespace) -> int:
    """Migrate and inspect a temporary copy; never rewrite the live database."""
    settings = get_settings()
    source = settings.db_path
    if not source.exists():
        print(f"database does not exist: {source}", file=sys.stderr)
        return 1
    output = Path(args.output).expanduser()
    with tempfile.TemporaryDirectory(prefix="memkit-replay-") as directory:
        copy = Path(directory) / "replay.db"
        source_conn = sqlite3.connect(source)
        target_conn = sqlite3.connect(copy)
        source_conn.backup(target_conn)
        source_conn.close()
        target_conn.close()
        init_db(copy)
        conn = connect(copy)
        result = reextract.dry_run_report(
            conn,
            owner_id=settings.owner_id,
            model=settings.judge_model,
            output_dir=output,
        )
        conn.close()
    _json(result)
    return 0


def _hermes_source() -> Path:
    packaged = resources.files("memkit").joinpath("hermes_provider")
    if packaged.is_dir():
        return Path(str(packaged))
    return Path(__file__).resolve().parents[2] / "integrations" / "hermes" / "memkit"


def cmd_install_hermes(args: argparse.Namespace) -> int:
    source = _hermes_source()
    if not source.is_dir():
        print("Hermes provider is missing from this installation", file=sys.stderr)
        return 1
    home = Path(args.hermes_home or os.environ.get("HERMES_HOME") or "~/.hermes").expanduser()
    target = home / "plugins" / "memkit"
    if target.exists() and not args.force:
        print(f"{target} exists; pass --force to replace it", file=sys.stderr)
        return 1
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__"))
    print(target.resolve())
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="memkit")
    commands = parser.add_subparsers(dest="command", required=True)

    serve = commands.add_parser("serve", help="run the HTTP service")
    serve.add_argument("--reload", action="store_true")
    serve.set_defaults(func=cmd_serve)

    commands.add_parser("bench", help="measure embedding latency").set_defaults(func=cmd_bench)

    importer = commands.add_parser("import-claude-code", help="import normalized evidence")
    importer.add_argument("--root", default="~/.claude/projects")
    importer.add_argument("--dry-run", action="store_true")
    importer.add_argument("--limit", type=int, default=0)
    importer.set_defaults(func=cmd_import)

    drain = commands.add_parser("drain-index", help="deliver queued index updates")
    drain.add_argument("--limit", type=int, default=500)
    drain.add_argument("--retry-now", action="store_true")
    drain.set_defaults(func=cmd_drain)

    commands.add_parser("reindex", help="build and atomically activate a new index").set_defaults(
        func=cmd_reindex
    )

    compact = commands.add_parser("consolidate", help="plan conservative maintenance")
    compact.add_argument(
        "--apply", action="store_true", help="apply the displayed safe maintenance"
    )
    compact.set_defaults(func=cmd_consolidate)

    commands.add_parser("export", help="export all owner data").set_defaults(func=cmd_export)

    erase = commands.add_parser("erase", help="erase SQLite and derived-index owner data")
    erase.add_argument("--confirm", default="")
    erase.set_defaults(func=cmd_erase)

    replay = commands.add_parser("replay-report", help="analyze a temporary copy of legacy data")
    replay.add_argument("--output", default="./data/exports")
    replay.set_defaults(func=cmd_replay_report)

    hermes = commands.add_parser("install-hermes", help="install the packaged Hermes adapter")
    hermes.add_argument("--hermes-home")
    hermes.add_argument("--force", action="store_true")
    hermes.set_defaults(func=cmd_install_hermes)

    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
