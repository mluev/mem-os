"""Durable background jobs, leases, and cost reservations."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .db import connect, transaction, utcnow


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


def claim(
    conn: sqlite3.Connection,
    job_id: str,
    *,
    holder: str | None = None,
    lease_seconds: int = 120,
) -> sqlite3.Row:
    now = utcnow()
    holder = holder or f"worker:{uuid.uuid4()}"
    expires = (
        (datetime.now(UTC) + timedelta(seconds=lease_seconds))
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )
    with transaction(conn):
        changed = conn.execute(
            """UPDATE jobs SET status='running',started_at=COALESCE(started_at,?),updated_at=?,
                               holder=?,lease_expires_at=?,attempts=attempts+1
                WHERE id=? AND status='queued'""",
            (now, now, holder, expires, job_id),
        ).rowcount
    if not changed:
        raise RuntimeError("job is not queued")
    with transaction(conn):
        conn.execute(
            "INSERT INTO job_events(job_id,status,created_at) VALUES (?,'running',?)",
            (job_id, now),
        )
    return get(conn, job_id)


def renew(
    conn: sqlite3.Connection,
    job_id: str,
    *,
    holder: str,
    lease_seconds: int = 120,
) -> bool:
    expires = (
        (datetime.now(UTC) + timedelta(seconds=lease_seconds))
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )
    with transaction(conn):
        changed = conn.execute(
            """UPDATE jobs SET lease_expires_at=?,updated_at=?
                 WHERE id=? AND status='running' AND holder=?""",
            (expires, utcnow(), job_id, holder),
        ).rowcount
    return bool(changed)


@contextmanager
def heartbeat(
    conn: sqlite3.Connection,
    job_id: str,
    *,
    holder: str,
    interval_seconds: int = 30,
    lease_seconds: int = 120,
):
    """Renew a running job lease from an independent SQLite connection."""
    path = Path(str(conn.execute("PRAGMA database_list").fetchone()[2]))
    stop = threading.Event()

    def beat() -> None:
        heartbeat_conn = connect(path)
        try:
            while not stop.wait(interval_seconds):
                if not renew(
                    heartbeat_conn,
                    job_id,
                    holder=holder,
                    lease_seconds=lease_seconds,
                ):
                    return
        finally:
            heartbeat_conn.close()

    thread = threading.Thread(target=beat, name=f"memkit-heartbeat-{job_id[:8]}", daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=2)


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
                              finished_at=?,updated_at=?,holder=NULL,lease_expires_at=NULL
                 WHERE id=?""",
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


def recover_stale(conn: sqlite3.Connection) -> dict[str, int]:
    """Requeue abandoned jobs and release their unreconciled spend reservations."""
    now = utcnow()
    conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    try:
        stale_ids = [
            row[0]
            for row in conn.execute(
                """SELECT id FROM jobs WHERE status='running'
                     AND (lease_expires_at IS NULL OR lease_expires_at<=?)""",
                (now,),
            ).fetchall()
        ]
        released_for_stale = 0
        released_claims = 0
        if stale_ids:
            placeholders = ",".join("?" for _ in stale_ids)
            released_for_stale = conn.execute(
                f"""UPDATE budget_reservations SET status='released',actual_usd=0,updated_at=?
                      WHERE status='active' AND job_id IN ({placeholders})""",
                (now, *stale_ids),
            ).rowcount
            conn.execute(
                f"""UPDATE jobs SET status='queued',holder=NULL,lease_expires_at=NULL,
                                      updated_at=?
                      WHERE id IN ({placeholders})""",
                (now, *stale_ids),
            )
            conn.executemany(
                """INSERT INTO job_events(job_id,status,detail_json,created_at)
                   VALUES (?,'recovered','{}',?)""",
                [(job_id, now) for job_id in stale_ids],
            )
            released_claims = conn.execute(
                f"""UPDATE messages SET claim_token=NULL,claim_expires_at=NULL
                       WHERE processed=0 AND EXISTS (
                           SELECT 1 FROM jobs j WHERE j.id IN ({placeholders})
                             AND messages.claim_token LIKE j.id || ':%'
                       )""",
                stale_ids,
            ).rowcount
        released = conn.execute(
            """UPDATE budget_reservations SET status='released',actual_usd=0,updated_at=?
                 WHERE status='active' AND job_id IS NOT NULL
                   AND job_id IN (SELECT id FROM jobs WHERE status!='running')""",
            (now,),
        ).rowcount
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return {
        "jobs": len(stale_ids),
        "reservations": int(released_for_stale) + int(released),
        "message_claims": int(released_claims),
    }


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
