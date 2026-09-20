"""Install owned integration files; merge settings without replacing user configuration."""

import json
import os
import shlex
import shutil
import sys
import time
from importlib.resources import files
from pathlib import Path

import yaml

from . import config
from .errors import ClientError


def add_parser(leaf):
    p = leaf(["agents", "install"], help="configure agent memory automatically")
    p.set_defaults(handler="agents", action="install")
    p.add_argument("targets", nargs="*", choices=["claude", "hermes", "codex"])
    p.add_argument("--skills-dir", help="custom directory containing skill folders")
    p.add_argument("--home", help="alternate agent configuration root (one target only)")
    p = leaf(["agents", "status"], help="check adapter installation and connection")
    p.set_defaults(handler="agents", action="status")
    p = leaf(["internal", "request"], help=__import__("argparse").SUPPRESS)
    p.set_defaults(handler="agents", action="request")
    p.add_argument("--input", default="-")
    p = leaf(["internal", "hook"], help=__import__("argparse").SUPPRESS)
    p.set_defaults(handler="agents", action="hook")
    p.add_argument("event", choices=["session-start", "recall", "capture", "session-end"])


def root(target):
    if target == "hermes":
        return Path(os.environ.get("HERMES_HOME", "~/.hermes")).expanduser()
    if target == "codex":
        return Path(os.environ.get("CODEX_HOME", "~/.codex")).expanduser()
    return Path.home() / ".claude"


def detected():
    return [name for name in ("claude", "hermes", "codex") if root(name).is_dir()]


def replace_owned(path, text):
    path = Path(path)
    if path.exists() and path.read_text() == text:
        return
    if path.exists():
        backup = path.with_name(path.name + f".before-memos-{time.time_ns()}")
        shutil.copy2(path, backup)
        os.chmod(backup, 0o600)
    config.private_write(path, text)


def agent_settings(directory, target):
    """Validate user-owned settings before replacing any integration files."""
    path = directory / ("settings.json" if target == "claude" else "config.yaml")
    try:
        settings = (
            (
                json.loads(path.read_text())
                if target == "claude"
                else yaml.safe_load(path.read_text())
            )
            if path.exists()
            else {}
        )
    except (ValueError, OSError, yaml.YAMLError) as exc:
        raise ClientError(
            f"Cannot read {target} settings at {path}; repair them before installing."
        ) from exc
    if settings is None and target == "hermes":
        settings = {}
    valid = isinstance(settings, dict)
    if valid and target == "claude":
        hooks = settings.get("hooks", {})
        valid = isinstance(hooks, dict) and all(
            isinstance(entries, list)
            and all(
                isinstance(entry, dict)
                and isinstance(entry.get("hooks"), list)
                and all(
                    isinstance(hook, dict) and isinstance(hook.get("command", ""), str)
                    for hook in entry["hooks"]
                )
                for entry in entries
            )
            for entries in hooks.values()
        )
    elif valid:
        valid = isinstance(settings.get("memory", {}), dict) and isinstance(
            settings.get("plugins", {}), dict
        )
        if valid:
            valid = isinstance(settings.get("plugins", {}).get("memkit", {}), dict)
    if not valid:
        raise ClientError(
            f"Invalid {target} settings structure at {path}; repair it before installing."
        )
    return settings


