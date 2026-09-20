"""SSH orchestration only. No Docker or database processes run on the client."""

import getpass
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
from importlib.resources import files
from pathlib import Path

from . import config
from .client import protocol_error, validate_url
from .errors import ClientError
from .server_operations import OPERATIONS


def add_parser(leaf):
    commands = (
        "install",
        "start",
        "stop",
        "restart",
        "status",
        "logs",
        "doctor",
        "upgrade",
        "tunnel",
        "reindex",
        "drain-index",
        "consolidate",
        "reextract-report",
        "bench",
        "eval",
        "import-claude-code",
        "import-sqlite",
    )
    for action in commands:
        p = leaf(["server", action], help=f"{action} on the hosted server")
        p.set_defaults(handler="server", action=action)
        p.add_argument("--host", help="SSH host or user@host (defaults to saved target)")
        p.add_argument("--directory", help="managed directory on the server")
        if action in {"install", "upgrade"}:
            p.add_argument("--image", required=True, help="versioned image or digest; never latest")
            p.add_argument("--source", help="remote source checkout to build on the server")
        if action == "install":
            p.add_argument("--name", default="default")
            p.add_argument("--handle", default="admin")
            p.add_argument("--password-file")
            p.add_argument(
                "--provider-key-file", help="Gemini API key file on this client, sent over SSH"
            )
            p.add_argument("--local-port", type=int)
            p.add_argument("--remote-port", type=int)
        if action == "logs":
            p.add_argument("--limit", type=int, default=100)
        if action == "import-claude-code":
            p.add_argument("--apply", action="store_true")
        if action in {"import-sqlite", "import-claude-code"}:
            p.add_argument("--path", required=True, help="path on the server")
        operation_parser(p, action)
        if action == "tunnel":
            p.add_argument("--close", action="store_true")
    for action in ("create", "list", "verify", "prune", "download", "restore"):
        p = leaf(["server", "backup", action])
        p.set_defaults(handler="server", action="backup-" + action)
        p.add_argument("--host")
        p.add_argument("--directory")
        if action in {"verify", "download", "restore"}:
            p.add_argument("artifact_id")
        if action == "download":
            p.add_argument("--output", required=True)
        if action == "restore":
            p.add_argument("--confirm", help="RESTORE to acknowledge replacement of server data")
        operation_parser(p, "backup-" + action)


def operation_parser(parser, action):
    for name, option in OPERATIONS.get(action, {}).get("options", {}).items():
        arguments = dict(option)
        if arguments.get("type") == "int":
            arguments["type"] = int
        parser.add_argument("--" + name.replace("_", "-"), **arguments)


def host_check(host):
    if not host or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.@-]*", host):
        raise ClientError(
            "Supply an SSH host alias or user@host. Configure ports in ~/.ssh/config."
        )
    return host


def run_ssh(argv, **kwargs):
    try:
        return subprocess.run(argv, **kwargs)
    except subprocess.TimeoutExpired as exc:
        raise ClientError(
            "Remote operation timed out; check memos server status before retrying.",
            code="timeout",
            exit_code=8,
        ) from exc
    except OSError as exc:
        raise ClientError(
            "Cannot run SSH; check installation and host access.", code="remote_error", exit_code=7
        ) from exc


