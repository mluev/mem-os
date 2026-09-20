"""Build/check standalone CLI snapshots from canonical API and adapter sources.

Snapshots let the tiny wheel ship independently without importing the server.
Runtime wrappers select transport and installation defaults; behavior is copied unchanged.
"""

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "cli/src/memos_cli"


def outputs():
    """Copy canonical sources verbatim; runtime wrappers select the transport."""
    snapshots = {
        "openapi.json": "openapi.json",
        "claude_classifier.py": "src/memkit/claude_classifier.py",
        "limits.py": "src/memkit/limits.py",
        "claude_hooks.py": "integrations/claude-code/hooks/memkit_hooks.py",
        "scrub.py": "integrations/hermes/memkit/scrub.py",
    }
    for name in ("__init__.py", "client.py", "scrub.py", "plugin.yaml"):
        snapshots[f"assets/hermes/{name}"] = f"integrations/hermes/memkit/{name}"
    for target, source in snapshots.items():
        yield TARGET / target, (ROOT / source).read_text()


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
