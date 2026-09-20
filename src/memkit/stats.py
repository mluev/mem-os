"""Pre-aggregated series for the dashboard.

Every function returns the same shape -- `{from, to, bucket, series, totals}`
where `series` is a flat list of `{date, key, value}` -- so the dashboard needs
one fetch hook and one chart wrapper rather than a bespoke pair per panel.

Aggregation is SQL, not Python. A month of judge runs is thousands of rows and
the answer is a few dozen numbers; sending the rows to a browser to be counted
there is how a monitoring page becomes the slowest screen in the product.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from statistics import median
from typing import Any

import psycopg

from .db import iso

# A day is the only bucket. An hour is noise at this volume, and a week hides
# the thing an operator is usually looking for, which is what changed
# yesterday.
BUCKET = "day"

GROUPINGS = {
    "kind": "m.kind",
    "scope": "e.name",
    "source_role": "m.source_role",
    "review_status": "m.review_status",
}


def _window(days: int) -> tuple[datetime, datetime]:
    now = datetime.now(UTC)
    return now - timedelta(days=days), now


def _envelope(
    start: datetime, end: datetime, series: list[dict[str, Any]], totals: dict[str, Any]
) -> dict[str, Any]:
    return {
        "from": iso(start),
        "to": iso(end),
        "bucket": BUCKET,
        "series": series,
        "totals": {key: _plain(value) for key, value in totals.items()},
    }


def _plain(value: Any) -> Any:
    """Postgres values in shapes JSON can carry.

    Recurses through lists and mappings: several totals are tables rather than
    numbers, and flattening one to `str` turns a chart's data into a string
    that renders as itself.
    """
    if isinstance(value, datetime):
        return iso(value)
    if isinstance(value, date):
        return value.isoformat()
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, list | tuple):
        return [_plain(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    try:
        return float(value)
    except (TypeError, ValueError):
        return str(value)


def _scopes(scope_ids: Sequence[str]) -> list[uuid.UUID]:
    return [uuid.UUID(str(scope)) for scope in scope_ids]


def _day(value: Any) -> str | None:
    """A bucket label: a calendar day, not an instant.

    Deliberately not `iso`, whose contract is a UTC timestamp. `::date` returns
    a date, and stamping a fake midnight on it would invite a reader to treat
    the bucket as a moment.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(UTC).date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _point(row: Any, key: str = "key", value: str = "value") -> dict[str, Any]:
    return {"date": _day(row["day"]), "key": str(row[key]), "value": _plain(row[value])}


def memories(
    conn: psycopg.Connection,
    *,
    scope_ids: Sequence[str],
    days: int = 30,
    group_by: str = "kind",
) -> dict[str, Any]:
    """New memories per day, grouped, plus what the store holds now.

    Two questions on one panel because each answers the other: a spike in new
    facts means little without the total it landed on.
    """
    if group_by not in GROUPINGS:
        raise ValueError(f"cannot group memories by {group_by!r}")
    start, end = _window(days)
    rows = conn.execute(
        f"""SELECT (m.created_at AT TIME ZONE 'UTC')::date AS day,
                   {GROUPINGS[group_by]} AS key, count(*) AS value
              FROM memories m JOIN entities e ON e.id = m.scope_id
             WHERE m.scope_id = ANY(%s) AND m.created_at >= %s
             GROUP BY day, key ORDER BY day, key""",
        (_scopes(scope_ids), start),
    ).fetchall()
    totals = conn.execute(
        """SELECT count(*) FILTER (WHERE status='active') AS active,
                  count(*) FILTER (WHERE status='active' AND review_status='pending')
                      AS pending,
                  count(*) FILTER (WHERE status='archived') AS archived,
                  count(*) FILTER (WHERE status='superseded') AS superseded,
                  count(*) FILTER (WHERE subject_id IS NOT NULL) AS about_someone
             FROM memories WHERE scope_id = ANY(%s)""",
        (_scopes(scope_ids),),
    ).fetchone()
    return _envelope(start, end, [_point(row) for row in rows], dict(totals or {}))


