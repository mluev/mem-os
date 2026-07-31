"""Generate the machine-checkable parts of the docs from the code.

The problem this solves: over a few weeks this project accumulated three
generations of documentation stating three different judge models, four different
message counts, a prompt block matching no live prompt version, and a route table
missing ten routes. Prose drifts because nobody can diff it. Constants and route
tables can be diffed, so they should be, and the diff should fail the build.

How it works. Each doc carries regions delimited by HTML comments:

    <!-- generated:retrieval-weights -->
    | term | weight | constant |
    ...
    <!-- /generated:retrieval-weights -->

The markers are invisible in rendered markdown. `check()` regenerates each region
from the imported code and compares byte for byte; `write()` replaces them.
`tests/test_docs_contract.py` calls the same `check()`, so there is one generator
and no second copy of the formatting.

Why regions rather than parsing the human tables: a parser has to be taught each
table's shape, and its worst failure is silent -- rename a heading and it finds
nothing and reports success. Why not generate whole files: `05-retrieval.md` is
~200 lines of which ~20 are machine facts, and the argued prose is most of the
value. So the constants live in regions and the reasoning lives around them.

    python -m tools.docblocks --check
    python -m tools.docblocks --write     # then read the diff before committing

`--write` makes the doc follow the code. That is right when a constant changed
and wrong when the code change was the mistake, so read what it did.

What this cannot cover, by construction: measured numbers (a test cannot know
they are stale, and re-measuring costs money and is nondeterministic), rationale,
and behavioural claims like "dry_run makes no model call". The first gets a
`<!-- measured: DATE · COMMAND -->` marker so a human knows the date; the last is
what tests/test_api.py and tests/test_admin_routes.py are for.
"""

from __future__ import annotations

import argparse
import difflib
import sqlite3
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
sys.path.insert(0, str(ROOT / "src"))

OPEN = "<!-- generated:{name} -->"
CLOSE = "<!-- /generated:{name} -->"


# --------------------------------------------------------------------------
# Generators. Each returns the region body: no markers, no trailing newline.
# --------------------------------------------------------------------------

def _retrieval_weights() -> str:
    from memkit import retrieval

    rows = [
        ("similarity", retrieval.W_SIMILARITY, "retrieval.W_SIMILARITY"),
        ("importance", retrieval.W_IMPORTANCE, "retrieval.W_IMPORTANCE"),
        ("recency", retrieval.W_RECENCY, "retrieval.W_RECENCY"),
        ("scope_boost", retrieval.W_SCOPE, "retrieval.W_SCOPE"),
    ]
    lines = ["| term | weight | constant |", "|---|---|---|"]
    lines += [f"| {name} | {weight:.2f} | `{const}` |" for name, weight, const in rows]
    total = sum(weight for _, weight, _ in rows)
    lines.append("")
    lines.append(f"The four weights sum to {total:.2f}.")
    lines.append("")
    lines += [
        "| parameter | value | constant |",
        "|---|---|---|",
        f"| overfetch | {retrieval.OVERFETCH} | `retrieval.OVERFETCH` |",
        f"| dedup cosine | {retrieval.DEDUP_COSINE:.2f} | "
        "`retrieval.DEDUP_COSINE`, overridable with `MEMKIT_DEDUP_COSINE` |",
        f"| characters per token | {retrieval.CHARS_PER_TOKEN} | "
        "`retrieval.CHARS_PER_TOKEN` |",
    ]
    return "\n".join(lines)


def _retrieval_tau() -> str:
    from memkit import retrieval

    width = max(len(t) for t in retrieval.TAU) + 2
    lines = ["```python", "# Recency half-life per type, in days. retrieval.TAU"]
    lines.append("TAU = {")
    for type_name, days in retrieval.TAU.items():
        key = f'"{type_name}":'
        lines.append(f"    {key:<{width + 1}} {days:g},")
    lines.append("}")
    lines.append(f"TAU_DEFAULT = {retrieval.TAU_DEFAULT:g}  # unknown type")
    lines.append("```")
    return "\n".join(lines)


def _vocabularies() -> str:
    from memkit import judge, provenance, providers, taskboard

    rows = [
        ("type", providers.MEMORY_TYPES, "`providers.MEMORY_TYPES`"),
        ("scope", providers.SCOPES, "`providers.SCOPES`"),
        ("status", ["active", "expired", "superseded"], "`mutate` (literals)"),
        ("workflow_status", list(taskboard.WORKFLOW_STATUSES),
         "`taskboard.WORKFLOW_STATUSES`"),
        ("operation", ["ADD", "UPDATE", "DELETE"], "`judge.Op.parse`"),
        ("source_role", list(provenance.ROLES), "`provenance.ROLES`"),
        ("judge_runs.kind", ["extract", "consolidate"], "`judge`, `consolidate`"),
    ]
    lines = ["| vocabulary | values | defined in |", "|---|---|---|"]
    for name, values, source in rows:
        rendered = ", ".join(f"`{v}`" for v in values)
        lines.append(f"| {name} | {rendered} | {source} |")
    assert judge.MEMORY_TYPES == providers.MEMORY_TYPES  # mirrored, not redefined
    return "\n".join(lines)


