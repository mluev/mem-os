"""Operational command line for the team memory service.

Everything here talks to the database directly rather than over HTTP, because
most of it exists to set an instance up or to repair one whose HTTP layer will
not start: creating the first administrator, minting a key, rebuilding the
index, taking a backup.

Reading and writing memory is deliberately absent. That belongs to a client
holding one user's key, not to a process holding the database password, and it
is not worth blurring the two to save a round trip.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import shutil
import sys
from importlib import resources
from pathlib import Path
from typing import Any

import yaml

from . import (
    auth,
    consolidate,
    entities,
    operations,
    outbox,
    privacy,
    reextract,
    reindex,
    store,
    users,
    vectors,
)
from . import (
    principal as principal_module,
)
from .config import DEFAULT_CONFIG_DIR, get_settings
from .db import connect, init_db, transaction
from .embed import get_embedder
from .importers.claude_code import ImportStats, iter_turns


def _ready() -> tuple[Any, Any]:
    settings = get_settings()
    init_db(settings.database_url)
    return connect(settings.database_url), vectors.get_client(settings.qdrant_url)


def _db() -> Any:
    settings = get_settings()
    init_db(settings.database_url)
    return connect(settings.database_url)


def _json(value: object) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False, default=str))


def _resolve_user(conn: Any, handle: str | None) -> Any:
    """The named user, or the only administrator when there is exactly one.

    Defaulting is a convenience for the common single-admin instance and is
    refused as soon as it would be a guess.
    """
    if handle:
        row = users.by_handle(conn, handle)
        if row is None:
            raise SystemExit(f"unknown user: {handle}")
        return row
    admins = [
        row for row in users.listing(conn) if row["role"] == "admin" and not row["disabled_at"]
    ]
    if len(admins) != 1:
        raise SystemExit("--user is required when the instance has more than one administrator")
    return admins[0]


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "memkit.api:app",
        host=settings.host,
        port=settings.port,
        reload=bool(args.reload),
        proxy_headers=True,
        forwarded_allow_ips="*",
    )
    return 0


def cmd_bench(_args: argparse.Namespace) -> int:
    from .embed import DIM

    result = get_embedder().benchmark()
    _json(result)
    # The gate is the prefetch budget: an embedding slower than this makes
    # session-start injection perceptible.
    return int(result["dim"] != DIM or result["median_ms"] >= 300)


def cmd_doctor(args: argparse.Namespace) -> int:
    report = operations.doctor(get_settings(), load_model=args.load_model)
    if args.json:
        _json(report)
    else:
        for check in report["checks"]:
            status = "ok  " if check["ok"] else "FAIL"
            detail = json.dumps(check.get("detail", {}), ensure_ascii=False)
            print(f"  {status} {check['name']}: {detail}")
    return 0 if report["ok"] else 1


# ---------------------------------------------------------------------------
# People and entities
# ---------------------------------------------------------------------------


def cmd_users_create(args: argparse.Namespace) -> int:
    password = args.password or os.environ.get("MEMKIT_PASSWORD") or getpass.getpass("password: ")
    conn = _db()
    with transaction(conn):
        entities.ensure_team(conn, name=get_settings().team_name)
        try:
            row = users.create(
                conn,
                handle=args.handle,
                display_name=args.name or args.handle,
                password=password,
                role="admin" if args.admin else "member",
                email=args.email,
            )
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
    _json({"id": str(row["id"]), "handle": row["handle"], "role": row["role"]})
    return 0


def cmd_users_list(_args: argparse.Namespace) -> int:
    conn = _db()
    _json(
        [
            {
                "handle": row["handle"],
                "name": row["display_name"],
                "role": row["role"],
                "disabled": bool(row["disabled_at"]),
            }
            for row in users.listing(conn)
        ]
    )
    return 0


def cmd_users_disable(args: argparse.Namespace) -> int:
    conn = _db()
    target = _resolve_user(conn, args.handle)
    if target["role"] == "admin" and users.count_admins(conn, excluding=str(target["id"])) == 0:
        raise SystemExit("the last administrator cannot be disabled")
    with transaction(conn):
        users.update(conn, user_id=str(target["id"]), disabled=not args.enable)
    _json({"handle": target["handle"], "disabled": not args.enable})
    return 0


def cmd_keys_create(args: argparse.Namespace) -> int:
    """Mint an API key. The secret is printed once and never stored in clear."""
    conn = _db()
    target = _resolve_user(conn, args.user)
    with transaction(conn):
        minted = auth.mint_api_key(conn, user_id=str(target["id"]), name=args.name)
    _json(
        {
            "id": minted.id,
            "user": target["handle"],
            "name": args.name,
            "key": minted.token,
            "hint": "store this in ~/.config/memkit/client.env as MEMKIT_API_KEY=…",
        }
    )
    return 0


def cmd_keys_revoke(args: argparse.Namespace) -> int:
    conn = _db()
    with transaction(conn):
        revoked = auth.revoke_api_key(conn, key_id=args.key_id)
    if not revoked:
        raise SystemExit("unknown or already revoked key")
    _json({"revoked": args.key_id})
    return 0


def cmd_entities_create(args: argparse.Namespace) -> int:
    conn = _db()
    creator = _resolve_user(conn, args.user)
    with transaction(conn):
        row = entities.create(
            conn,
            kind=args.kind,
            name=args.name,
            slug=args.slug,
            description=args.description or "",
            created_by=str(creator["id"]),
            aliases=list(args.alias or []),
        )
    _json({"id": str(row["id"]), "slug": row["slug"], "kind": row["kind"]})
    return 0


def cmd_entities_list(_args: argparse.Namespace) -> int:
    conn = _db()
    rows = conn.execute(
        "SELECT * FROM entities WHERE archived_at IS NULL ORDER BY kind, name"
    ).fetchall()
    _json(
        [
            {
                "slug": row["slug"],
                "kind": row["kind"],
                "name": row["name"],
                "aliases": entities.aliases_of(conn, str(row["id"])),
            }
            for row in rows
        ]
    )
    return 0


def cmd_entities_member(args: argparse.Namespace) -> int:
    conn = _db()
    entity = entities.by_slug(conn, args.slug)
    if entity is None:
        raise SystemExit(f"unknown entity: {args.slug}")
    member = _resolve_user(conn, args.user)
    with transaction(conn):
        if args.remove:
            entities.remove_member(conn, entity_id=str(entity["id"]), user_id=str(member["id"]))
        else:
            entities.set_member(
                conn, entity_id=str(entity["id"]), user_id=str(member["id"]), role=args.role
            )
    _json({"entity": entity["slug"], "user": member["handle"], "removed": bool(args.remove)})
    return 0


# ---------------------------------------------------------------------------
# Ingest and maintenance
# ---------------------------------------------------------------------------


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
    conn = _db()
    owner = _resolve_user(conn, args.user)
    caller = principal_module.load(conn, str(owner["id"]))
    inserted = deduplicated = redacted = 0
    with transaction(conn):
        for turn in turns:
            # A transcript belongs to whoever ran it; the repository it came
            # from picks the scope when an entity answers to that name.
            scope_id = caller.own_entity_id
            if turn.project:
                match = entities.resolve_alias(conn, turn.project)
                if match is not None and str(match["id"]) in caller.writable_scope_ids:
                    scope_id = str(match["id"])
            _, duplicate, was_redacted = store.add_message(
                conn,
                session_id=turn.session_id,
                user_id=caller.user_id,
                scope_id=scope_id,
                agent_id="claude-code",
                role=turn.role,
                content=turn.text,
                created_at=turn.created_at,
                external_source="claude-code",
                external_id=turn.external_id,
                context={"source_workspace": turn.project, "source_branch": turn.git_branch},
            )
            inserted += int(not duplicate)
            deduplicated += int(duplicate)
            redacted += int(was_redacted)
    client = vectors.get_client(settings.qdrant_url)
    delivery = outbox.drain(conn, client, get_embedder(), limit=max(1, inserted))
    _json(
        {
            "user": owner["handle"],
            "stored": inserted,
            "deduplicated": deduplicated,
            "redacted": redacted,
            "indexed": delivery.applied,
            "index_failed": delivery.failed,
        }
    )
    return int(delivery.failed > 0)


def cmd_import_sqlite(args: argparse.Namespace) -> int:
    from .importers.sqlite_v6 import import_sqlite

    conn = _db()
    owner = _resolve_user(conn, args.user)
    try:
        report = import_sqlite(
            conn,
            source=Path(args.path).expanduser(),
            user_id=str(owner["id"]),
            pending=bool(args.pending),
        )
    except (FileNotFoundError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    _json(report)
    print("\nnow run `memkit reindex` to rebuild the vector index", file=sys.stderr)
    return int(not report["ok"])


def cmd_drain(args: argparse.Namespace) -> int:
    conn, client = _ready()
    outcome = outbox.drain(
        conn,
        client,
        get_embedder(),
        limit=args.limit,
        ignore_schedule=bool(args.retry_now),
    )
    _json({"applied": outcome.applied, "failed": outcome.failed})
    return int(outcome.failed > 0)


def cmd_reindex(_args: argparse.Namespace) -> int:
    conn, client = _ready()
    _json(reindex.rebuild(conn, client, get_embedder()))
    return 0


def cmd_consolidate(args: argparse.Namespace) -> int:
    settings = get_settings()
    conn, client = _ready()
    scope_ids = [str(row["id"]) for row in conn.execute("SELECT id FROM entities")]
    outcome = consolidate.run(
        conn,
        scope_ids=scope_ids,
        stale_days=settings.consolidate_stale_days,
        demotion=settings.consolidate_demotion,
        importance_floor=settings.consolidate_importance_floor,
        dry_run=not args.apply,
        embedder=get_embedder(),
        client=client,
        consolidate_cosine=settings.consolidate_cosine,
        merge=bool(args.merge),
        merge_model=settings.judge_model,
        monthly_limit_usd=settings.monthly_cost_limit_usd,
        anthropic_api_key=settings.anthropic_api_key,
        gemini_api_key=settings.gemini_api_key,
        project=settings.vertex_project,
        location=settings.vertex_location,
    )
    if args.apply:
        outbox.drain(conn, client, get_embedder(), limit=500)
    _json(outcome.as_dict())
    return 0


def cmd_reextract_report(args: argparse.Namespace) -> int:
    conn = _db()
    owner = _resolve_user(conn, args.user)
    caller = principal_module.load(conn, str(owner["id"]))
    _json(reextract.dry_run_report(conn, scope_ids=caller.scopes()))
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    conn = _db()
    owner = _resolve_user(conn, args.user)
    caller = principal_module.load(conn, str(owner["id"]))
    result = privacy.export_user(
        conn,
        user_id=caller.user_id,
        export_dir=get_settings().export_dir,
        private_scope_id=caller.own_entity_id,
        authored_scopes=caller.scopes(),
    )
    _json(result)
    return 0


def cmd_erase(args: argparse.Namespace) -> int:
    if args.confirm != "ERASE":
        print("refusing: pass --confirm ERASE", file=sys.stderr)
        return 1
    conn, client = _ready()
    owner = _resolve_user(conn, args.user)
    caller = principal_module.load(conn, str(owner["id"]))
    try:
        result = privacy.erase_user(
            conn, client, user_id=caller.user_id, private_scope_id=caller.own_entity_id
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    _json(result)
    return 0


def cmd_backup(args: argparse.Namespace) -> int:
    settings = get_settings()
    if args.action == "create":
        _json(operations.create_backup(settings, kind=args.kind, protected=bool(args.protected)))
        return 0
    if args.action == "list":
        _json(operations.list_backups(settings))
        return 0
    if args.action == "verify":
        try:
            _json(operations.verify_backup(Path(args.path).expanduser()))
        except (FileNotFoundError, ValueError) as exc:
            raise SystemExit(str(exc)) from exc
        return 0
    if args.action == "prune":
        _json(operations.prune_backups(settings))
        return 0
    try:
        operations.restore_backup(settings, artifact_id=args.artifact_id or "", confirm="")
    except NotImplementedError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


# ---------------------------------------------------------------------------
# Integrations
# ---------------------------------------------------------------------------


def _hermes_source() -> Path:
    packaged = resources.files("memkit").joinpath("hermes_provider")
    if packaged.is_dir():
        return Path(str(packaged))
    return Path(__file__).resolve().parents[2] / "integrations" / "hermes" / "memkit"


def _configure_hermes(home: Path, settings: Any) -> None:
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
            "budget_tokens": int(plugin.get("budget_tokens", 800) or 800),
            "prefetch_timeout": float(plugin.get("prefetch_timeout", 0.4) or 0.4),
            "send_tool_results": False,
        }
    )
    config_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = config_path.with_suffix(".yaml.tmp")
    temporary.write_text(
        yaml.safe_dump(existing, default_flow_style=False, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    os.chmod(temporary, 0o600)
    temporary.replace(config_path)


def _install_hermes(
    *, hermes_home: str | None = None, force: bool = False, settings: Any | None = None
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
            hermes_home=args.hermes_home, force=args.force, settings=get_settings()
        )
    except (RuntimeError, FileExistsError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(target.resolve())
    return 0


def _claude_code_source() -> Path:
    packaged = resources.files("memkit").joinpath("claude_code_integration")
    if packaged.is_dir():
        return Path(str(packaged))
    return Path(__file__).resolve().parents[2] / "integrations" / "claude-code"


def cmd_install_claude_code(args: argparse.Namespace) -> int:
    source = _claude_code_source()
    if not source.is_dir():
        print("Claude Code integration is missing from this installation", file=sys.stderr)
        return 1
    claude_home = Path(args.claude_home or "~/.claude").expanduser()
    skills_home = Path(args.skills_home or claude_home / "skills").expanduser()
    skill_target = skills_home / "mem-os"
    hook_target = claude_home / "memkit" / "memkit_hooks.py"
    if (skill_target.exists() or hook_target.exists()) and not args.force:
        print(f"{skill_target} exists; pass --force to replace it", file=sys.stderr)
        return 1
    if skill_target.exists():
        shutil.rmtree(skill_target)
    skill_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        source / "skills" / "mem-os", skill_target, ignore=shutil.ignore_patterns("__pycache__")
    )
    hook_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source / "hooks" / "memkit_hooks.py", hook_target)

    settings = get_settings()
    # Pinned to this interpreter so the hook imports the same memkit that
    # classifies transcripts server-side; a mismatch there silently changes
    # what counts as a user turn.
    command = f"{sys.executable} {hook_target}"
    # SessionStart matchers are an exact string or a `|`-separated list of the
    # session sources, so `fork` has to be named too or a forked session starts
    # with no memory. PreCompact flushes the transcript tail before compaction
    # replaces it; its stdout cannot add context, which is why the profile is
    # re-injected through SessionStart's `compact` source instead.
    # UserPromptSubmit takes no matcher and fires on every prompt, so recall
    # does its own abstaining and stays off unless a repository opts in.
    snippet = {
        "hooks": {
            "SessionStart": [
                {
                    "matcher": "startup|resume|clear|compact|fork",
                    "hooks": [
                        {"type": "command", "command": f"{command} session-start", "timeout": 5}
                    ],
                }
            ],
            "UserPromptSubmit": [
                {"hooks": [{"type": "command", "command": f"{command} recall", "timeout": 5}]}
            ],
            "PreCompact": [
                {"hooks": [{"type": "command", "command": f"{command} capture", "timeout": 30}]}
            ],
            "Stop": [
                {"hooks": [{"type": "command", "command": f"{command} capture", "timeout": 30}]}
            ],
            "SessionEnd": [
                {"hooks": [{"type": "command", "command": f"{command} session-end", "timeout": 30}]}
            ],
        }
    }
    print(f"installed skill:  {skill_target}")
    print(f"installed hooks:  {hook_target}")
    print("\nadd this to ~/.claude/settings.json:\n")
    print(json.dumps(snippet, indent=2))
    print(
        f"\nthen create a key with `memkit api-keys create --user <handle>` and put it in\n"
        f"{DEFAULT_CONFIG_DIR / 'client.env'} as:\n"
        f"  MEMKIT_BASE_URL=http://{settings.host}:{settings.port}\n"
        f"  MEMKIT_API_KEY=<your key>\n"
        "\nfacts from a repository go to that person's own memory unless the repository\n"
        "says otherwise. To file them in a shared scope, add a .memkit.toml at its root:\n"
        "\n  [memkit]\n"
        '  entity = "<entity slug>"   # from `memkit entities list`\n'
        "  recall = false            # true asks memory a question on each prompt"
    )
    return 0


def cmd_eval(args: argparse.Namespace) -> int:
    repo_root = Path(__file__).resolve().parents[2]
    if not (repo_root / "eval").is_dir():
        print("the eval harness ships with the repository checkout only", file=sys.stderr)
        return 1
    sys.path.insert(0, str(repo_root))
    from eval.run import run_compare, run_eval

    result = (
        run_compare(limit=args.limit)
        if args.compare
        else run_eval(target=args.target, limit=args.limit)
    )
    _json(result)
    return 0


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(prog="memkit", description="team memory service")
    commands = parser.add_subparsers(dest="command", required=True)

    serve = commands.add_parser("serve", help="run the HTTP service")
    serve.add_argument("--reload", action="store_true")
    serve.set_defaults(func=cmd_serve)

    commands.add_parser("bench", help="measure embedding latency").set_defaults(func=cmd_bench)

    doctor = commands.add_parser("doctor", help="check every dependency")
    doctor.add_argument("--json", action="store_true")
    doctor.add_argument("--load-model", action="store_true")
    doctor.set_defaults(func=cmd_doctor)

    people = commands.add_parser("users", help="manage people").add_subparsers(
        dest="action", required=True
    )
    create_user = people.add_parser("create")
    create_user.add_argument("handle")
    create_user.add_argument("--name")
    create_user.add_argument("--email")
    create_user.add_argument("--password", help="prompted for when omitted")
    create_user.add_argument("--admin", action="store_true")
    create_user.set_defaults(func=cmd_users_create)
    people.add_parser("list").set_defaults(func=cmd_users_list)
    disable = people.add_parser("disable")
    disable.add_argument("handle")
    disable.add_argument("--enable", action="store_true", help="re-enable instead")
    disable.set_defaults(func=cmd_users_disable)

    keys = commands.add_parser("api-keys", help="manage agent credentials").add_subparsers(
        dest="action", required=True
    )
    create_key = keys.add_parser("create")
    create_key.add_argument("--user")
    create_key.add_argument("--name", default="cli")
    create_key.set_defaults(func=cmd_keys_create)
    revoke_key = keys.add_parser("revoke")
    revoke_key.add_argument("key_id")
    revoke_key.set_defaults(func=cmd_keys_revoke)

    ents = commands.add_parser("entities", help="manage shared scopes").add_subparsers(
        dest="action", required=True
    )
    create_entity = ents.add_parser("create")
    create_entity.add_argument("name")
    create_entity.add_argument(
        "--kind", default="project", choices=sorted(entities.CREATABLE_KINDS)
    )
    create_entity.add_argument("--slug")
    create_entity.add_argument("--description")
    create_entity.add_argument("--alias", action="append")
    create_entity.add_argument("--user")
    create_entity.set_defaults(func=cmd_entities_create)
    ents.add_parser("list").set_defaults(func=cmd_entities_list)
    member = ents.add_parser("member")
    member.add_argument("slug")
    member.add_argument("--user")
    member.add_argument("--role", default="member", choices=sorted(entities.MEMBER_ROLES))
    member.add_argument("--remove", action="store_true")
    member.set_defaults(func=cmd_entities_member)

    importer = commands.add_parser("import-claude-code", help="import transcripts as evidence")
    importer.add_argument("--root", default="~/.claude/projects")
    importer.add_argument("--user")
    importer.add_argument("--dry-run", action="store_true")
    importer.add_argument("--limit", type=int)
    importer.set_defaults(func=cmd_import)

    legacy = commands.add_parser("import-sqlite", help="import a single-owner v6 database")
    legacy.add_argument("path")
    legacy.add_argument("--user", help="the user who receives the imported memory")
    legacy.add_argument(
        "--pending", action="store_true", help="import memories unconfirmed rather than confirmed"
    )
    legacy.set_defaults(func=cmd_import_sqlite)

    drain = commands.add_parser("drain-index", help="deliver queued index updates")
    drain.add_argument("--limit", type=int, default=100)
    drain.add_argument("--retry-now", action="store_true")
    drain.set_defaults(func=cmd_drain)

    commands.add_parser("reindex", help="build and atomically activate a new index").set_defaults(
        func=cmd_reindex
    )

    compact = commands.add_parser("consolidate", help="plan conservative maintenance")
    compact.add_argument("--apply", action="store_true")
    compact.add_argument("--merge", action="store_true", help="LLM-confirmed semantic merge")
    compact.set_defaults(func=cmd_consolidate)

    report = commands.add_parser("reextract-report", help="cost a re-extraction without running it")
    report.add_argument("--user")
    report.set_defaults(func=cmd_reextract_report)

    export = commands.add_parser("export", help="export one user's data")
    export.add_argument("--user")
    export.set_defaults(func=cmd_export)

    erase = commands.add_parser("erase", help="erase one user's private data")
    erase.add_argument("--user")
    erase.add_argument("--confirm", default="")
    erase.set_defaults(func=cmd_erase)

    backup = commands.add_parser("backup", help="create, verify, or prune backups")
    backup_commands = backup.add_subparsers(dest="action", required=True)
    backup_create = backup_commands.add_parser("create")
    backup_create.add_argument("--kind", default="manual")
    backup_create.add_argument("--protected", action="store_true")
    backup_create.set_defaults(func=cmd_backup)
    backup_commands.add_parser("list").set_defaults(func=cmd_backup)
    backup_verify = backup_commands.add_parser("verify")
    backup_verify.add_argument("path")
    backup_verify.set_defaults(func=cmd_backup)
    backup_commands.add_parser("prune").set_defaults(func=cmd_backup)
    backup_restore = backup_commands.add_parser("restore")
    backup_restore.add_argument("artifact_id", nargs="?")
    backup_restore.set_defaults(func=cmd_backup)

    hermes = commands.add_parser("install-hermes", help="install the packaged Hermes adapter")
    hermes.add_argument("--hermes-home")
    hermes.add_argument("--force", action="store_true")
    hermes.set_defaults(func=cmd_install_hermes)

    claude_code = commands.add_parser(
        "install-claude-code", help="install the Claude Code skill and hooks"
    )
    claude_code.add_argument("--claude-home")
    claude_code.add_argument("--skills-home")
    claude_code.add_argument("--force", action="store_true")
    claude_code.set_defaults(func=cmd_install_claude_code)

    evaluate = commands.add_parser("eval", help="run the retrieval eval (repo checkout only)")
    evaluate.add_argument("--target", default="memories", choices=["raw", "memories"])
    evaluate.add_argument("--compare", action="store_true")
    evaluate.add_argument("--limit", type=int)
    evaluate.set_defaults(func=cmd_eval)

    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
