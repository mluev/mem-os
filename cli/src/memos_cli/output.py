"""Stable machine envelopes and readable terminal rendering."""

import json
import sys

from .client import protocol_error


def validate_rows(rows):
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise protocol_error()


def emit(value, fmt=None, *, error=False):
    machine = fmt == "json" or (fmt != "text" and not sys.stdout.isatty())
    payload = {"ok": False, "error": value} if error else {"ok": True, "data": value}
    if machine:
        print(json.dumps(payload, ensure_ascii=False, default=str))
    elif error:
        print(value["message"], file=sys.stderr)
    elif isinstance(value, dict) and "commands" in value:
        print("Everyday: remember, search, profile, forget, whoami, status")
        grouped = {}
        for item in [*value["commands"], *value.get("local_commands", [])]:
            group, _, action = item["command"].partition(" ")
            if action:
                grouped.setdefault(group, []).append(action)
        for group, actions in grouped.items():
            print(f"{group}: {', '.join(actions)}")
        print("Use memos <command> --help or memos schema <command> --json for arguments.")
    elif isinstance(value, dict) and "blocks" in value:
        if not isinstance(value["blocks"], dict):
            raise protocol_error()
        for rows in value["blocks"].values():
            validate_rows(rows)
            if any(not isinstance(row.get("text", ""), str) for row in rows):
                raise protocol_error()
        for name, rows in value["blocks"].items():
            if rows:
                print(name.replace("_", " ").capitalize() + ":")
                for row in rows:
                    print("  " + row.get("text", ""))
    elif isinstance(value, dict) and any(
        isinstance(value.get(k), list) for k in ("memories", "items")
    ):
        key = "memories" if isinstance(value.get("memories"), list) else "items"
        validate_rows(value[key])
        if not value[key]:
            print("No results.")
        for row in value[key]:
            label = " / ".join(
                str(row[field]) for field in ("scope", "review_status") if row.get(field)
            )
            print(
                f"{row.get('id', '')}  {row.get('text') or row.get('name') or json.dumps(row, ensure_ascii=False)}"
                + (f" [{label}]" if label else "")
            )
    else:
        print(json.dumps(value, ensure_ascii=False, indent=2, default=str))
