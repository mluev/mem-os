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

import yaml

from . import (
    benchmark,
    consolidate,
    operations,
    outbox,
    policy_sweep,
    privacy,
    reextract,
    reindex,
    store,
    vectors,
)
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
    result = privacy.erase_owner(
        conn,
        client,
        get_embedder(),
        owner_id=settings.owner_id,
        export_dir=settings.export_dir,
    )
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


def _configure_hermes(home: Path, settings: object) -> None:
    config_path = home / "config.yaml"
    existing = (
        yaml.safe_load(config_path.read_text(encoding="utf-8-sig")) or {}
        if config_path.exists()
        else {}
    )
    existing.setdefault("memory", {})["provider"] = "memkit"
    plugin = existing.setdefault("plugins", {}).setdefault("memkit", {})
    plugin.update(
        {
            "base_url": f"http://{settings.host}:{settings.port}",
            "db_path": str(settings.db_path.expanduser().resolve()),
            "budget_tokens": int(plugin.get("budget_tokens", 800) or 800),
            "prefetch_timeout": float(plugin.get("prefetch_timeout", 0.4) or 0.4),
            "send_tool_results": False,
        }
    )
    if settings.api_key_file is not None:
        plugin["api_key_file"] = str(settings.api_key_file.expanduser().resolve())
    config_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = config_path.with_suffix(".yaml.tmp")
    temporary.write_text(
        yaml.safe_dump(existing, default_flow_style=False, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    os.chmod(temporary, 0o600)
    temporary.replace(config_path)


def _install_hermes(
    *,
    hermes_home: str | None = None,
    force: bool = False,
    settings: object | None = None,
) -> Path:
    source = _hermes_source()
    if not source.is_dir():
        raise RuntimeError("Hermes provider is missing from this installation")
    home = Path(hermes_home or os.environ.get("HERMES_HOME") or "~/.hermes").expanduser()
    target = home / "plugins" / "memkit"
    if target.exists() and not force:
        raise FileExistsError(f"{target} exists; pass --force to replace it")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__"))
    if settings is not None:
        _configure_hermes(home, settings)
    return target.resolve()


def cmd_install_hermes(args: argparse.Namespace) -> int:
    try:
        target = _install_hermes(
            hermes_home=args.hermes_home,
            force=args.force,
            settings=get_settings(),
        )
    except (RuntimeError, FileExistsError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(target.resolve())
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    report = operations.doctor(get_settings(), load_model=args.load_model)
    if args.json:
        _json(report)
    else:
        for check in report["checks"]:
            mark = "OK" if check["ok"] else "FAIL"
            print(f"{mark:4} {check['name']}: {check['detail']}")
    return int(not report["ok"])


def cmd_service(args: argparse.Namespace) -> int:
    result = operations.service_action(args.action, get_settings())
    _json(result)
    return int(not result["ok"])


def cmd_backup(args: argparse.Namespace) -> int:
    settings = get_settings()
    if args.backup_action == "create":
        result = operations.create_backup(settings, kind=args.kind, protected=args.protected)
        operations.prune_backups(settings)
    elif args.backup_action == "list":
        result = {"items": operations.list_backups(settings)}
    elif args.backup_action == "verify":
        rows = {str(row["id"]): row for row in operations.list_backups(settings)}
        row = rows.get(args.id)
        if row is None:
            print("unknown backup artifact", file=sys.stderr)
            return 1
        result = operations.verify_backup(Path(row["path"]), expected_sha256=row["sha256"])
    elif args.backup_action == "prune":
        result = operations.prune_backups(settings)
    elif args.backup_action == "restore":
        operations.service_action("stop", settings)
        try:
            result = operations.restore_backup(settings, artifact_id=args.id, confirm=args.confirm)
        finally:
            operations.service_action("restart", settings)
    else:  # pragma: no cover - argparse constrains this
        raise AssertionError(args.backup_action)
    _json(result)
    return 0


def cmd_setup(_args: argparse.Namespace) -> int:
    result = operations.setup(
        get_settings(),
        install_hermes=lambda force, settings: _install_hermes(force=force, settings=settings),
    )
    _json(result)
    return int(not result["doctor"]["ok"])


def cmd_benchmark_retrieval(args: argparse.Namespace) -> int:
    result = benchmark.run_100k(get_settings(), memories=args.memories, query_count=args.queries)
    _json(result)
    return int(not result["passed"])


def cmd_policy_sweep(args: argparse.Namespace) -> int:
    settings = get_settings()
    init_db(settings.db_path)
    conn = connect(settings.db_path)
    try:
        if args.activate:
            path = settings.export_dir / "release-artifacts" / f"policy-sweep-{args.activate}.json"
            result = policy_sweep.activate(
                conn,
                artifact_path=path,
                checksum=args.activate,
                confirm=args.confirm,
            )
        else:
            result = policy_sweep.sweep(
                conn,
                owner_id=settings.owner_id,
                output_dir=settings.export_dir / "release-artifacts",
            )
    finally:
        conn.close()
    _json(result)
    return int(not result.get("passed", result.get("activated", False)))


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

    setup = commands.add_parser("setup", help="install and validate a production instance")
    setup.set_defaults(func=cmd_setup)

    doctor = commands.add_parser("doctor", help="check every local dependency")
    doctor.add_argument("--json", action="store_true")
    doctor.add_argument("--load-model", action="store_true")
    doctor.set_defaults(func=cmd_doctor)

    service = commands.add_parser("service", help="manage the macOS background service")
    service.add_argument(
        "action", choices=["install", "start", "stop", "restart", "status", "uninstall"]
    )
    service.set_defaults(func=cmd_service)

    backup = commands.add_parser("backup", help="create, verify, prune, or restore backups")
    backup_commands = backup.add_subparsers(dest="backup_action", required=True)
    backup_create = backup_commands.add_parser("create")
    backup_create.add_argument(
        "--kind",
        choices=["auto", "daily", "weekly", "pre-migration", "pre-promotion", "emergency"],
        default="auto",
    )
    backup_create.add_argument("--protected", action="store_true")
    backup_commands.add_parser("list")
    backup_verify = backup_commands.add_parser("verify")
    backup_verify.add_argument("--id", required=True)
    backup_commands.add_parser("prune")
    backup_restore = backup_commands.add_parser("restore")
    backup_restore.add_argument("--id", required=True)
    backup_restore.add_argument("--confirm", default="")
    backup.set_defaults(func=cmd_backup)

    retrieval_benchmark = commands.add_parser(
        "benchmark-retrieval", help="run the protected 100k retrieval latency gate"
    )
    retrieval_benchmark.add_argument("--memories", type=int, default=100_000)
    retrieval_benchmark.add_argument("--queries", type=int, default=50)
    retrieval_benchmark.set_defaults(func=cmd_benchmark_retrieval)

    sweep = commands.add_parser("policy-sweep", help="evaluate labelled retrieval weights offline")
    sweep.add_argument("--activate", help="manually activate a passing artifact checksum")
    sweep.add_argument("--confirm", default="")
    sweep.set_defaults(func=cmd_policy_sweep)

    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
