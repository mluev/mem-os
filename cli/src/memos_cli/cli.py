"""Human-friendly commands and complete, discoverable API access."""

import getpass
import math
import socket
import sys

from . import __version__, config, registry
from .api_commands import execute
from .arguments import (
    globals_parser,
    local_schemas,
    parser_tree,
    read_value,
    referenced_definitions,
    split_globals,
)
from .client import Client, protocol_error
from .connection import open_connection
from .errors import ClientError
from .output import emit


def connect(options, *, authenticated=True):
    saved = config.resolve(options.connection, options.url)
    return open_connection(
        saved, timeout=options.timeout, authenticated=authenticated, factory=Client
    )


def setup(args, options):
    data = config.load()
    selected = options.connection or (args.name if args.name in data["connections"] else None)
    previous = config.resolve(selected)
    interactive = sys.stdin.isatty()
    url = options.url or previous.get("url")
    if not url and interactive:
        url = input("Hosted Mem OS URL: ").strip()
    key = (
        read_value("-" if args.api_key_file == "-" else "@" + args.api_key_file).strip()
        if args.api_key_file
        else (previous.get("key") if url == previous.get("url") else None)
    )
    connection = {**previous, "url": url, "key": key}
    if url != previous.get("url"):
        connection.pop("server", None)
    client = open_connection(
        connection, timeout=options.timeout, authenticated=bool(key), factory=Client
    )
    minted_id = None
    try:
        if not key or args.handle or args.password_file:
            handle = args.handle or (input("Your handle: ").strip() if interactive else None)
            password = (
                read_value("-" if args.password_file == "-" else "@" + args.password_file).strip()
                if args.password_file
                else (getpass.getpass("Password: ") if interactive else None)
            )
            if not handle or not password:
                raise ClientError(
                    "Provide --api-key-file, or --handle and --password-file for noninteractive setup."
                )
            client.http.headers.pop("X-API-Key", None)
            client.post("/v1/auth/login", {"handle": handle, "password": password})
            try:
                minted = client.post("/v1/api-keys", {"name": f"memos-{socket.gethostname()}"})
                if any(
                    not isinstance(minted.get(name), str) or not minted[name]
                    for name in ("secret", "id")
                ):
                    raise protocol_error()
                key, minted_id = minted["secret"], minted["id"]
            finally:
                try:
                    client.post("/v1/auth/logout")
                finally:
                    client.http.cookies.clear()
            client.key = key
            client.http.headers["X-API-Key"] = key
        identity = client.get("/v1/auth/me")
        data = config.load()
        existing = data["connections"].get(args.name, {})
        if existing.get("url") != client.url:
            existing = {}
        data["connections"][args.name] = {
            **existing,
            "url": client.url,
            "key": key,
            "key_id": minted_id or (existing.get("key_id") if existing.get("key") == key else None),
        }
        data["default"] = args.name
        config.save(data)
        result = {"connection": args.name, "url": client.url, "identity": identity}
        if args.agents is not None:
            from .agents import install

            result["agents"] = install(args.agents or ["claude", "hermes", "codex"])
        elif interactive:
            from .agents import detected, install

            available = detected()
            if (
                available
                and input(f"Configure memory for {', '.join(available)}? [Y/n] ").strip().lower()
                != "n"
            ):
                result["agents"] = install(available)
        return result
    finally:
        client.close()


def api(args, options):
    return execute(
        args,
        options,
        connect=connect,
        public_connect=lambda opts: connect(opts, authenticated=False),
    )


def dispatch(args, options):
    if args.handler == "api":
        return api(args, options)
    if args.handler == "setup":
        return setup(args, options)
    if args.handler == "commands":
        document = registry.spec()
        return {
            "version": __version__,
            "commands": [
                registry.operation(cmd, document) for cmd in [*registry.ROUTES, *registry.ALIASES]
            ],
            "local_commands": [
                value for key, value in local_schemas().items() if not key.startswith("internal ")
            ],
        }
    if args.handler == "schema":
        command = " ".join(args.name)
        if command not in registry.ROUTES and command not in registry.ALIASES:
            if command in local_schemas():
                return local_schemas()[command]
            raise ClientError("Unknown command; use memos commands.")
        document = registry.spec()
        operation = registry.operation(command, document)
        return {
            **operation,
            "definitions": referenced_definitions(operation, document),
        }
    if args.handler == "connections":
        data = config.load()
        if args.action == "list":
            return {
                "default": data["default"],
                "connections": {
                    k: config.redact_connection(v) for k, v in data["connections"].items()
                },
            }
        if args.name not in data["connections"]:
            raise ClientError("Unknown connection")
        if args.action == "use":
            data["default"] = args.name
        else:
            del data["connections"][args.name]
            if data["default"] == args.name:
                data["default"] = None
        config.save(data)
        return {"default": data["default"]}
    if args.handler == "status":
        client = connect(options)
        try:
            return {
                "url": client.url,
                "identity": client.get("/v1/auth/me"),
                "readiness": client.get("/readyz"),
            }
        finally:
            client.close()
    if args.handler == "agents":
        from .agents import dispatch as agents_dispatch

        return agents_dispatch(args, options)
    if args.handler == "server":
        from .server import dispatch as server_dispatch

        return server_dispatch(args, options)
    raise ClientError("Unknown command")


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    fmt = "json" if "--json" in argv else None
    try:
        global_args, command_args = split_globals(argv)
        options = globals_parser().parse_args(global_args)
        fmt = options.format
        if not math.isfinite(options.timeout) or options.timeout <= 0 or options.timeout > 300:
            raise ClientError("--timeout must be greater than zero and at most 300 seconds")
        args = parser_tree().parse_args(command_args)
        emit(dispatch(args, options), fmt)
        return 0
    except ClientError as exc:
        emit(exc.payload(), fmt, error=True)
        return exc.exit_code
    except (ValueError, OSError, KeyError) as exc:
        emit(
            {
                "code": "invalid_input",
                "message": f"{type(exc).__name__}: check command input or configuration",
                "status": None,
            },
            fmt,
            error=True,
        )
        return 2
    except KeyboardInterrupt:
        emit({"code": "interrupted", "message": "Interrupted", "status": None}, fmt, error=True)
        return 130
