"""Legacy replay planning and restart-safe application."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from . import extract, judge
from .db import transaction, utcnow
from .limits import MAX_MEMORY_CHARS


def dry_run_report(
    conn: sqlite3.Connection,
    *,
    owner_id: str,
    model: str,
    output_dir: Path,
) -> dict[str, Any]:
    active_rows = conn.execute(
        "SELECT * FROM memories WHERE owner_id=? AND status='active' ORDER BY id",
        (owner_id,),
    ).fetchall()
    versions = {
        row["extraction_version"]: row["n"]
        for row in conn.execute(
            """SELECT extraction_version,COUNT(*) n FROM memories
                WHERE owner_id=? AND status='active' GROUP BY extraction_version""",
            (owner_id,),
        )
    }
    session_counts = conn.execute(
        """SELECT m.session_id,COUNT(*) n FROM messages m
             JOIN sessions s ON s.id=m.session_id
            WHERE s.owner_id=? GROUP BY m.session_id""",
        (owner_id,),
    ).fetchall()
    messages = sum(int(row["n"]) for row in session_counts)
    # Replay windows never cross session boundaries, so each session must be
    # rounded separately or the durable job call limit can stop a valid replay.
    windows = sum(
        (int(row["n"]) + judge.MESSAGES_PER_EXTRACTION - 1) // judge.MESSAGES_PER_EXTRACTION
        for row in session_counts
    )
    estimated_cost = windows * judge.cost_of(3000, 150, model=model)
    provenance = {
        row["source_role"]: row["n"]
        for row in conn.execute(
            """SELECT source_role,COUNT(*) n FROM memories
                WHERE owner_id=? AND status='active' GROUP BY source_role""",
            (owner_id,),
        )
    }
    contexts: dict[str, int] = {}
    for row in active_rows:
        normalized = json.dumps(
            json.loads(row["context_json"] or "{}"),
            ensure_ascii=False,
            sort_keys=True,
        )
        contexts[normalized] = contexts.get(normalized, 0) + 1
    cited = int(
        conn.execute(
            """SELECT COUNT(DISTINCT e.memory_id) FROM memory_evidence e
                 JOIN memories m ON m.id=e.memory_id
                WHERE m.owner_id=? AND m.status='active'""",
            (owner_id,),
        ).fetchone()[0]
    )
    expired = sum(
        1
        for row in active_rows
        if row["valid_until"] is not None and row["valid_until"] <= utcnow()
    )
    untrusted = sum(1 for row in active_rows if row["source_role"] in {"assistant", "agent"})
    overlong = sum(1 for row in active_rows if len(row["text"]) > 200)
    storage_overlimit = sum(1 for row in active_rows if len(row["text"]) > MAX_MEMORY_CHARS)
    report = {
        "mode": "dry-run-only",
        "generated_at": utcnow(),
        "owner_id": owner_id,
        "active_by_version": versions,
        "messages": messages,
        "estimated_windows": windows,
        "estimated_cost_usd": round(estimated_cost, 6),
        "provenance": {
            "active_by_source_role": provenance,
            "with_exact_evidence": cited,
            "without_exact_evidence": len(active_rows) - cited,
        },
        "contexts": dict(sorted(contexts.items(), key=lambda item: (-item[1], item[0]))),
        "expiry": {
            "indefinite": sum(row["valid_until"] is None for row in active_rows),
            "dated": sum(row["valid_until"] is not None for row in active_rows),
            "expired_but_active": expired,
        },
        "search_quality": {
            "status": "not_measured_on_live_data",
            "reason": "dry-run does not mutate or replay the live index",
            "required_gate": [
                "corrections",
                "contradictions",
                "silence",
                "exact-term",
                "temporal",
                "10k-distractors",
            ],
        },
        "proposed_changes": [
            {
                "action": "archive_untrusted_claims_from_normal_retrieval",
                "count": untrusted,
            },
            {"action": "expire_past_valid_until", "count": expired},
            {"action": "review_overlong_memories", "count": overlong},
            {
                "action": "preserve_and_review_legacy_storage_exceptions",
                "count": storage_overlimit,
            },
            {
                "action": "reextract_with_exact_evidence",
                "count": len(active_rows) - cited,
            },
        ],
        "rollback": {
            "before_apply": "retain this report and make no live changes",
            "future_apply": "create a fresh SQLite backup and Qdrant generation; switch alias only after validation",
        },
        "apply_allowed": False,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "legacy-replay-dry-run.json"
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)
    report["report_path"] = str(path)
    return report


def apply_replay(
    conn: sqlite3.Connection,
    *,
    owner_id: str,
    api_key: str,
    gemini_api_key: str,
    project: str,
    location: str,
    monthly_limit_usd: float,
    model: str,
    job_id: str,
    cancelled,
) -> dict[str, Any]:
    """Replay every owner session through v7; processed flags are the durable cursor."""
    initialized = conn.execute(
        "SELECT 1 FROM job_events WHERE job_id=? AND status='replay_initialized'",
        (job_id,),
    ).fetchone()
    if initialized is None:
        with transaction(conn):
            conn.execute(
                """UPDATE messages SET processed=0,claim_token=NULL,claim_expires_at=NULL
                     WHERE session_id IN (SELECT id FROM sessions WHERE owner_id=?)""",
                (owner_id,),
            )
            conn.execute(
                """INSERT INTO job_events(job_id,status,detail_json,created_at)
                   VALUES (?,'replay_initialized','{}',?)""",
                (job_id, utcnow()),
            )
    totals = {"windows": 0, "added": 0, "updated": 0, "deleted": 0, "rejected": 0}
    sessions = conn.execute(
        "SELECT id,agent_id FROM sessions WHERE owner_id=? ORDER BY started_at,id",
        (owner_id,),
    ).fetchall()
    for session in sessions:
        while extract.messages_since_last(conn, session["id"]):
            if cancelled():
                return {**totals, "cancelled": True}
            outcome = extract.run_extraction(
                conn,
                session_id=session["id"],
                owner_id=owner_id,
                agent_id=session["agent_id"],
                api_key=api_key,
                gemini_api_key=gemini_api_key,
                project=project,
                location=location,
                monthly_limit_usd=monthly_limit_usd,
                model=model,
                job_id=job_id,
                force=True,
            )
            if outcome.error:
                raise RuntimeError(f"replay stopped: {outcome.error}")
            totals["windows"] += 1
            totals["added"] += outcome.added
            totals["updated"] += outcome.updated
            totals["deleted"] += outcome.deleted
            totals["rejected"] += outcome.rejected
    return {**totals, "cancelled": False, "prompt_version": judge.PROMPT_VERSION}
