"""Prepare the scope review: which stored facts are bound to a repo by wording only.

Measured on the full corpus under v4: 41 of 62 extracted facts came back
scope=project and only 21 scope=user, so 34% of the store was reachable without
naming a project. Reading the 41 by hand, roughly 17 are facts about the person
that happen to mention a repository -- "For frontend-second, prefers modal dialogs
with tabs". A project-scoped fact is dropped by the read path whenever the caller
does not name that project, so those are effectively write-only.

This script does not decide anything. It prints each project-scoped fact with the
signals that matter and emits a ready-to-paste id list, so the call stays with a
human in the dashboard. The judge already got this wrong once; a second automated
pass would just be the same mistake at a different layer.

    uv run python -m eval.scope_review
    uv run python -m eval.scope_review --json    # ids only, for the bulk endpoint

Applying a decision, once reviewed:

    POST /v1/admin/memories/bulk
    {"ids": [...], "op": "set_scope", "value": {"scope": "user"}}

`mutate.update_memory` clears `scope_key` on the way to user scope, and
`mutate.bulk` re-embeds nothing it does not have to, so the vector payload stays
consistent without a reindex.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from memkit.config import get_settings  # noqa: E402

# Phrased as a statement about the person rather than about a codebase.
PERSONAL = re.compile(
    r"\b(prefers?|wants?|requires?|expects?|rejects?|likes?|dislikes?|insists?"
    r"|avoids?|refuses?)\b",
    re.IGNORECASE,
)
# Names a concrete artefact of one codebase. Even with "prefers" in the sentence,
# these are genuinely project-scoped.
STRUCTURAL = re.compile(
    r"\.(vue|tsx?|py)\b|\blives in\b|\bendpoint\b|\bschema\b|\btable\b"
    r"|\blogin\b|\bOTP\b|\bAPI\b|\bfolder\b|\bdirectory\b",
    re.IGNORECASE,
)


def verdict(text: str) -> tuple[str, str]:
    """A hint, not a decision.

    The test is v5 rule 5's: would this exact sentence still be true if the user
    switched to a different project?
    """
    personal = bool(PERSONAL.search(text))
    structural = bool(STRUCTURAL.search(text))
    if personal and not structural:
        return "PROMOTE?", "phrased as a preference, names no concrete artefact"
    if personal and structural:
        return "look", "reads as a preference but names a concrete artefact"
    return "keep", "structural — genuinely about one codebase"


def main() -> int:
    ap = argparse.ArgumentParser(prog="scope_review")
    ap.add_argument("--json", action="store_true", help="print only the id list")
    ap.add_argument("--owner", default=None)
    args = ap.parse_args()

    settings = get_settings()
    conn = sqlite3.connect(settings.db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT id, scope_key, type, importance, text, extraction_version,
                  retrieval_count
             FROM memories
            WHERE owner_id = ? AND status = 'active' AND scope = 'project'
            ORDER BY scope_key, importance DESC""",
        (args.owner or settings.owner_id,),
    ).fetchall()

    graded = [(verdict(r["text"]), r) for r in rows]
    promote = [r["id"] for (v, _), r in graded if v == "PROMOTE?"]

    if args.json:
        print(json.dumps({"ids": promote, "op": "set_scope",
                          "value": {"scope": "user"}}, indent=2))
        return 0

    total_active = conn.execute(
        "SELECT COUNT(*) n FROM memories WHERE owner_id=? AND status='active'",
        (args.owner or settings.owner_id,),
    ).fetchone()["n"]
    user_scope = total_active - len(rows)

    print(f"active facts        {total_active}")
    print(f"  scope=user        {user_scope}  <- reachable without naming a project")
    print(f"  scope=project     {len(rows)}")
    print(f"reachable share     {user_scope / max(1, total_active):.0%}\n")

    order = {"PROMOTE?": 0, "look": 1, "keep": 2}
    for (v, why), r in sorted(graded, key=lambda g: (order[g[0][0]], g[1]["scope_key"] or "")):
        seen = "never retrieved" if not r["retrieval_count"] else f"retrieved {r['retrieval_count']}x"
        print(f"[{v:<9}] {r['id'][:8]}  {r['scope_key'] or '-':<18} "
              f"imp={r['importance']:.1f} {r['type']:<11} ({seen})")
        print(f"             {r['text'][:150]}")
        print(f"             why: {why}")
        print()

    print("-" * 78)
    print(f"suggested for promotion to scope=user: {len(promote)} of {len(rows)}")
    print("Review each one, then apply with:")
    print("  uv run python -m eval.scope_review --json | \\")
    print("    curl -X POST localhost:8077/v1/admin/memories/bulk \\")
    print("      -H \"X-API-Key: $MEMKIT_API_KEY\" -H 'Content-Type: application/json' -d @-")
    print("\nThe hints are regex heuristics. The judge already mis-scoped these once;")
    print("the point of this listing is that a person decides, not a second model.")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