def install(targets, skills_dir=None, home=None):
    if home and len(targets) != 1:
        raise ClientError("--home requires exactly one agent target")
    skill = files("memos_cli").joinpath("assets/SKILL.md").read_text()
    result = []
    command = shlex.join([sys.executable, "-m", "memos_cli"])
    if skills_dir:
        replace_owned(Path(skills_dir).expanduser() / "mem-os/SKILL.md", skill)
        result.append({"target": "custom", "skill": str(Path(skills_dir).expanduser())})
    for target in targets:
        directory = Path(home).expanduser() if home else root(target)
        settings = agent_settings(directory, target) if target in {"claude", "hermes"} else {}
        replace_owned(directory / "skills/mem-os/SKILL.md", skill)
        if target == "claude":
            path = directory / "settings.json"
            hooks = settings.setdefault("hooks", {})
            for event, action, timeout in (
                ("SessionStart", "session-start", 5),
                ("UserPromptSubmit", "recall", 5),
                ("Stop", "capture", 30),
                ("PreCompact", "capture", 30),
                ("SessionEnd", "session-end", 30),
            ):
                remaining = []
                for entry in hooks.get(event, []):
                    kept = [
                        hook
                        for hook in entry.get("hooks", [])
                        if not any(
                            marker in hook.get("command", "")
                            for marker in ("memkit_hooks.py", "memos_cli internal hook")
                        )
                    ]
                    if kept:
                        remaining.append({**entry, "hooks": kept})
                entry = {
                    "hooks": [
                        {
                            "type": "command",
                            "command": f"{command} internal hook {action}",
                            "timeout": timeout,
                        }
                    ]
                }
                if event == "SessionStart":
                    entry["matcher"] = "startup|resume|clear|compact|fork"
                hooks[event] = [*remaining, entry]
            replace_owned(path, json.dumps(settings, indent=2) + "\n")
        elif target == "hermes":
            plugin = directory / "plugins/memkit"
            for filename in ("__init__.py", "client.py", "scrub.py", "plugin.yaml"):
                replace_owned(
                    plugin / filename,
                    files("memos_cli").joinpath("assets/hermes", filename).read_text(),
                )
            replace_owned(
                plugin / "bridge.json",
                json.dumps({"command": [sys.executable, "-m", "memos_cli"]}) + "\n",
            )
            path = directory / "config.yaml"
            settings.setdefault("memory", {})["provider"] = "memkit"
            plugin_settings = settings.setdefault("plugins", {}).setdefault("memkit", {})
            # Credentials belong to the CLI; stale plugin keys must not select a
            # different identity or prevent the provider from initializing.
            for key in ("api_key_file", "api_key_env", "base_url"):
                plugin_settings.pop(key, None)
            plugin_settings["send_tool_results"] = False
            replace_owned(path, yaml.safe_dump(settings, sort_keys=False, allow_unicode=True))
        result.append({"target": target, "path": str(directory), "automatic": target != "codex"})
    return result


def dispatch(args, options):
    if args.action == "install":
        targets = args.targets or ([] if args.skills_dir else detected())
        if not targets and not args.skills_dir:
            raise ClientError("No agents found; name claude, hermes, codex, or --skills-dir.")
        return {"installed": install(targets, args.skills_dir, args.home)}
    if args.action == "request":
        from .cli import connect, read_value

        payload = json.loads(read_value(args.input))
        if (
            not isinstance(payload, dict)
            or not isinstance(payload.get("method"), str)
            or not isinstance(payload.get("path"), str)
        ):
            raise ClientError("Request input requires method and path strings")
        if payload.get("params") is not None and not isinstance(payload["params"], dict):
            raise ClientError("Request params must be a JSON object")
        client = connect(options)
        try:
            return client.request(
                payload["method"], payload["path"], payload.get("body"), payload.get("params")
            )
        finally:
            client.close()
    if args.action == "hook":
        # Hook stdout is an agent-specific protocol, not a CLI envelope.
        try:
            from . import claude_hooks

            sys.argv = ["memos-hook", args.event]
            code = claude_hooks.main()
        except Exception:
            print("Mem OS hook unavailable; continuing without memory.", file=sys.stderr)
            code = 0
        raise SystemExit(code)
    result = []
    for target in ("claude", "hermes", "codex"):
        directory = root(target)
        item = {"target": target, "skill": (directory / "skills/mem-os/SKILL.md").is_file()}
        if target == "claude":
            settings = agent_settings(directory, target)
            item["hooks"] = [
                event
                for event, hooks in settings.get("hooks", {}).items()
                if "memos_cli internal hook" in json.dumps(hooks)
            ]
            item["disabled"] = bool(settings.get("disableAllHooks"))
        elif target == "hermes":
            item["bridge"] = (directory / "plugins/memkit/bridge.json").is_file()
        result.append(item)
    from .cli import connect

    try:
        client = connect(options)
        try:
            client.get("/v1/auth/me")
            client.get("/readyz")
            connection = {"ok": True}
        finally:
            client.close()
    except ClientError as exc:
        connection = {"ok": False, "error": exc.payload()}
    return {"agents": result, "connection": connection}
