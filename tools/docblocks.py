"""Small contract checker for normative documentation and generated OpenAPI.

Two kinds of claim are checked. Canary phrases assert that a normative document
still says the thing it exists to say. Generated regions are rendered from the
code and compared byte for byte, so a documented value cannot drift: the prompt
registry block claimed `v2`-`v6` and consolidator `c1` for weeks after the code
moved to v7/v8 and c2, because nothing regenerated it.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from memkit import judge, prompts
from memkit.api import app
from memkit.db import SCHEMA_VERSION

ROOT = Path(__file__).resolve().parents[1]


def _prompt_versions() -> str:
    registry = ", ".join(f"`{version}`" for version in sorted(prompts.REGISTRY))
    return "\n".join(
        [
            "| | |",
            "|---|---|",
            f"| registry | {registry} |",
            f"| active extractor prompt | `{prompts.DEFAULT_VERSION}` |",
            f"| consolidator prompt | `{prompts.CONSOLIDATE_VERSION}` |",
            f"| stamped on new facts | `{judge.PROMPT_VERSION}` |",
            f"| default judge model | `{judge.DEFAULT_MODEL}` |",
        ]
    )


def _judge_rate_card() -> str:
    rows = ["| model | $/Mtok in | $/Mtok out | |", "|---|---|---|---|"]
    for model, spec in judge.MODELS.items():
        price_in, price_out = spec["price"]
        note = "unverified" if spec.get("price_unverified") else ""
        rows.append(f"| `{model}` | {price_in:.2f} | {price_out:.2f} | {note} |")
    return "\n".join(rows)


# Region name -> (document, renderer).
GENERATED = {
    "prompt-versions": ("docs/experiments/extractor-prompts.md", _prompt_versions),
    "judge-rate-card": ("docs/04-judge.md", _judge_rate_card),
}


def _region(text: str, name: str) -> tuple[int, int] | None:
    match = re.search(
        rf"<!-- generated:{re.escape(name)} -->\n(.*?)<!-- /generated:{re.escape(name)} -->",
        text,
        re.DOTALL,
    )
    return (match.start(1), match.end(1)) if match else None


def render(write: bool = False) -> list[str]:
    """Check every generated region, optionally rewriting it."""
    errors: list[str] = []
    for name, (relative, renderer) in GENERATED.items():
        path = ROOT / relative
        text = path.read_text()
        span = _region(text, name)
        if span is None:
            errors.append(f"{relative} is missing the generated:{name} region")
            continue
        expected = renderer() + "\n"
        if text[span[0] : span[1]] == expected:
            continue
        if write:
            path.write_text(text[: span[0]] + expected + text[span[1] :])
        else:
            errors.append(
                f"{relative} generated:{name} is stale; run python -m tools.docblocks --write"
            )
    return errors


def check() -> list[str]:
    errors: list[str] = render()
    schema_path = ROOT / "openapi.json"
    if not schema_path.exists() or json.loads(schema_path.read_text()) != app.openapi():
        errors.append("openapi.json is stale; run tools/export_openapi.py")
    required = {
        "docs/01-architecture.md": "Memory, not workflow",
        # Derived from code so a schema bump cannot leave the doc claiming the
        # old version -- exactly the drift this checker exists to catch.
        "docs/02-data-model.md": f"Schema version is {SCHEMA_VERSION}",
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
    parser.add_argument("--write", action="store_true", help="rewrite generated regions")
    args = parser.parse_args()
    if args.write:
        render(write=True)
    errors = check()
    for error in errors:
        print(error)
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
