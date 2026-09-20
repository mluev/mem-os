"""Privacy-preserving retrieval telemetry and explicit result feedback.

A run row records how a search behaved, never what was asked: the query is
reduced to an HMAC digest so the table can be joined against itself over time
without holding anyone's question. That is why `hash_query` refuses an empty
secret rather than falling back to a plain hash.

Telemetry is keyed by `user_id`, not by scope. A run is an act by a person, and
the same person may search several scopes in one query, so there is no single
scope to attribute it to. The consequence is that reading a run back has to
re-check what the caller may see, which is what `allowed_scope_ids` is for in
`recent_runs`.
"""

from __future__ import annotations

import hashlib
import hmac
import math
import uuid
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from .db import iso, utcnow


def hash_query(secret: str, query: str) -> str:
    if not secret:
        raise ValueError("retrieval telemetry HMAC secret is not configured")
    return hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()


def _as_uuids(values: list[str]) -> list[uuid.UUID]:
    """Parse ids for a `= ANY(%s)` predicate, dropping anything unparseable.

    The ids arrive from stored JSON and from callers, and psycopg dumps
    `uuid.UUID` as the `uuid` type, so the comparison stays index-eligible
    instead of forcing a cast on the column.
    """
    parsed: list[uuid.UUID] = []
    for value in values:
        try:
            parsed.append(uuid.UUID(str(value)))
        except (ValueError, AttributeError, TypeError):
            continue
    return parsed


def record_retrieval_run(
    conn: psycopg.Connection,
    *,
    user_id: str,
    query_hash: str,
    policy_id: str,
    results: list[dict[str, Any]],
    timings: dict[str, float],
    used_tokens: int,
    has_evidence: bool = False,
) -> str:
    """Store one search's scores and timings, without its text.

    Only the score components are kept per result -- no memory text, no query --
    so the table can be read by anyone debugging the ranker without becoming a
    second copy of the memory store.
    """
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
           (id,user_id,query_hash,policy_id,results,timings,
            used_tokens,abstained,created_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (
            retrieval_id,
            user_id,
            query_hash,
            policy_id,
            Jsonb(safe_results),
            Jsonb(timings),
            used_tokens,
            not safe_results and not has_evidence,
            utcnow(),
        ),
    )
    return retrieval_id


def record_run_feedback(
    conn: psycopg.Connection,
    *,
    retrieval_id: str,
    user_id: str,
    memory_id: str,
    useful: bool | None,
    correct: bool | None,
) -> None:
    """Label one result of one run, replacing any earlier label for that pair.

    The run is looked up with the caller's `user_id` in the predicate so a run
    belonging to someone else reads as unknown rather than as forbidden: the run
    id is a random uuid, and confirming its existence is itself a leak.
    """
    if useful is None and correct is None:
        raise ValueError("at least one feedback value is required")
    row = conn.execute(
        "SELECT results FROM retrieval_runs WHERE id=%s AND user_id=%s",
        (retrieval_id, user_id),
    ).fetchone()
    if row is None:
        raise LookupError("unknown retrieval run")
    result_ids = {str(item["memory_id"]) for item in row["results"]}
    if memory_id not in result_ids:
        raise ValueError("memory was not returned by this retrieval run")
    # One label per (run, memory) is the semantic the dashboard relies on, and
    # the table carries no unique constraint to hang an ON CONFLICT from, so the
    # replacement is done by hand. Safe under concurrency because the caller
    # holds a transaction and both statements touch the same rows.
    updated = conn.execute(
        """UPDATE retrieval_run_feedback SET useful=%s,correct=%s,created_at=%s
            WHERE run_id=%s AND memory_id=%s""",
        (useful, correct, utcnow(), retrieval_id, memory_id),
    )
    if updated.rowcount:
        return
    conn.execute(
        """INSERT INTO retrieval_run_feedback
           (run_id,memory_id,useful,correct,created_at)
           VALUES (%s,%s,%s,%s,%s)""",
        (retrieval_id, memory_id, useful, correct, utcnow()),
    )


def prune(conn: psycopg.Connection, *, retention_days: int = 90) -> int:
    """Drop runs past the retention window. Feedback cascades with them."""
    cursor = conn.execute(
        "DELETE FROM retrieval_runs WHERE created_at < now() - make_interval(days => %s)",
        (retention_days,),
    )
    return max(0, int(cursor.rowcount))


def _percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(quantile * len(ordered)) - 1)
    return round(ordered[index], 1)


