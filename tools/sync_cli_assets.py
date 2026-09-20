"""Build/check standalone CLI snapshots from canonical API and adapter sources.

Snapshots let the tiny wheel ship independently without importing the server.
Transport is replaced by the shared CLI client; classifier behavior stays exact.
"""

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "cli/src/memos_cli"


def replace_exact(source, before, after, *, count=1):
    found = source.count(before)
    if found != count:
        raise RuntimeError(
            f"CLI snapshot source changed: expected {count} occurrences of {before!r}, found {found}"
        )
    return source.replace(before, after)


def boundary(source, marker, start=0):
    if source.count(marker) != 1:
        raise RuntimeError(f"CLI snapshot source changed: expected one boundary {marker!r}")
    try:
        return source.index(marker, start)
    except ValueError as exc:
        raise RuntimeError(f"CLI snapshot source changed: misplaced boundary {marker!r}") from exc


def outputs():
    yield TARGET / "openapi.json", (ROOT / "openapi.json").read_text()
    importer = (ROOT / "src/memkit/importers/claude_code.py").read_text()
    importer = replace_exact(
        importer, "from ..limits import MIN_INDEX_CHARS", "MIN_INDEX_CHARS = 20"
    )
    yield TARGET / "claude_classifier.py", importer
    hooks = (ROOT / "integrations/claude-code/hooks/memkit_hooks.py").read_text()
    hooks = replace_exact(
        hooks, "from memkit import remote", "from . import agent_remote as remote"
    )
    hooks = replace_exact(hooks, '/ "claude-code"', '/ "claude-code"\n    / remote.namespace()')
    hooks = replace_exact(hooks, 'section.get("recall", False)', 'section.get("recall", True)')
    start = boundary(hooks, "def events_from_delta(")
    end = boundary(hooks, "def capture(", start)
    hooks = hooks[:start] + "from .capture import events_from_delta\n\n\n" + hooks[end:]
    start = boundary(hooks, "def _flush(")
    end = boundary(hooks, "def _send(", start)
    hooks = (
        hooks[:start]
        + """def _flush(client, transcript, session_id, repo, workspace):
    from .config import private_write
    cursor_file = STATE_DIR / f"{_state_key(session_id)}.offset"
    scope = resolve_scope(repo, entity_cache(client, session_id))
    deadline = time.monotonic() + CAPTURE_TIMEOUT
    while time.monotonic() < deadline:
        previous = int(cursor_file.read_text()) if cursor_file.exists() else 0
        events, offset = events_from_delta(transcript, cursor_file, workspace, scope)
        if events:
            _send(client, events, timeout=max(.1, deadline - time.monotonic()))
        private_write(cursor_file, str(offset))
        if offset == previous or offset >= transcript.stat().st_size:
            break


"""
        + hooks[end:]
    )
    hooks = replace_exact(hooks, "timeout=CAPTURE_TIMEOUT)", "timeout=timeout)", count=3)
    hooks = replace_exact(
        hooks,
        "def _send(client: Any, events: list[dict[str, Any]]) -> None:",
        "def _send(client: Any, events: list[dict[str, Any]], *, timeout=CAPTURE_TIMEOUT) -> None:",
    )
    # Keep capture's default budget; only _send receives the remaining budget.
    hooks = replace_exact(
        hooks, "client = _client(timeout=timeout)", "client = _client(timeout=CAPTURE_TIMEOUT)"
    )
    yield TARGET / "claude_hooks.py", hooks
    hermes = ROOT / "integrations/hermes/memkit"
    for name in ("__init__.py", "scrub.py"):
        yield TARGET / "assets/hermes" / name, (hermes / name).read_text()
    yield TARGET / "scrub.py", (hermes / "scrub.py").read_text()
    yield (
        TARGET / "assets/hermes/plugin.yaml",
        'name: memkit\nversion: 0.2.0\ndescription: "Hosted Mem OS through the lightweight memos CLI"\nhooks: [on_session_end, on_session_switch, on_memory_write]\n',
    )
    client = (hermes / "client.py").read_text()
    start = boundary(client, "    def _request(")
    end = boundary(client, "    # -- endpoints", start)
    client = (
        client[:start]
        + """    def _request(self, method, path, body=None, *, timeout=None):
        import subprocess
        if not self.breaker.allow():
            raise MemkitError("circuit open")
        seconds = timeout or self.timeout
        command = json.loads(Path(__file__).with_name("bridge.json").read_text())["command"]
        try:
            process = subprocess.run(
                [*command, "internal", "request", "--json", "--timeout", str(seconds)],
                input=json.dumps({"method": method, "path": path, "body": body}),
                text=True, capture_output=True, timeout=seconds + 1,
            )
            result = json.loads(process.stdout)
            if not result.get("ok"):
                error = result.get("error", {})
                if error.get("status", 0) is None or (error.get("status") or 0) >= 500:
                    self.breaker.fail()
                raise MemkitError(error.get("message", "Mem OS unavailable"), status=error.get("status"))
            self.breaker.ok()
            return result["data"]
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            self.breaker.fail()
            raise MemkitError("Mem OS CLI unavailable") from exc

"""
        + client[end:]
    )
    start = boundary(client, "def resolve_config()")
    end = boundary(client, "\n\nclass Breaker:", start)
    client = (
        client[:start]
        + """def resolve_config():
    # The CLI resolves the actual connection and credentials for every call.
    return "https://memos-managed.invalid", "memos-managed-identity"
"""
        + client[end:]
    )
    yield TARGET / "assets/hermes/client.py", client


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    mismatches = []
    for path, content in list(outputs()):
        if args.check:
            if not path.exists() or path.read_text() != content:
                mismatches.append(str(path.relative_to(ROOT)))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
    if mismatches:
        raise SystemExit("CLI assets need regeneration: " + ", ".join(mismatches))


if __name__ == "__main__":
    main()
