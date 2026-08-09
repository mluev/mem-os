"""Small contract checker for normative documentation and generated OpenAPI."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from memkit.api import app

ROOT = Path(__file__).resolve().parents[1]


def check() -> list[str]:
    errors: list[str] = []
    schema_path = ROOT / "openapi.json"
    if not schema_path.exists() or json.loads(schema_path.read_text()) != app.openapi():
        errors.append("openapi.json is stale; run tools/export_openapi.py")
    required = {
        "docs/01-architecture.md": "Memory, not workflow",
        "docs/02-data-model.md": "Schema version is 4",
        "docs/05-retrieval.md": "BM25",
        "docs/08-testing.md": "10,000 distractors",
    }
    for relative, phrase in required.items():
        if phrase.casefold() not in (ROOT / relative).read_text().casefold():
            errors.append(f"{relative} is missing {phrase!r}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.parse_args()
    errors = check()
    for error in errors:
        print(error)
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