def metrics(conn: psycopg.Connection, user_id: str | None = None) -> dict[str, Any]:
    """Retrieval health, for one user or for the whole instance.

    `user_id=None` means every user, which is the admin view; a member passes
    their own id and sees only their own runs. The parameter is cast in SQL
    because `%s IS NULL` alone leaves Postgres with no type to infer.
    """
    rows = conn.execute(
        """SELECT timings,abstained FROM retrieval_runs
            WHERE created_at >= now() - make_interval(days => 90)
              AND (%s::uuid IS NULL OR user_id = %s::uuid)""",
        (user_id, user_id),
    ).fetchall()
    latencies = [float((row["timings"] or {}).get("total_ms", 0.0)) for row in rows]
    total = len(rows)
    feedback = conn.execute(
        """SELECT count(*) AS labels,count(DISTINCT f.run_id) AS runs,
                  avg(f.useful::int) AS useful_rate,avg(f.correct::int) AS correct_rate
             FROM retrieval_run_feedback f JOIN retrieval_runs r ON r.id = f.run_id
            WHERE %s::uuid IS NULL OR r.user_id = %s::uuid""",
        (user_id, user_id),
    ).fetchone() or {"labels": 0, "runs": 0, "useful_rate": None, "correct_rate": None}
    return {
        "search_latency_ms": {
            "p50": _percentile(latencies, 0.50),
            "p95": _percentile(latencies, 0.95),
            "p99": _percentile(latencies, 0.99),
        },
        "retrieval_runs": total,
        "abstention_rate": (
            round(sum(1 for row in rows if row["abstained"]) / total, 4) if total else None
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
        "spend_by_user": spend_by_user(conn, user_id),
    }


def spend_by_user(conn: psycopg.Connection, user_id: str | None = None) -> list[dict[str, Any]]:
    """This month's model spend per person, most expensive first.

    Judge calls used to be one bill because there was one owner. With a team,
    "who is spending" is the question a budget alert has to answer, so the
    breakdown is joined against `users` and returns handles rather than bare
    ids.

    The month comes from `to_char(... AT TIME ZONE 'UTC')`: the column is
    `timestamptz`, so formatting it without a zone would bucket rows by whatever
    the session timezone happens to be and shift the month boundary per client.

    Runs with no `user_id` -- instance-level maintenance -- are excluded by the
    join, since there is nobody to attribute them to.
    """
    month = utcnow().strftime("%Y-%m")
    rows = conn.execute(
        """SELECT j.user_id,u.handle,u.display_name,
                  count(*) AS calls,
                  coalesce(sum(j.cost_usd),0) AS cost_usd,
                  coalesce(sum(j.input_tokens),0) AS input_tokens,
                  coalesce(sum(j.output_tokens),0) AS output_tokens
             FROM judge_runs j JOIN users u ON u.id = j.user_id
            WHERE to_char(j.created_at AT TIME ZONE 'UTC','YYYY-MM') = %s
              AND (%s::uuid IS NULL OR j.user_id = %s::uuid)
            GROUP BY j.user_id,u.handle,u.display_name
            ORDER BY cost_usd DESC,u.handle""",
        (month, user_id, user_id),
    ).fetchall()
    return [
        {
            "user_id": str(row["user_id"]),
            "handle": row["handle"],
            "display_name": row["display_name"],
            "calls": int(row["calls"]),
            # numeric arrives as Decimal, which json.dumps will not serialise.
            "cost_usd": round(float(row["cost_usd"]), 6),
            "input_tokens": int(row["input_tokens"]),
            "output_tokens": int(row["output_tokens"]),
        }
        for row in rows
    ]


def recent_runs(
    conn: psycopg.Connection,
    *,
    user_id: str,
    allowed_scope_ids: list[str],
    limit: int = 20,
) -> list[dict[str, Any]]:
    """The caller's recent runs, with result text only where they may read it.

    A run is the caller's own, but the memories it returned may since have moved
    out of reach -- a shared scope they left, or a scope whose membership was
    revoked. Such a result keeps its id, rank and scores and loses its text: the
    run happened, and hiding the row entirely would make the ranking history
    lie about what was ranked.
    """
    rows = conn.execute(
        """SELECT * FROM retrieval_runs WHERE user_id=%s
            ORDER BY created_at DESC,id DESC LIMIT %s""",
        (user_id, limit),
    ).fetchall()
    if not rows:
        return []
    results_by_run = {str(row["id"]): list(row["results"] or []) for row in rows}
    memory_ids = {
        str(result["memory_id"]) for results in results_by_run.values() for result in results
    }
    readable: dict[str, dict[str, Any]] = {}
    if memory_ids:
        readable = {
            str(row["id"]): dict(row)
            for row in conn.execute(
                """SELECT id,text,kind,source_role FROM memories
                    WHERE id = ANY(%s) AND scope_id = ANY(%s)""",
                (_as_uuids(sorted(memory_ids)), _as_uuids(allowed_scope_ids)),
            )
        }
    labels: dict[tuple[str, str], dict[str, Any]] = {
        (str(row["run_id"]), str(row["memory_id"])): {
            "useful": row["useful"],
            "correct": row["correct"],
            "created_at": iso(row["created_at"]),
        }
        for row in conn.execute(
            """SELECT run_id,memory_id,useful,correct,created_at
                 FROM retrieval_run_feedback WHERE run_id = ANY(%s)""",
            (_as_uuids(list(results_by_run)),),
        )
    }
    items: list[dict[str, Any]] = []
    for row in rows:
        run_id = str(row["id"])
        results = results_by_run[run_id]
        for result in results:
            memory_id = str(result["memory_id"])
            memory = readable.get(memory_id)
            if memory is not None:
                result.update(
                    {
                        "text": memory["text"],
                        "kind": memory["kind"],
                        "source_role": memory["source_role"],
                    }
                )
            result["feedback"] = labels.get((run_id, memory_id))
        items.append(
            {
                "id": run_id,
                "policy_id": row["policy_id"],
                "results": results,
                "timings": row["timings"] or {},
                "used_tokens": int(row["used_tokens"]),
                "abstained": bool(row["abstained"]),
                "created_at": iso(row["created_at"]),
            }
        )
    return items
