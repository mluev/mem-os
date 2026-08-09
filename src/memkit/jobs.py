"""Durable background jobs, leases, and cost reservations."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from .db import transaction, utcnow


class BudgetExceeded(RuntimeError):
    pass


class CallLimitExceeded(RuntimeError):
    pass


def create(
    conn: sqlite3.Connection,
    *,
    kind: str,
    input_data: dict[str, Any] | None = None,
    call_limit: int = 0,
) -> str:
    job_id = str(uuid.uuid4())
    now = utcnow()
    with transaction(conn):
        conn.execute(
            """INSERT INTO jobs
               (id,kind,status,input_json,call_limit,created_at,updated_at)
               VALUES (?,?,'queued',?,?,?,?)""",
            (
                job_id,
                kind,
                json.dumps(input_data or {}, ensure_ascii=False, sort_keys=True),
                call_limit,
                now,
                now,
            ),
        )
        conn.execute(
            "INSERT INTO job_events(job_id,status,created_at) VALUES (?,'queued',?)",
            (job_id, now),
        )
    return job_id


def get(conn: sqlite3.Connection, job_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if row is None:
        raise KeyError(job_id)
    return row


def claim(conn: sqlite3.Connection, job_id: str) -> sqlite3.Row:
    now = utcnow()
    with transaction(conn):
        changed = conn.execute(
            """UPDATE jobs SET status='running',started_at=?,updated_at=?
                WHERE id=? AND status='queued'""",
            (now, now, job_id),
        ).rowcount
    if not changed:
        raise RuntimeError("job is not queued")
    with transaction(conn):
        conn.execute(
            "INSERT INTO job_events(job_id,status,created_at) VALUES (?,'running',?)",
            (job_id, now),
        )
    return get(conn, job_id)


def request_cancel(conn: sqlite3.Connection, job_id: str) -> None:
    with transaction(conn):
        changed = conn.execute(
            """UPDATE jobs SET cancel_requested=1,updated_at=?
                WHERE id=? AND status IN ('queued','running')""",
            (utcnow(), job_id),
        ).rowcount
    if not changed:
        raise RuntimeError("job cannot be cancelled")
    with transaction(conn):
        conn.execute(
            """INSERT INTO job_events(job_id,status,detail_json,created_at)
               VALUES (?,'cancellation_requested','{}',?)""",
            (job_id, utcnow()),
        )


def cancel_requested(conn: sqlite3.Connection, job_id: str) -> bool:
    return bool(get(conn, job_id)["cancel_requested"])


def finish(
    conn: sqlite3.Connection,
    job_id: str,
    *,
    status: str,
    result: dict[str, Any] | None = None,
    error_code: str | None = None,
    error: str | None = None,
) -> None:
    if status not in {"complete", "failed", "cancelled"}:
        raise ValueError("invalid terminal job status")
    now = utcnow()
    with transaction(conn):
        conn.execute(
            """UPDATE jobs SET status=?,result_json=?,error_code=?,error=?,
                              finished_at=?,updated_at=? WHERE id=?""",
            (
                status,
                json.dumps(result, ensure_ascii=False, sort_keys=True)
                if result is not None
                else None,
                error_code,
                error,
                now,
                now,
                job_id,
            ),
        )
        conn.execute(
            """INSERT INTO job_events(job_id,status,detail_json,created_at)
               VALUES (?,?,?,?)""",
            (
                job_id,
                status,
                json.dumps(
                    {"error_code": error_code, "error": error} if error else {},
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                now,
            ),
        )


def consume_call(conn: sqlite3.Connection, job_id: str) -> int:
    """Atomically consume one provider call from a running job."""
    conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute(
            "SELECT status,call_limit,calls_completed FROM jobs WHERE id=?", (job_id,)
        ).fetchone()
        if row is None or row["status"] != "running":
            raise CallLimitExceeded("job is not running")
        if row["call_limit"] and row["calls_completed"] >= row["call_limit"]:
            raise CallLimitExceeded("job provider call limit reached")
        completed = int(row["calls_completed"]) + 1
        conn.execute(
            "UPDATE jobs SET calls_completed=?,updated_at=? WHERE id=?",
            (completed, utcnow(), job_id),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return completed


def history(conn: sqlite3.Connection, job_id: str) -> list[dict[str, Any]]:
    return [
        {**dict(row), "detail": json.loads(row["detail_json"])}
        for row in conn.execute("SELECT * FROM job_events WHERE job_id=? ORDER BY id", (job_id,))
    ]


def reserve_budget(
    conn: sqlite3.Connection,
    *,
    period: str,
    amount_usd: float,
    limit_usd: float,
    job_id: str | None = None,
) -> str:
    if amount_usd < 0:
        raise ValueError("budget reservation must be non-negative")
    reservation_id = str(uuid.uuid4())
    now = utcnow()
    # BEGIN IMMEDIATE serialises the read-plus-insert across processes.
    conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    try:
        spent = float(
            conn.execute(
                """SELECT COALESCE(SUM(cost_usd),0) FROM judge_runs
                    WHERE substr(created_at,1,7)=?""",
                (period,),
            ).fetchone()[0]
        )
        reserved = float(
            conn.execute(
                """SELECT COALESCE(SUM(reserved_usd),0) FROM budget_reservations
                    WHERE period=? AND status='active'""",
                (period,),
            ).fetchone()[0]
        )
        if spent + reserved + amount_usd > limit_usd + 1e-12:
            raise BudgetExceeded(
                f"cost ceiling exceeded: {spent + reserved + amount_usd:.6f} > {limit_usd:.6f}"
            )
        conn.execute(
            """INSERT INTO budget_reservations
               (id,job_id,period,reserved_usd,status,created_at,updated_at)
               VALUES (?,?,?,?,'active',?,?)""",
            (reservation_id, job_id, period, amount_usd, now, now),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return reservation_id


def reconcile_budget(conn: sqlite3.Connection, reservation_id: str, *, actual_usd: float) -> None:
    with transaction(conn):
        changed = conn.execute(
            """UPDATE budget_reservations
                  SET actual_usd=?,status='reconciled',updated_at=?
                WHERE id=? AND status='active'""",
            (actual_usd, utcnow(), reservation_id),
        ).rowcount
    if not changed:
        raise RuntimeError("unknown or inactive budget reservation")


def release_budget(conn: sqlite3.Connection, reservation_id: str) -> None:
    with transaction(conn):
        changed = conn.execute(
            """UPDATE budget_reservations
                  SET actual_usd=0,status='released',updated_at=?
                WHERE id=? AND status='active'""",
            (utcnow(), reservation_id),
        ).rowcount
    if not changed:
        raise RuntimeError("unknown or inactive budget reservation")


def acquire_lease(conn: sqlite3.Connection, *, name: str, holder: str, ttl_seconds: int) -> bool:
    now = datetime.now(UTC)
    expires = (
        (now + timedelta(seconds=ttl_seconds)).isoformat(timespec="seconds").replace("+00:00", "Z")
    )
    now_text = now.isoformat(timespec="seconds").replace("+00:00", "Z")
    with transaction(conn):
        row = conn.execute("SELECT holder,expires_at FROM leases WHERE name=?", (name,)).fetchone()
        if row and row["holder"] != holder and row["expires_at"] > now_text:
            return False
        conn.execute(
            """INSERT INTO leases(name,holder,expires_at,updated_at) VALUES (?,?,?,?)
               ON CONFLICT(name) DO UPDATE SET holder=excluded.holder,
                   expires_at=excluded.expires_at,updated_at=excluded.updated_at""",
            (name, holder, expires, now_text),
        )
    return True


def release_lease(conn: sqlite3.Connection, *, name: str, holder: str) -> None:
    with transaction(conn):
        conn.execute("DELETE FROM leases WHERE name=? AND holder=?", (name, holder))