def ssh(host, command, *, input=None, timeout=1800):
    result = run_ssh(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", host_check(host), command],
        input=input,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode:
        raise ClientError(
            "SSH operation failed; check host access and memos server doctor.",
            code="remote_error",
            exit_code=7,
        )
    return result.stdout


def remote(server, payload):
    script = (
        files("memos_cli").joinpath("server_operations.py").read_text()
        + "\n"
        + files("memos_cli").joinpath("assets/server_worker.py").read_text()
    )
    content = json.dumps({**payload, "directory": server["directory"]})
    try:
        result = json.loads(ssh(server["host"], "python3 -c " + shlex.quote(script), input=content))
    except ValueError as exc:
        raise protocol_error() from exc
    if not isinstance(result, dict) or type(result.get("ok")) is not bool:
        raise protocol_error()
    if not result.get("ok"):
        if not isinstance(result.get("error"), str):
            raise protocol_error()
        raise ClientError(
            result.get("error", "Remote operation failed"),
            code="remote_error",
            exit_code=7,
            details=result.get("details"),
        )
    data = result.get("data")
    if payload["action"] == "backup-list":
        if not isinstance(data, list) or any(not isinstance(item, dict) for item in data):
            raise protocol_error()
    elif not isinstance(data, dict):
        raise protocol_error()
    return data


def tunnel_path(server):
    identifier = hashlib.sha256(json.dumps(server, sort_keys=True).encode()).hexdigest()[:16]
    directory = config.config_dir() / "ssh"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    return str(directory / identifier)


def ensure_tunnel(server, close=False):
    host = host_check(server["host"])
    control = tunnel_path(server)
    base = ["ssh", "-S", control, "-o", "BatchMode=yes", "-o", "ConnectTimeout=10"]
    if close:
        result = run_ssh([*base, "-O", "exit", host], capture_output=True, timeout=15)
        return {"closed": result.returncode == 0}
    checked = run_ssh([*base, "-O", "check", host], capture_output=True, timeout=15)
    if checked.returncode == 0:
        return {"open": True}
    port = int(server.get("local_port", 18077))
    remote_port = int(server.get("port", 8077))
    result = run_ssh(
        [
            *base,
            "-M",
            "-f",
            "-N",
            "-o",
            "ExitOnForwardFailure=yes",
            "-o",
            "ServerAliveInterval=30",
            "-o",
            "ServerAliveCountMax=3",
            "-L",
            f"127.0.0.1:{port}:127.0.0.1:{remote_port}",
            host,
        ],
        capture_output=True,
        timeout=20,
    )
    if result.returncode:
        raise ClientError(
            "Cannot open SSH tunnel; check SSH access and local port availability.",
            code="unavailable",
            exit_code=7,
        )
    return {"open": True, "local_port": port}


def dispatch(args, options):
    name = options.connection
    if args.action == "install":
        if name and args.name != "default" and name != args.name:
            raise ClientError("--connection and --name must identify the same connection")
        args.name = name or args.name
        name = args.name if args.name in config.load()["connections"] else name
    saved = config.resolve(name, options.url)
    server = dict(saved.get("server", {}))
    if args.host:
        server["host"] = host_check(args.host)
    if args.directory:
        server["directory"] = args.directory
    server.setdefault("directory", ".local/share/memos/server")
    if not server.get("host"):
        raise ClientError(
            "No managed server configured; use memos server install --host HOST --image IMAGE:VERSION."
        )
    if args.action == "tunnel":
        return ensure_tunnel(server, args.close)
    if hasattr(args, "limit") and args.limit < 1:
        raise ClientError("--limit must be a positive integer")
    payload = {
        k: v
        for k, v in vars(args).items()
        if k not in {"handler", "output", "password_file", "provider_key_file"}
        and not k.startswith("command_")
        and v is not None
    }
    if args.action == "install":
        from .cli import read_value

        password = (
            read_value("-" if args.password_file == "-" else "@" + args.password_file).strip()
            if args.password_file
            else (
                getpass.getpass("Initial administrator password: ") if sys.stdin.isatty() else None
            )
        )
        if not password or len(password) < 12:
            raise ClientError(
                "Provide a password of at least 12 characters with --password-file (or interactively)."
            )
        previous = config.load()["connections"].get(args.name, {})
        previous_server = previous.get("server", {})
        same_target = bool(previous_server) and all(
            previous_server.get(k) == server.get(k) for k in ("host", "directory")
        )
        if (
            same_target
            and args.remote_port is not None
            and args.remote_port != previous_server.get("port", 8077)
        ):
            raise ClientError("--remote-port conflicts with the installed deployment")
        if same_target and options.url and validate_url(options.url) != previous.get("url"):
            raise ClientError(
                "--url conflicts with the installed connection; use a separate connection name"
            )
        local_port = (
            args.local_port
            if args.local_port is not None
            else (previous_server.get("local_port", 18077) if same_target else 18077)
        )
        remote_port = (
            args.remote_port
            if args.remote_port is not None
            else (previous_server.get("port", 8077) if same_target else 8077)
        )
        if not 1 <= local_port <= 65535 or not 1 <= remote_port <= 65535:
            raise ClientError("Ports must be between 1 and 65535")
        tunnel = previous_server.get("tunnel", True) if same_target else not bool(options.url)
        next_url = (
            (previous.get("url") if same_target and not tunnel else None)
            or options.url
            or f"http://127.0.0.1:{local_port}"
        )
        validate_url(next_url)
        payload["password"] = password
        provider = (
            Path(args.provider_key_file).expanduser().read_text().strip()
            if args.provider_key_file
            else os.environ.get("GEMINI_API_KEY", "")
        )
        if not provider and sys.stdin.isatty():
            provider = getpass.getpass(
                "Server Gemini API key (empty disables automatic extraction): "
            )
        payload["provider_key"] = provider
        payload["https"] = next_url.startswith("https://")
        if same_target or args.remote_port is not None:
            payload["remote_port"] = remote_port
        server.update(port=remote_port, local_port=local_port, tunnel=tunnel)
    if args.action == "backup-restore" and args.confirm != "RESTORE":
        raise ClientError("Restore replaces server data; pass --confirm RESTORE.")
    result = remote(server, payload)
    if args.action == "install":
        data = config.load()
        if not same_target:
            previous = {}
        if "port" in result:
            if type(result["port"]) is not int or not 1 <= result["port"] <= 65535:
                raise protocol_error()
            server["port"] = result["port"]
        entry = {
            **previous,
            "url": next_url,
            "server": server,
        }
        secret = result.pop("key", None)
        if secret:
            entry["key"] = secret
        if result.get("key_id"):
            entry["key_id"] = result.pop("key_id")
        data["connections"][args.name] = entry
        data["default"] = args.name
        config.save(data)
        if server["tunnel"]:
            ensure_tunnel(server)
        result["connection"] = args.name
        result["url"] = entry["url"]
        result["next"] = (
            "memos agents install; memos status"
            if entry.get("key")
            else "memos setup to log in to this existing deployment"
        )
    if args.action == "backup-download":
        # A separate SSH stream prevents buffering an entire database backup.
        target = Path(args.output).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        import tempfile

        fd, temporary = tempfile.mkstemp(prefix=".memos-backup-", dir=target.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                command = "cat -- " + shlex.quote(result["path"])
                process = run_ssh(
                    [
                        "ssh",
                        "-o",
                        "BatchMode=yes",
                        "-o",
                        "ConnectTimeout=10",
                        host_check(server["host"]),
                        command,
                    ],
                    stdout=stream,
                    stderr=subprocess.PIPE,
                    timeout=1800,
                )
            if process.returncode:
                raise ClientError("Backup download failed", code="remote_error", exit_code=7)
            digest = hashlib.sha256()
            with open(temporary, "rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            if digest.hexdigest() != result["sha256"]:
                raise ClientError("Backup checksum mismatch", code="remote_error", exit_code=7)
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return {"path": str(target.resolve()), "sha256": result["sha256"]}
    return result
