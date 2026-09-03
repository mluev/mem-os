#!/usr/bin/env python3
"""Claude Code hooks for Mem OS: profile injection and session capture.

Three subcommands, registered in ~/.claude/settings.json by
`memkit install-claude-code`:

    session-start   SessionStart: render the profile, print a <mem-os-context>
                    block (stdout of a SessionStart hook becomes context).
    capture         Stop: post the transcript delta since the last cursor as
                    one idempotent evidence batch.
    session-end     SessionEnd: capture the final delta, then close the
                    session so the extraction tail runs server-side.

Every path fails open: a dead or unconfigured service must never block the
user's session, so errors go to stderr and the exit code stays 0. Capture
advances its cursor only after the batch succeeds; `external_id` per turn (the
transcript line uuid — the same id `memkit import-claude-code` uses) makes any
re-send idempotent, so the hook and the bulk importer can coexist.

Transcript classification is imported from memkit itself — the installer pins
this script to the interpreter that has memkit installed — so the hook and the
importer can never disagree about what counts as a real turn.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path

CAPTURE_TIMEOUT = 10.0
PROFILE_TIMEOUT = 3.0
BATCH_LIMIT = 100
STATE_DIR = (
    Path(os.environ.get("XDG_STATE_HOME") or "~/.local/state").expanduser()
    / "memkit"
    / "claude-code"
)


CLIENT_ENV = Path("~/.config/memkit/client.env").expanduser()
LEGACY_ENV = Path("~/.memkit").expanduser()


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return values
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        values[name.strip()] = value.strip().strip("'\"")
    return values


def _config() -> tuple[str, str]:
    """Resolve the service URL and this user's key.

    Precedence: the environment, then ~/.config/memkit/client.env (written by
    `memkit setup`, beside the rest of the memkit config), then ~/.memkit.
    The legacy path is still read because installs predating client.env used it.
    Nothing is printed about it here -- a hook's contract is to stay silent and
    fail open, so `memkit doctor` reports the deprecation instead.
    """
    base = os.environ.get("MEMKIT_BASE_URL", "")
    key = os.environ.get("MEMKIT_API_KEY", "")
    if not base or not key:
        for path in (CLIENT_ENV, LEGACY_ENV):
            if not path.is_file():
                continue
            values = _read_env_file(path)
            base = base or values.get("MEMKIT_BASE_URL", "")
            key = key or values.get("MEMKIT_API_KEY", "")
            if base and key:
                break
    return (base or "http://127.0.0.1:8077").rstrip("/"), key


def _post(base: str, key: str, path: str, payload: dict | None, timeout: float) -> dict:
    request = urllib.request.Request(
        base + path,
        data=json.dumps(payload).encode() if payload is not None else b"",
        headers={"Content-Type": "application/json", "X-API-Key": key},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode() or "{}")


def _hook_input() -> dict:
    try:
        return json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return {}


def session_start() -> None:
    base, key = _config()
    if not key:
        return
    profile = _post(base, key, "/v1/profiles/render", {"budget_tokens": 600}, PROFILE_TIMEOUT)
    stable = profile.get("stable") or []
    dynamic = profile.get("dynamic") or []
    if not stable and not dynamic:
        return
    lines = [
        "<mem-os-context>",
        "Long-term memory about this user, loaded from Mem OS. Reference it",
        "naturally; for anything deeper, search with the mem-os skill.",
    ]
    if stable:
        lines.append("Profile:")
        lines.extend(f"- {item['text']}" for item in stable)
    if dynamic:
        lines.append("Recent context:")
        lines.extend(f"- {item['text']}" for item in dynamic)
    lines.append("</mem-os-context>")
    print("\n".join(lines))


def _events_from_delta(transcript: Path, cursor_file: Path, workspace: str) -> tuple[list, int]:
    from memkit.importers.claude_code import MAX_TURN_CHARS, classify

    offset = 0
    if cursor_file.is_file():
        try:
            offset = int(cursor_file.read_text().strip() or 0)
        except ValueError:
            offset = 0
    data = transcript.read_bytes()
    if offset > len(data):
        offset = 0  # transcript rewritten; idempotent ids make re-reads safe
    events = []
    for raw in data[offset:].splitlines():
        try:
            line = json.loads(raw)
        except ValueError:
            continue
        turn, _reason = classify(line)
        if turn is None:
            continue
        # classify() keeps full documents out already; assistant turns are
        # context only server-side, so cap them to keep batches small.
        text = turn.text if turn.role == "user" else turn.text[:2000]
        events.append(
            {
                "session_id": turn.session_id,
                "agent_id": "claude-code",
                "role": turn.role,
                "content": text[:MAX_TURN_CHARS],
                "external_source": "claude-code",
                "external_id": turn.external_id,
                "context": {"source_workspace": turn.project or workspace},
                **({"created_at": turn.created_at} if turn.created_at else {}),
            }
        )
    return events, len(data)


def capture(close: bool) -> None:
    hook = _hook_input()
    base, key = _config()
    transcript_path = hook.get("transcript_path") or ""
    session_id = hook.get("session_id") or ""
    if not key or not transcript_path or not session_id:
        return
    transcript = Path(transcript_path).expanduser()
    if not transcript.is_file():
        return
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    cursor_file = STATE_DIR / f"{session_id}.offset"
    workspace = Path(hook.get("cwd") or os.getcwd()).name
    events, new_offset = _events_from_delta(transcript, cursor_file, workspace)
    for start in range(0, len(events), BATCH_LIMIT):
        _post(
            base,
            key,
            "/v1/evidence/events:batch",
            {"events": events[start : start + BATCH_LIMIT]},
            CAPTURE_TIMEOUT,
        )
    # Only reached when every batch landed: a failed send keeps the old cursor
    # and the idempotency keys absorb the overlap on the next run.
    cursor_file.write_text(str(new_offset))
    if close and events:
        _post(base, key, f"/v1/sessions/{session_id}/close", None, CAPTURE_TIMEOUT)


def main() -> int:
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        if command == "session-start":
            session_start()
        elif command == "capture":
            capture(close=False)
        elif command == "session-end":
            capture(close=True)
        else:
            print(f"unknown memkit hook command: {command!r}", file=sys.stderr)
    except Exception as exc:  # fail open, always
        print(f"memkit hook {command} failed: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
