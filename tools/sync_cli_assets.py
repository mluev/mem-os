"""Build/check standalone CLI snapshots from canonical API and adapter sources.

Snapshots let the tiny wheel ship independently without importing the server.
Runtime wrappers select transport and installation defaults; behavior is copied unchanged.
"""

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "cli/src/memos_cli"
FILES = {
    "openapi.json": "openapi.json",
    "claude_classifier.py": "src/memkit/claude_classifier.py",
    "limits.py": "src/memkit/limits.py",
    "claude_hooks.py": "integrations/claude-code/hooks/memkit_hooks.py",
    "scrub.py": "integrations/hermes/memkit/scrub.py",
    **{
        f"assets/hermes/{name}": f"integrations/hermes/memkit/{name}"
        for name in ("__init__.py", "client.py", "scrub.py", "plugin.yaml")
    },
}
# Whole-directory snapshots: every file below the source is copied, and any other
# file below the target is stale, so a removed reference cannot linger in the wheel.
DIRECTORIES = {"assets/skill": "skills/mem-os"}


def outputs():
    """Copy canonical sources verbatim; runtime wrappers select the transport."""
    snapshots = dict(FILES)
    for target, source in DIRECTORIES.items():
        for path in sorted((ROOT / source).rglob("*")):
            if path.is_file():
                snapshots[f"{target}/{path.relative_to(ROOT / source).as_posix()}"] = (
                    path.relative_to(ROOT).as_posix()
                )
    for target, source in snapshots.items():
        yield TARGET / target, (ROOT / source).read_text()


def stale(expected):
    """Files inside snapshot directories that no canonical source produces."""
    return sorted(
        path
        for target in DIRECTORIES
        for path in (TARGET / target).rglob("*")
        if path.is_file() and path not in expected
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    # Read every source before touching any target, so a failure cannot leave a
    # half-regenerated snapshot behind.
    expected = dict(outputs())
    extra = stale(expected)
    if args.check:
        problems = [
            f"{'missing' if not path.exists() else 'changed'}: {path.relative_to(ROOT)}"
            for path, content in expected.items()
            if not path.exists() or path.read_text() != content
        ]
        problems += [f"stale: {path.relative_to(ROOT)}" for path in extra]
        if problems:
            raise SystemExit("CLI assets need regeneration: " + ", ".join(problems))
        return
    for path, content in expected.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    for path in extra:
        path.unlink()


if __name__ == "__main__":
    main()