def _sqlite_schema() -> str:
    """Read the schema from a freshly migrated file, not from the SQL string.

    Building it from a temp database means the table this documents is the one
    `init_db` actually produces, including everything the migrations did to it.
    """
    from memkit.db import SCHEMA_VERSION, init_db

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "schema.db"
        init_db(path)
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        tables = [
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        lines = [
            f"`db.SCHEMA_VERSION = {SCHEMA_VERSION}`, stored in "
            "`PRAGMA user_version`.",
            "",
            "| table | columns |",
            "|---|---|",
        ]
        for table in tables:
            columns = [
                row["name"] for row in conn.execute(f"PRAGMA table_info({table})")
            ]
            lines.append(f"| `{table}` | {', '.join(columns)} |")
        indexes = [
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        conn.close()
    lines.append("")
    lines.append("Indexes: " + ", ".join(f"`{name}`" for name in indexes) + ".")
    return "\n".join(lines)


def _http_routes() -> str:
    """Every route, its success status, and whether it needs the API key.

    Read from `app.openapi()` and not from `app.routes`: FastAPI wraps included
    routers, so walking `app.routes` yields only the handful declared directly on
    `app` and silently omits every admin and taskboard route. A hand-maintained
    table made exactly that mistake.
    """
    from memkit import api

    spec = api.app.openapi()
    rows = []
    for path, methods in sorted(spec["paths"].items()):
        for method, op in sorted(methods.items()):
            success = next(
                (code for code in op.get("responses", {}) if code.startswith("2")),
                "200",
            )
            key = "`X-API-Key`" if op.get("security") else "—"
            rows.append((f"`{method.upper()} {path}`", success, key))
    lines = ["| endpoint | success | auth |", "|---|---|---|"]
    lines += [f"| {route} | {code} | {key} |" for route, code, key in rows]
    guarded = sum(1 for _, _, key in rows if key != "—")
    lines.append("")
    lines.append(
        f"{len(rows)} routes, {guarded} behind the API key. "
        f"{len(rows) - guarded} unauthenticated."
    )
    return "\n".join(lines)


def _config_defaults() -> str:
    from memkit.config import Settings

    # Every value here is the declared *default*, never a configured one, so
    # there is nothing to redact -- and `api_key`'s default in particular has to
    # be visible, because shipping with it unchanged is the mistake to catch.
    lines = ["| setting | environment variable | default |", "|---|---|---|"]
    for name, field in Settings.model_fields.items():
        alias = field.validation_alias
        if alias is None:
            env = f"MEMKIT_{name.upper()}"
        elif isinstance(alias, str):
            env = alias
        else:  # AliasChoices, in precedence order
            env = " / ".join(str(choice) for choice in alias.choices)
        if field.default == "":
            default = '`""` (empty)'
        elif isinstance(field.default, list) and not field.default:
            default = "`[]`"
        else:
            default = f"`{field.default}`"
        lines.append(f"| `{name}` | `{env}` | {default} |")
    return "\n".join(lines)


def _prompt_versions() -> str:
    from memkit import judge, prompts

    lines = [
        "| | |",
        "|---|---|",
        f"| registry | {', '.join(f'`{v}`' for v in sorted(prompts.REGISTRY))} |",
        f"| active extractor prompt | `{prompts.DEFAULT_VERSION}` |",
        f"| consolidator prompt | `{prompts.CONSOLIDATE_VERSION}` |",
        f"| stamped on new facts | `{judge.PROMPT_VERSION}` |",
        f"| default judge model | `{judge.DEFAULT_MODEL}` |",
    ]
    return "\n".join(lines)


def _judge_models() -> str:
    from memkit import judge

    lines = [
        "| model | provider | $/Mtok in | $/Mtok out | note |",
        "|---|---|---|---|---|",
    ]
    for name, spec in judge.MODELS.items():
        price_in, price_out = spec["price"]
        note = []
        if name == judge.DEFAULT_MODEL:
            note.append("**default**")
        if spec.get("price_unverified"):
            note.append("price unverified")
        if spec.get("price_after"):
            after_in, after_out = spec["price_after"]
            note.append(
                f"introductory until {judge._INTRO_ENDS.isoformat()}, then "
                f"${after_in:.2f}/${after_out:.2f}"
            )
        lines.append(
            f"| `{name}` | {judge.provider_of(name)} | {price_in:.2f} | "
            f"{price_out:.2f} | {', '.join(note) or '—'} |"
        )
    lines.append("")
    lines.append(
        "An unknown model is priced at the most expensive known pair rather than "
        "at zero, so an unrecognised name cannot make a run look free."
    )
    return "\n".join(lines)


BLOCKS: dict[str, tuple[Path, Callable[[], str]]] = {
    "retrieval-weights": (DOCS / "05-retrieval.md", _retrieval_weights),
    "retrieval-tau": (DOCS / "05-retrieval.md", _retrieval_tau),
    "vocabularies": (DOCS / "02-data-model.md", _vocabularies),
    "sqlite-schema": (DOCS / "02-data-model.md", _sqlite_schema),
    "http-routes": (DOCS / "03-api.md", _http_routes),
    "config-defaults": (DOCS / "01-architecture.md", _config_defaults),
    "judge-models": (DOCS / "04-judge.md", _judge_models),
    "prompt-versions": (
        DOCS / "experiments" / "extractor-prompts.md", _prompt_versions
    ),
}


# --------------------------------------------------------------------------
# Region handling
# --------------------------------------------------------------------------

def render(name: str) -> str:
    """The body a region should contain."""
    return BLOCKS[name][1]()


def _region(text: str, name: str) -> tuple[int, int] | None:
    """Character span of the region body, or None if the markers are absent."""
    open_marker = OPEN.format(name=name)
    close_marker = CLOSE.format(name=name)
    start = text.find(open_marker)
    end = text.find(close_marker)
    if start == -1 or end == -1 or end < start:
        return None
    return start + len(open_marker), end


def current(name: str) -> str | None:
    """What the doc holds today, or None if the file or markers are missing."""
    path = BLOCKS[name][0]
    if not path.exists():
        return None
    text = path.read_text()
    span = _region(text, name)
    if span is None:
        return None
    return text[span[0] : span[1]].strip("\n")


def check() -> list[tuple[str, str]]:
    """[(block name, human-readable problem)] for every stale or missing block."""
    problems = []
    for name, (path, _) in BLOCKS.items():
        expected = render(name)
        actual = current(name)
        if actual is None:
            rel = path.relative_to(ROOT)
            reason = "file does not exist" if not path.exists() else (
                f"missing markers {OPEN.format(name=name)} … "
                f"{CLOSE.format(name=name)}"
            )
            problems.append((name, f"{rel}: {reason}"))
            continue
        if actual != expected:
            diff = "\n".join(
                difflib.unified_diff(
                    actual.splitlines(),
                    expected.splitlines(),
                    fromfile=f"{path.relative_to(ROOT)} (in the doc)",
                    tofile=f"generated from code ({name})",
                    lineterm="",
                )
            )
            problems.append((name, diff))
    return problems


def write() -> list[str]:
    """Rewrite every stale region. Returns the names it changed."""
    changed = []
    by_path: dict[Path, list[str]] = {}
    for name, (path, _) in BLOCKS.items():
        by_path.setdefault(path, []).append(name)
    for path, names in by_path.items():
        if not path.exists():
            print(f"skipped {path.relative_to(ROOT)}: does not exist yet")
            continue
        text = path.read_text()
        for name in names:
            span = _region(text, name)
            if span is None:
                print(f"skipped {name}: no markers in {path.relative_to(ROOT)}")
                continue
            body = render(name)
            if text[span[0] : span[1]].strip("\n") == body:
                continue
            text = text[: span[0]] + "\n" + body + "\n" + text[span[1] :]
            changed.append(name)
        path.write_text(text)
    return changed


def scaffold() -> str:
    """Every block with its markers, for pasting into a doc being written."""
    out = []
    for name in BLOCKS:
        out.append(OPEN.format(name=name))
        out.append(render(name))
        out.append(CLOSE.format(name=name))
        out.append("")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true", default=True,
                       help="report stale blocks and exit non-zero (default)")
    group.add_argument("--write", action="store_true",
                       help="rewrite stale blocks in place")
    group.add_argument("--scaffold", action="store_true",
                       help="print every block with markers, for a new doc")
    group.add_argument("--show", metavar="NAME",
                       help="print one generated block")
    args = parser.parse_args(argv)

    if args.scaffold:
        print(scaffold(), end="")
        return 0
    if args.show:
        if args.show not in BLOCKS:
            print(f"unknown block {args.show!r}; known: {', '.join(BLOCKS)}",
                  file=sys.stderr)
            return 2
        print(render(args.show))
        return 0
    if args.write:
        changed = write()
        print(f"rewrote {len(changed)} block(s): {', '.join(changed) or 'none'}")
        print("Read the diff before committing: --write makes the doc follow the "
              "code, which is wrong if the code change was the mistake.")
        return 0

    problems = check()
    if not problems:
        print(f"all {len(BLOCKS)} generated doc blocks match the code")
        return 0
    for name, detail in problems:
        print(f"\n=== {name} ===")
        print(detail)
    print(f"\n{len(problems)} of {len(BLOCKS)} block(s) stale or missing.")
    print("Run:  python -m tools.docblocks --write")
    print("then read the diff -- it makes the doc follow the code, which is the "
          "wrong direction if the code change was the mistake.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
