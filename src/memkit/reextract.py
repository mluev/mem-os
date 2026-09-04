"""Re-extraction planning: what a prompt change would cost, before it runs.

Only the report survives from the old replay program. Applying a replay used to
copy the SQLite file, rewrite the copy, and swap it in; on Postgres that becomes
a shadow database, which is a different piece of work and has no rows waiting
for it (see docs/decisions on the parked release program). The report is the
part that was actually used: it answers "how many windows, at what cost, over
which scopes" before anyone spends money.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import psycopg

from . import judge
from .db import iso


def dry_run_report(
    conn: psycopg.Connection,
    *,
    scope_ids: Sequence[str],
    model: str | None = None,
) -> dict[str, Any]:
    """Plan a re-extraction over these scopes. Writes nothing.

    The window count is rounded per session, not over the whole corpus: windows
    never cross a session boundary, so summing first and dividing later
    under-counts and would let a job's call limit stop a valid replay midway.
    """
    if not scope_ids:
        return {"scopes": 0, "memories": 0, "messages": 0, "windows": 0}
    model = model or judge.DEFAULT_MODEL
    scopes = list(scope_ids)

    versions = {
        str(row["extraction_version"]): int(row["n"])
        for row in conn.execute(
            """SELECT extraction_version,COUNT(*) AS n FROM memories
                WHERE scope_id = ANY(%s) AND status='active'
                GROUP BY extraction_version""",
            (scopes,),
        )
    }
    provenance = {
        str(row["source_role"]): int(row["n"])
        for row in conn.execute(
            """SELECT source_role,COUNT(*) AS n FROM memories
                WHERE scope_id = ANY(%s) AND status='active' GROUP BY source_role""",
            (scopes,),
        )
    }
    review = {
        str(row["review_status"]): int(row["n"])
        for row in conn.execute(
            """SELECT review_status,COUNT(*) AS n FROM memories
                WHERE scope_id = ANY(%s) AND status='active' GROUP BY review_status""",
            (scopes,),
        )
    }
    contexts = {
        json.dumps(dict(row["context"] or {}), ensure_ascii=False, sort_keys=True): int(row["n"])
        for row in conn.execute(
            """SELECT context,COUNT(*) AS n FROM memories
                WHERE scope_id = ANY(%s) AND status='active' GROUP BY context""",
            (scopes,),
        )
    }
    session_counts = conn.execute(
        """SELECT m.session_id, COUNT(*) AS n FROM messages m
             JOIN sessions s ON s.id = m.session_id
            WHERE s.scope_id = ANY(%s) GROUP BY m.session_id""",
        (scopes,),
    ).fetchall()
    messages = sum(int(row["n"]) for row in session_counts)
    windows = sum(
        (int(row["n"]) + judge.MESSAGES_PER_EXTRACTION - 1) // judge.MESSAGES_PER_EXTRACTION
        for row in session_counts
    )
    oldest = conn.execute(
        """SELECT MIN(created_at) AS oldest FROM messages m
             JOIN sessions s ON s.id = m.session_id
            WHERE s.scope_id = ANY(%s)""",
        (scopes,),
    ).fetchone()
    return {
        "scopes": len(scopes),
        "memories": sum(versions.values()),
        "messages": messages,
        "sessions": len(session_counts),
        "windows": windows,
        "extraction_versions": versions,
        "provenance": provenance,
        "review_status": review,
        "contexts": contexts,
        "active_prompt_version": judge.PROMPT_VERSION,
        "model": model,
        # Per-window token estimate from the measured production average, not a
        # guess: see docs/measurements.md#cost.
        "estimated_cost_usd": round(windows * judge.cost_of(3000, 150, model=model), 4),
        "oldest_message": iso(oldest["oldest"]) if oldest else None,
    }
