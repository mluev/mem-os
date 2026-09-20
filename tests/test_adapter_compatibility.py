"""An upgraded legacy installation still captures without the memos runtime."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from memkit import cli


def test_reinstalled_legacy_hook_keeps_cursor_credentials_and_default(tmp_path, monkeypatch):
    source = Path(__file__).resolve().parents[1] / "src"
    home, state = tmp_path / "claude", tmp_path / "state"
    transcript = tmp_path / "session.jsonl"
    seen = []

    def turn(identifier, text):
        return (
            json.dumps(
                {
                    "uuid": identifier,
                    "sessionId": "session",
                    "type": "user",
                    "message": {"content": text},
                }
            )
            + "\n"
        )

    old = turn("old", "I prefer pnpm for every project")
    transcript.write_text(old + turn("new", "I now use uv for Python projects"))
    cursor = state / "memkit/claude-code/session.offset"
    cursor.parent.mkdir(parents=True)
    cursor.write_text(str(len(old.encode())))
    monkeypatch.setenv("XDG_STATE_HOME", str(state))
    args = argparse.Namespace(claude_home=str(home), skills_home=None, force=False)
    assert cli.cmd_install_claude_code(args) == 0
    args.force = True
    assert cli.cmd_install_claude_code(args) == 0

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.respond()

        def do_POST(self):
            self.respond()

        def respond(self):
            raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            seen.append(
                (self.path, self.headers.get("X-API-Key"), json.loads(raw) if raw else None)
            )
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"items":[],"count":1,"status":"queued"}')

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    environment = {
        **os.environ,
        "PYTHONPATH": str(source),
        "MEMKIT_BASE_URL": f"http://127.0.0.1:{server.server_port}",
        "MEMKIT_API_KEY": "legacy-key",
        "MEMKIT_RECALL": "0",
    }
    hook = home / "memkit/memkit_hooks.py"
    payload = json.dumps(
        {"session_id": "session", "cwd": str(tmp_path), "transcript_path": str(transcript)}
    )
    try:
        # -S excludes installed third-party packages, including memos_cli.
        result = subprocess.run(  # noqa: S603 -- installed hook, fixed interpreter, no shell
            [sys.executable, "-S", str(hook), "session-end"],
            input=payload,
            text=True,
            capture_output=True,
            env=environment,
            check=True,
        )
        assert result.stderr == ""
        writes = [body for path, _, body in seen if path == "/v1/evidence/events:batch"]
        assert [event["external_id"] for body in writes for event in body["events"]] == ["new"]
        assert seen[-1][0] == "/v1/sessions/session/close"
        assert all(key == "legacy-key" for _, key, _ in seen)
        assert cursor.read_text() == str(transcript.stat().st_size)
        seen.clear()
        subprocess.run(  # noqa: S603 -- installed hook, fixed interpreter, no shell
            [sys.executable, "-S", str(hook), "recall"],
            input=json.dumps({"cwd": str(tmp_path), "prompt": "What did we decide last time?"}),
            text=True,
            capture_output=True,
            env=environment,
            check=True,
        )
        assert seen == [], "legacy recall must remain opt-in after reinstall"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