def pipeline(
    conn: psycopg.Connection, *, user_id: str | None = None, days: int = 30
) -> dict[str, Any]:
    """What extraction produced, what it refused, and what it cost.

    The acceptance rate is the number worth watching: applied over everything
    the model proposed. A falling rate means the prompt is drifting from what
    the store will accept, which is invisible in a raw operation count.
    """
    start, end = _window(days)
    series: list[dict[str, Any]] = []

    outcomes = conn.execute(
        """SELECT (finished_at AT TIME ZONE 'UTC')::date AS day,
                  sum(COALESCE((result->>'added')::int, 0)) AS added,
                  sum(COALESCE((result->>'updated')::int, 0)) AS updated,
                  sum(COALESCE((result->>'deleted')::int, 0)) AS deleted,
                  sum(COALESCE((result->>'rejected')::int, 0)) AS rejected,
                  sum(COALESCE((result->>'deduplicated')::int, 0)) AS deduplicated,
                  sum(COALESCE((result->>'unresolved_mentions')::int, 0)) AS unresolved
             FROM jobs
            WHERE kind='extraction' AND status='complete' AND finished_at >= %s
              AND (%s::uuid IS NULL OR user_id = %s::uuid)
            GROUP BY day ORDER BY day""",
        (start, user_id, user_id),
    ).fetchall()
    applied = proposed = 0
    for row in outcomes:
        day = _day(row["day"])
        wrote = int(row["added"] or 0) + int(row["updated"] or 0) + int(row["deleted"] or 0)
        noise = int(row["rejected"] or 0) + int(row["deduplicated"] or 0)
        applied += wrote
        proposed += wrote + noise
        for key, value in (
            ("added", row["added"]),
            ("updated", row["updated"]),
            ("deleted", row["deleted"]),
            ("rejected", row["rejected"]),
            ("deduplicated", row["deduplicated"]),
            ("unresolved", row["unresolved"]),
        ):
            series.append({"date": day, "key": key, "value": int(value or 0)})
        if wrote + noise:
            series.append(
                {"date": day, "key": "acceptance", "value": round(wrote / (wrote + noise), 4)}
            )

    spend = conn.execute(
        """SELECT (created_at AT TIME ZONE 'UTC')::date AS day, model AS key,
                  sum(cost_usd) AS cost, sum(input_tokens) AS input_tokens,
                  sum(output_tokens) AS output_tokens, count(*) AS calls,
                  count(*) FILTER (WHERE error IS NOT NULL) AS errors
             FROM judge_runs
            WHERE created_at >= %s AND (%s::uuid IS NULL OR user_id = %s::uuid)
            GROUP BY day, key ORDER BY day, key""",
        (start, user_id, user_id),
    ).fetchall()
    for row in spend:
        day = _day(row["day"])
        series.append({"date": day, "key": f"cost:{row['key']}", "value": _plain(row["cost"])})
        series.append(
            {
                "date": day,
                "key": "tokens",
                "value": int((row["input_tokens"] or 0) + (row["output_tokens"] or 0)),
            }
        )
        series.append({"date": day, "key": "calls", "value": int(row["calls"])})
        series.append({"date": day, "key": "errors", "value": int(row["errors"])})

    month = conn.execute(
        """SELECT COALESCE(sum(cost_usd), 0) AS spend,
                  count(*) AS calls,
                  count(*) FILTER (WHERE error IS NOT NULL) AS errors
             FROM judge_runs
            WHERE to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM')
                  = to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM')
              AND (%s::uuid IS NULL OR user_id = %s::uuid)""",
        (user_id, user_id),
    ).fetchone()
    reserved = conn.execute(
        """SELECT COALESCE(sum(reserved_usd), 0) AS reserved FROM budget_reservations
            WHERE status='active' AND period = to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM')"""
    ).fetchone()
    return _envelope(
        start,
        end,
        series,
        {
            "month_spend_usd": _plain((month or {}).get("spend")),
            "month_reserved_usd": _plain((reserved or {}).get("reserved")),
            "month_calls": int((month or {}).get("calls") or 0),
            "month_errors": int((month or {}).get("errors") or 0),
            "acceptance_rate": round(applied / proposed, 4) if proposed else None,
        },
    )


