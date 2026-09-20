"""Run using a clean interpreter with only the standalone CLI installed."""

# ruff: noqa: S101 -- this executable is a packaging acceptance test

import importlib.metadata
import json
import subprocess
import sys

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
print("Standalone wheel works without server packages, databases, Docker or models.")
