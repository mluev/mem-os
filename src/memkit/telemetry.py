"""Privacy-preserving retrieval telemetry and explicit result feedback."""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from .db import utcnow


def hash_query(secret: str, query: str) -> str:
    if not secret:
        raise ValueError("retrieval telemetry HMAC secret is not configured")
    return hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()


def record_retrieval_run(
    conn: sqlite3.Connection,
    *,
    owner_id: str,
    query_hash: str,
    policy_id: str,
    results: list[dict[str, Any]],
    timings: dict[str, float],
    used_tokens: int,
) -> str:
    retrieval_id = str(uuid.uuid4())
    safe_results = [
        {
            "memory_id": str(item["id"]),
            "rank": rank,
            "score": float(item.get("score", 0.0)),
            "similarity": float(item.get("similarity", 0.0)),
            "lexical": float(item.get("lexical", 0.0)),
            "entity": float(item.get("entity", 0.0)),
        }
        for rank, item in enumerate(results, start=1)
    ]
    conn.execute(
        """INSERT INTO retrieval_runs
           (id,owner_id,query_hash,policy_id,result_json,timings_json,
            used_tokens,abstained,created_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (
            retrieval_id,
            owner_id,
            query_hash,
            policy_id,
            json.dumps(safe_results, separators=(",", ":"), sort_keys=True),
            json.dumps(timings, separators=(",", ":"), sort_keys=True),
            used_tokens,
            int(not safe_results),
            utcnow(),
        ),
    )
    return retrieval_id


def record_run_feedback(
    conn: sqlite3.Connection,
    *,
    retrieval_id: str,
    owner_id: str,
    memory_id: str,
    useful: bool | None,
    correct: bool | None,
) -> None:
    if useful is None and correct is None:
        raise ValueError("at least one feedback value is required")
    row = conn.execute(
        "SELECT result_json FROM retrieval_runs WHERE id=? AND owner_id=?",
        (retrieval_id, owner_id),
    ).fetchone()
    if row is None:
        raise LookupError("unknown retrieval run")
    result_ids = {str(item["memory_id"]) for item in json.loads(row["result_json"])}
    if memory_id not in result_ids:
        raise ValueError("memory was not returned by this retrieval run")
    conn.execute(
        """INSERT INTO retrieval_run_feedback
           (retrieval_run_id,memory_id,useful,correct,created_at)
           VALUES (?,?,?,?,?)
           ON CONFLICT(retrieval_run_id,memory_id) DO UPDATE SET
             useful=excluded.useful,correct=excluded.correct,created_at=excluded.created_at""",
        (
            retrieval_id,
            memory_id,
            None if useful is None else int(useful),
            None if correct is None else int(correct),
            utcnow(),
        ),
    )


def prune(conn: sqlite3.Connection, *, retention_days: int = 90) -> int:
    cutoff = (
        (datetime.now(UTC) - timedelta(days=retention_days))
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )
    cursor = conn.execute("DELETE FROM retrieval_runs WHERE created_at<?", (cutoff,))
    return max(0, int(cursor.rowcount))


def _percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(quantile * len(ordered)) - 1)
    return round(ordered[index], 1)


def metrics(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = conn.execute(
        "SELECT timings_json,abstained FROM retrieval_runs WHERE created_at>=datetime('now','-90 days')"
    ).fetchall()
    latencies = [
        float(json.loads(row["timings_json"] or "{}").get("total_ms", 0.0)) for row in rows
    ]
    total = len(rows)
    feedback = conn.execute(
        """SELECT COUNT(*) AS labels,COUNT(DISTINCT retrieval_run_id) AS runs,
                  AVG(useful) AS useful_rate,AVG(correct) AS correct_rate
             FROM retrieval_run_feedback"""
    ).fetchone()
    return {
        "search_latency_ms": {
            "p50": _percentile(latencies, 0.50),
            "p95": _percentile(latencies, 0.95),
            "p99": _percentile(latencies, 0.99),
        },
        "retrieval_runs": total,
        "abstention_rate": (
            round(sum(int(row["abstained"]) for row in rows) / total, 4) if total else None
        ),
        "feedback_labels": int(feedback["labels"] or 0),
        "feedback_runs": int(feedback["runs"] or 0),
        "useful_rate": (
            round(float(feedback["useful_rate"]), 4)
            if feedback["useful_rate"] is not None
            else None
        ),
        "correct_rate": (
            round(float(feedback["correct_rate"]), 4)
            if feedback["correct_rate"] is not None
            else None
        ),
    }


def recent_runs(
    conn: sqlite3.Connection, *, owner_id: str, limit: int = 20
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT * FROM retrieval_runs WHERE owner_id=?
            ORDER BY created_at DESC,id DESC LIMIT ?""",
        (owner_id, limit),
    ).fetchall()
    items: list[dict[str, Any]] = []
    for row in rows:
        results = json.loads(row["result_json"])
        for result in results:
            memory = conn.execute(
                "SELECT text,kind,source_role FROM memories WHERE id=? AND owner_id=?",
                (result["memory_id"], owner_id),
            ).fetchone()
            if memory is not None:
                result.update(
                    {
                        "text": memory["text"],
                        "kind": memory["kind"],
                        "source_role": memory["source_role"],
                    }
                )
            feedback = conn.execute(
                """SELECT useful,correct,created_at FROM retrieval_run_feedback
                    WHERE retrieval_run_id=? AND memory_id=?""",
                (row["id"], result["memory_id"]),
            ).fetchone()
            result["feedback"] = dict(feedback) if feedback else None
        items.append(
            {
                "id": row["id"],
                "policy_id": row["policy_id"],
                "results": results,
                "timings": json.loads(row["timings_json"]),
                "used_tokens": row["used_tokens"],
                "abstained": bool(row["abstained"]),
                "created_at": row["created_at"],
            }
        )
    return items