def retrieval(
    conn: psycopg.Connection, *, user_id: str | None = None, days: int = 30
) -> dict[str, Any]:
    """Search latency, abstention, and whether the results were any good.

    Percentiles are computed per day in Python from that day's durations: the
    rows are already bounded by telemetry retention, and a SQL percentile per
    bucket costs more to read than it saves.
    """
    start, end = _window(days)
    rows = conn.execute(
        """SELECT (created_at AT TIME ZONE 'UTC')::date AS day,
                  COALESCE((timings->>'total_ms')::float, 0) AS total_ms,
                  abstained
             FROM retrieval_runs
            WHERE created_at >= %s AND (%s::uuid IS NULL OR user_id = %s::uuid)
            ORDER BY day""",
        (start, user_id, user_id),
    ).fetchall()
    per_day: dict[str, list[float]] = {}
    abstained: dict[str, int] = {}
    for row in rows:
        day = _day(row["day"]) or ""
        per_day.setdefault(day, []).append(float(row["total_ms"]))
        abstained[day] = abstained.get(day, 0) + int(bool(row["abstained"]))
    series: list[dict[str, Any]] = []
    for day, durations in sorted(per_day.items()):
        ordered = sorted(durations)
        series.append({"date": day, "key": "p50", "value": round(median(ordered), 1)})
        index = max(0, int(len(ordered) * 0.95) - 1)
        series.append({"date": day, "key": "p95", "value": round(ordered[index], 1)})
        series.append({"date": day, "key": "searches", "value": len(ordered)})
        series.append(
            {
                "date": day,
                "key": "abstention",
                "value": round(abstained.get(day, 0) / len(ordered), 4),
            }
        )

    # Labels reach their user through the run they belong to; the feedback row
    # itself carries no user, which is what keeps one label per (run, memory).
    feedback = conn.execute(
        """SELECT (f.created_at AT TIME ZONE 'UTC')::date AS day,
                  count(*) FILTER (WHERE f.useful) AS useful,
                  count(*) FILTER (WHERE NOT f.useful) AS not_useful
             FROM retrieval_run_feedback f
             JOIN retrieval_runs r ON r.id = f.run_id
            WHERE f.created_at >= %s AND (%s::uuid IS NULL OR r.user_id = %s::uuid)
            GROUP BY day ORDER BY day""",
        (start, user_id, user_id),
    ).fetchall()
    for row in feedback:
        day = _day(row["day"])
        series.append({"date": day, "key": "useful", "value": int(row["useful"] or 0)})
        series.append({"date": day, "key": "not_useful", "value": int(row["not_useful"] or 0)})

    everything = sorted(float(row["total_ms"]) for row in rows)
    return _envelope(
        start,
        end,
        series,
        {
            "searches": len(everything),
            "p50_ms": round(median(everything), 1) if everything else None,
            "p95_ms": round(everything[max(0, int(len(everything) * 0.95) - 1)], 1)
            if everything
            else None,
            "abstention_rate": round(sum(abstained.values()) / len(everything), 4)
            if everything
            else None,
        },
    )


def review(
    conn: psycopg.Connection, *, scope_ids: Sequence[str], user_id: str, days: int = 30
) -> dict[str, Any]:
    """The backlog of things waiting on a person, and how it got that way.

    Opened against closed per day, so a queue that is growing looks different
    from one that is merely large.
    """
    start, end = _window(days)
    series: list[dict[str, Any]] = []
    # Everything that ever needed a decision: still pending, or already
    # decided. The earlier version counted every memory created, so a day on
    # which nothing needed review still towered over the decisions made.
    opened = conn.execute(
        """SELECT (created_at AT TIME ZONE 'UTC')::date AS day, count(*) AS value
             FROM memories
            WHERE scope_id = ANY(%s) AND created_at >= %s
              AND (review_status = 'pending' OR reviewed_at IS NOT NULL)
            GROUP BY day ORDER BY day""",
        (_scopes(scope_ids), start),
    ).fetchall()
    for row in opened:
        series.append({"date": _day(row["day"]), "key": "opened", "value": int(row["value"])})
    closed = conn.execute(
        """SELECT (reviewed_at AT TIME ZONE 'UTC')::date AS day,
                  review_status AS key, count(*) AS value
             FROM memories
            WHERE scope_id = ANY(%s) AND reviewed_at >= %s
            GROUP BY day, key ORDER BY day, key""",
        (_scopes(scope_ids), start),
    ).fetchall()
    for row in closed:
        series.append(_point(row))

    by_reason = conn.execute(
        """SELECT source_role AS key, count(*) AS value FROM memories
            WHERE scope_id = ANY(%s) AND status='active' AND review_status='pending'
            GROUP BY key ORDER BY value DESC""",
        (_scopes(scope_ids),),
    ).fetchall()
    attention = conn.execute(
        """SELECT kind AS key, count(*) AS value FROM needs_attention
            WHERE user_id=%s AND status='open' GROUP BY key""",
        (user_id,),
    ).fetchall()
    pending = conn.execute(
        """SELECT count(*) AS n FROM memories
            WHERE scope_id = ANY(%s) AND status='active' AND review_status='pending'""",
        (_scopes(scope_ids),),
    ).fetchone()
    oldest = conn.execute(
        """SELECT min(created_at) AS oldest FROM memories
            WHERE scope_id = ANY(%s) AND status='active' AND review_status='pending'""",
        (_scopes(scope_ids),),
    ).fetchone()
    return _envelope(
        start,
        end,
        series,
        {
            "pending": int((pending or {}).get("n") or 0),
            "oldest_pending": _plain((oldest or {}).get("oldest")),
            "pending_by_source": {str(row["key"]): int(row["value"]) for row in by_reason},
            "attention_by_kind": {str(row["key"]): int(row["value"]) for row in attention},
        },
    )


