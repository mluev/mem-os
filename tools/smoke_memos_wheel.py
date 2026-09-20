"""Run using a clean interpreter with only the standalone CLI installed."""

# ruff: noqa: S101 -- this executable is a packaging acceptance test

import importlib.metadata
import json
import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from memos_cli import config
from memos_cli.agents import install
from memos_cli.cli import parser_tree

parser_tree()
for forbidden in ("memkit", "torch", "sentence_transformers", "psycopg", "qdrant_client"):
    assert forbidden not in sys.modules, forbidden
installed = {
    d.metadata["Name"].lower().replace("_", "-") for d in importlib.metadata.distributions()
}
assert not installed.intersection(
    {"memkit", "torch", "sentence-transformers", "psycopg", "qdrant-client"}
)
result = subprocess.run(
    [sys.executable, "-m", "memos_cli", "commands", "--json"],
    capture_output=True,
    text=True,
    check=True,
)
assert json.loads(result.stdout)["ok"]
with TemporaryDirectory() as directory:
    root = Path(directory)
    os.chdir(root)
    os.environ["MEMOS_CONFIG_DIR"] = str(root / "config")
    os.environ["XDG_STATE_HOME"] = str(root / "state")
    for name in (
        "MEMOS_CONNECTION",
        "MEMOS_API_KEY",
        "MEMOS_URL",
        "MEMKIT_API_KEY",
        "MEMKIT_BASE_URL",
    ):
        os.environ.pop(name, None)
    config.save(
        {
            "default": "smoke",
            "connections": {"smoke": {"url": "https://memory.example", "key": "smoke"}},
        }
    )
    from memos_cli import claude_hooks

    assert claude_hooks.repo_settings(root).recall is True
    cursor = claude_hooks.STATE_DIR / "existing.offset"
    cursor.parent.mkdir(parents=True)
    cursor.write_text("123")
    for target in ("claude", "hermes", "codex"):
        home = root / target
        install([target], home=str(home))
        install([target], home=str(home))
        assert (home / "skills/mem-os/SKILL.md").is_file()
        if target == "hermes":
            assert (home / "plugins/memkit/bridge.json").is_file()
    assert cursor.read_text() == "123"
    assert not any(name in sys.modules for name in ("memkit", "torch", "psycopg"))
print("Standalone wheel works without server packages, databases, Docker or models.")
