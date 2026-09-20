"""Saved connections and repository binding, with no server configuration imports."""

import json
import os
import tempfile
import tomllib
from pathlib import Path

from .errors import ClientError


def config_dir():
    return Path(os.environ.get("MEMOS_CONFIG_DIR", "~/.config/memkit")).expanduser()


def private_write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=".memos-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(value)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load():
    path = config_dir() / "connections.json"
    if not path.exists():
        return {"default": None, "connections": {}}
    try:
        return validate(json.loads(path.read_text()))
    except (ValueError, OSError) as exc:
        raise ClientError("Cannot read connections.json; repair it or run memos setup.") from exc


def validate(data):
    """Reject malformed saved state before any network or configuration mutation."""
    message = "Invalid connections.json structure; repair the saved connection configuration."
    if not isinstance(data, dict) or not isinstance(data.get("connections"), dict):
        raise ClientError(message)
    if data.get("default") is not None and not isinstance(data["default"], str):
        raise ClientError(message)
    for name, entry in data["connections"].items():
        if not name or not isinstance(entry, dict):
            raise ClientError(message)
        for key in ("url", "key", "key_id"):
            if entry.get(key) is not None and not isinstance(entry[key], str):
                raise ClientError(message)
        if "server" in entry:
            server = entry["server"]
            if not isinstance(server, dict):
                raise ClientError(message)
            for key in ("host", "directory"):
                if not isinstance(server.get(key), str) or not server[key]:
                    raise ClientError(message)
            for key in ("port", "local_port"):
                if key in server and (
                    type(server[key]) is not int or not 1 <= server[key] <= 65535
                ):
                    raise ClientError(message)
            if "tunnel" in server and not isinstance(server["tunnel"], bool):
                raise ClientError(message)
    return {**data, "default": data.get("default")}


def save(data):
    private_write(config_dir() / "connections.json", json.dumps(validate(data), indent=2) + "\n")


def repository(cwd=None):
    start = Path(cwd or os.getcwd()).resolve()
    for directory in (start, *start.parents):
        path = directory / ".memkit.toml"
        if path.exists():
            try:
                section = tomllib.loads(path.read_text()).get("memkit", {})
            except (ValueError, OSError) as exc:
                raise ClientError("Cannot read repository .memkit.toml configuration.") from exc
            if not isinstance(section, dict) or any(
                key in section and not isinstance(section[key], kind)
                for key, kind in (
                    ("connection", str),
                    ("entity", str),
                    ("capture", bool),
                    ("recall", bool),
                )
            ):
                raise ClientError("Invalid [memkit] configuration in .memkit.toml.")
            return section
        if (directory / ".git").exists():
            break
    return {}


def legacy():
    result = {}
    for path in (config_dir() / "client.env", Path.home() / ".memkit"):
        if not path.is_file():
            continue
        for raw in path.read_text().splitlines():
            if raw.strip().startswith("#") or "=" not in raw:
                continue
            key, _, value = raw.partition("=")
            result.setdefault(key.strip(), value.strip().strip("\"'"))
    return result


def resolve(name=None, url=None, key=None):
    data, repo = load(), repository()
    selected = (
        name or os.environ.get("MEMOS_CONNECTION") or repo.get("connection") or data.get("default")
    )
    if selected and selected not in data["connections"]:
        raise ClientError(f"Unknown connection {selected!r}; use memos connections list.")
    saved = dict(data["connections"].get(selected, {}))
    old = legacy() if not selected else {}
    saved.update(
        name=selected,
        url=url
        or os.environ.get("MEMOS_URL")
        or os.environ.get("MEMKIT_BASE_URL")
        or saved.get("url")
        or old.get("MEMKIT_BASE_URL"),
        key=key
        or os.environ.get("MEMOS_API_KEY")
        or os.environ.get("MEMKIT_API_KEY")
        or saved.get("key")
        or old.get("MEMKIT_API_KEY"),
    )
    return saved


def redact_connection(value):
    return {k: v for k, v in value.items() if k not in {"key", "password"}}
