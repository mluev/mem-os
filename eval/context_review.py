"""List active memories whose copied context may be unnecessarily restrictive."""

from __future__ import annotations

import argparse
import json
import re
import sqlite3

from memkit.config import get_settings

PERSONAL = re.compile(
    r"\b(prefers?|wants?|requires?|expects?|likes?|dislikes?|avoids?|refuses?)\b",
    re.IGNORECASE,
)


def main() -> int:
    parser = argparse.ArgumentParser(prog="context_review")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    conn = sqlite3.connect(settings.db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT id,revision,kind,text,context_json,importance FROM memories
             WHERE owner_id=? AND status='active' AND context_json!='{}'
             ORDER BY importance DESC,id""",
        (settings.owner_id,),
    ).fetchall()
    candidates = [row for row in rows if PERSONAL.search(row["text"])]
    if args.json:
        print(
            json.dumps(
                [
                    {
                        "id": row["id"],
                        "revision": row["revision"],
                        "context": json.loads(row["context_json"]),
                    }
                    for row in candidates
                ],
                indent=2,
            )
        )
        return 0
    print(f"context-bound active memories: {len(rows)}")
    print(f"manual-review candidates: {len(candidates)}")
    for row in candidates:
        print(
            f"{row['id'][:8]} r{row['revision']} {row['kind']} "
            f"context={row['context_json']} — {row['text'][:120]}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