def entities(
    conn: psycopg.Connection, *, scope_ids: Sequence[str], limit: int = 10
) -> dict[str, Any]:
    """Where memory actually accumulates, and what the team talks about.

    Two counts per entity, because they mean different things: memories held in
    its scope, and memories about it recorded elsewhere.
    """
    start, end = _window(0)
    rows = conn.execute(
        """SELECT e.slug, e.name, e.kind,
                  count(*) FILTER (WHERE m.scope_id = e.id AND m.status='active') AS in_scope,
                  count(*) FILTER (WHERE m.subject_id = e.id AND m.status='active') AS about,
                  max(m.updated_at) AS last_activity,
                  (SELECT count(*) FROM memberships mm WHERE mm.entity_id = e.id) AS members
             FROM entities e
             LEFT JOIN memories m
                    ON (m.scope_id = e.id OR m.subject_id = e.id)
                   AND m.scope_id = ANY(%s)
            WHERE e.archived_at IS NULL
            GROUP BY e.id, e.slug, e.name, e.kind
            HAVING count(m.id) > 0
            ORDER BY count(m.id) DESC
            LIMIT %s""",
        (_scopes(scope_ids), limit),
    ).fetchall()
    return _envelope(
        start,
        end,
        [
            {
                "date": iso(row["last_activity"]),
                "key": str(row["slug"]),
                "value": int(row["in_scope"]) + int(row["about"]),
            }
            for row in rows
        ],
        {
            "entities": [
                {
                    "slug": row["slug"],
                    "name": row["name"],
                    "kind": row["kind"],
                    "in_scope": int(row["in_scope"]),
                    "about": int(row["about"]),
                    "members": int(row["members"]),
                    "last_activity": iso(row["last_activity"]),
                }
                for row in rows
            ]
        },
    )


def users(conn: psycopg.Connection, *, days: int = 30) -> dict[str, Any]:
    """Per-person activity and spend. Administrators only.

    Included because a shared instance has a shared bill and a shared review
    queue, and neither is actionable without knowing whose work they are.
    """
    start, end = _window(days)
    rows = conn.execute(
        """SELECT (m.created_at AT TIME ZONE 'UTC')::date AS day, u.handle AS key,
                  count(*) AS value
             FROM memories m JOIN users u ON u.id = m.author_id
            WHERE m.created_at >= %s
            GROUP BY day, key ORDER BY day, key""",
        (start,),
    ).fetchall()
    # Two counts per person, and the column names say which is which: a table
    # headed by a range that reports all-time numbers is worse than no table.
    people = conn.execute(
        """SELECT u.handle, u.display_name, u.role, u.disabled_at,
                  (SELECT count(*) FROM memories m
                    WHERE m.author_id = u.id AND m.created_at >= %(start)s) AS memories,
                  (SELECT count(*) FROM sessions s
                    WHERE s.user_id = u.id AND s.started_at >= %(start)s) AS sessions,
                  (SELECT count(*) FROM retrieval_runs r
                    WHERE r.user_id = u.id AND r.created_at >= %(start)s) AS searches,
                  (SELECT count(*) FROM memories m WHERE m.author_id = u.id)
                      AS memories_all_time,
                  (SELECT COALESCE(sum(j.cost_usd), 0) FROM judge_runs j
                    WHERE j.user_id = u.id
                      AND to_char(j.created_at AT TIME ZONE 'UTC', 'YYYY-MM')
                          = to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM')) AS month_spend_usd,
                  (SELECT max(k.last_used_at) FROM api_keys k WHERE k.user_id = u.id)
                      AS key_last_used_at
             FROM users u ORDER BY u.handle""",
        {"start": start},
    ).fetchall()
    return _envelope(
        start,
        end,
        [_point(row) for row in rows],
        {
            "people": [
                {
                    "handle": row["handle"],
                    "display_name": row["display_name"],
                    "role": row["role"],
                    "disabled": bool(row["disabled_at"]),
                    "memories": int(row["memories"]),
                    "memories_all_time": int(row["memories_all_time"]),
                    "sessions": int(row["sessions"]),
                    "searches": int(row["searches"]),
                    "month_spend_usd": _plain(row["month_spend_usd"]),
                    "key_last_used_at": iso(row["key_last_used_at"]),
                }
                for row in people
            ]
        },
    )
