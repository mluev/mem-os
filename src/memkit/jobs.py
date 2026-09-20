"""Durable background jobs, leases, and cost reservations."""

from __future__ import annotations

import json
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from .db import ConnectionPool, Row, advisory_lock, transaction, utcnow


class BudgetExceeded(RuntimeError):
    pass


class CallLimitExceeded(RuntimeError):
    pass


def _job_row(row: Row) -> Row:
    """A job row with the encoded JSON columns the old readers still expect.

    `input` and `result` are jsonb and come back already decoded, but several
    callers were written against the SQLite columns `input_json`/`result_json`
    and decode them themselves. Carrying the encoded strings alongside the
    decoded values keeps those readers working, so the port does not have to
    land in every handler at once.
    """
    enriched = Row(row)
    enriched["input_json"] = json.dumps(row.get("input") or {}, ensure_ascii=False, sort_keys=True)
    result = row.get("result")
    enriched["result_json"] = (
        None if result is None else json.dumps(result, ensure_ascii=False, sort_keys=True)
    )
    return enriched


def _job_uuid(job_id: str) -> str:
    """Reject a malformed id before Postgres sees it.

    `jobs.id` is a uuid column, so a non-uuid string is a type error rather
    than a miss. Callers expect a lookup for an id that cannot exist to raise
    KeyError, as it did when ids were text.
    """
    try:
        return str(uuid.UUID(str(job_id)))
    except ValueError as exc:
        raise KeyError(job_id) from exc


def create(
    conn: psycopg.Connection,
    *,
    kind: str,
    input_data: dict[str, Any] | None = None,
    call_limit: int = 0,
    user_id: str | None = None,
) -> str:
    job_id = str(uuid.uuid4())
    now = utcnow()
    with transaction(conn):
        conn.execute(
            """INSERT INTO jobs
               (id,user_id,kind,status,input,call_limit,created_at,updated_at)
               VALUES (%s,%s,%s,'queued',%s,%s,%s,%s)""",
            (job_id, user_id, kind, Jsonb(input_data or {}), call_limit, now, now),
        )
        conn.execute(
            "INSERT INTO job_events(job_id,status,created_at) VALUES (%s,'queued',%s)",
            (job_id, now),
        )
    return job_id


def get(conn: psycopg.Connection, job_id: str) -> Row:
    row = conn.execute("SELECT * FROM jobs WHERE id=%s", (_job_uuid(job_id),)).fetchone()
    if row is None:
        raise KeyError(job_id)
    return _job_row(row)


def claim(
    conn: psycopg.Connection,
    job_id: str,
    *,
    holder: str | None = None,
    lease_seconds: int = 120,
) -> Row:
    """Take a queued job, or refuse because someone else already has it.

    One statement does the whole claim: the row is picked and locked by the
    subquery and written by the same UPDATE, so two workers cannot both see it
    queued. SKIP LOCKED makes the loser fail immediately instead of waiting
    for a lease it will not get. This is what SQLite needed BEGIN IMMEDIATE
    for.
    """
    now = utcnow()
    holder = holder or f"worker:{uuid.uuid4()}"
    expires = now + timedelta(seconds=lease_seconds)
    row = conn.execute(
        """UPDATE jobs SET status='running',started_at=COALESCE(started_at,%s),updated_at=%s,
                           holder=%s,lease_expires_at=%s,attempts=attempts+1
            WHERE id = (SELECT id FROM jobs WHERE id=%s AND status='queued'
                          FOR UPDATE SKIP LOCKED)
         RETURNING *""",
        (now, now, holder, expires, job_id),
    ).fetchone()
    if row is None:
        raise RuntimeError("job is not queued")
    conn.execute(
        "INSERT INTO job_events(job_id,status,created_at) VALUES (%s,'running',%s)",
        (job_id, now),
    )
    return _job_row(row)


def renew(
    conn: psycopg.Connection,
    job_id: str,
    *,
    holder: str,
    lease_seconds: int = 120,
) -> bool:
    now = utcnow()
    changed = conn.execute(
        """UPDATE jobs SET lease_expires_at=%s,updated_at=%s
             WHERE id=%s AND status='running' AND holder=%s""",
        (now + timedelta(seconds=lease_seconds), now, job_id, holder),
    ).rowcount
    return bool(changed)


@contextmanager
def heartbeat(
    conn: psycopg.Connection,
    job_id: str,
    *,
    holder: str,
    interval_seconds: int = 30,
    lease_seconds: int = 120,
    pool: ConnectionPool | None = None,
) -> Iterator[None]:
    """Renew a running job lease from a connection of its own.

    The renewal must not share the connection running the job: that one may be
    inside a transaction for minutes, and a lease extended from within it
    would be undone by a rollback -- besides serialising the beat behind the
    work. With a pool the beat borrows a connection per renewal and returns it
    at once; without one it falls back to the caller's connection, which is
    what a single-connection setup has and what tests use.
    """
    stop = threading.Event()

    def renew_once() -> bool:
        if pool is None:
            return renew(conn, job_id, holder=holder, lease_seconds=lease_seconds)
        with pool.borrow() as beat_conn:
            return renew(beat_conn, job_id, holder=holder, lease_seconds=lease_seconds)

    def beat() -> None:
        while not stop.wait(interval_seconds):
            if not renew_once():
                return

    thread = threading.Thread(target=beat, name=f"memkit-heartbeat-{job_id[:8]}", daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=2)


def request_cancel(conn: psycopg.Connection, job_id: str) -> None:
    now = utcnow()
    with transaction(conn):
        changed = conn.execute(
            """UPDATE jobs SET cancel_requested=true,updated_at=%s
                WHERE id=%s AND status IN ('queued','running')""",
            (now, job_id),
        ).rowcount
        if not changed:
            raise RuntimeError("job cannot be cancelled")
        conn.execute(
            """INSERT INTO job_events(job_id,status,detail,created_at)
               VALUES (%s,'cancellation_requested',%s,%s)""",
            (job_id, Jsonb({}), now),
        )


def cancel_requested(conn: psycopg.Connection, job_id: str) -> bool:
    return bool(get(conn, job_id)["cancel_requested"])


def finish(
    conn: psycopg.Connection,
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
            """UPDATE jobs SET status=%s,result=%s,error_code=%s,error=%s,
                              finished_at=%s,updated_at=%s,holder=NULL,lease_expires_at=NULL
                 WHERE id=%s""",
            (
                status,
                Jsonb(result) if result is not None else None,
                error_code,
                error,
                now,
                now,
                job_id,
            ),
        )
        conn.execute(
            """INSERT INTO job_events(job_id,status,detail,created_at)
               VALUES (%s,%s,%s,%s)""",
            (
                job_id,
                status,
                Jsonb({"error_code": error_code, "error": error} if error else {}),
                now,
            ),
        )


def consume_call(conn: psycopg.Connection, job_id: str) -> int:
    """Atomically consume one provider call from a running job.

    The guard lives in the WHERE clause, so the read and the increment cannot
    be split: two threads asking at once get one grant each until the limit is
    reached, and the loser sees no row. `call_limit=0` still means unlimited,
    which is what jobs created without a limit rely on. The follow-up SELECT
    only decides which refusal to report.
    """
    row = conn.execute(
        """UPDATE jobs SET calls_completed=calls_completed+1,updated_at=%s
             WHERE id=%s AND status='running'
               AND (call_limit=0 OR calls_completed<call_limit)
         RETURNING calls_completed""",
        (utcnow(), job_id),
    ).fetchone()
    if row is None:
        current = conn.execute("SELECT status FROM jobs WHERE id=%s", (job_id,)).fetchone()
        if current is None or current["status"] != "running":
            raise CallLimitExceeded("job is not running")
        raise CallLimitExceeded("job provider call limit reached")
    return int(row["calls_completed"])


def history(conn: psycopg.Connection, job_id: str) -> list[dict[str, Any]]:
    return [
        {
            **dict(row),
            "detail": row["detail"],
            # Same reason as `_job_row`: readers written against the SQLite
            # column still decode the string themselves.
            "detail_json": json.dumps(row["detail"] or {}, ensure_ascii=False, sort_keys=True),
        }
        for row in conn.execute("SELECT * FROM job_events WHERE job_id=%s ORDER BY id", (job_id,))
    ]


def reserve_budget(
    conn: psycopg.Connection,
    *,
    period: str,
    amount_usd: float,
    limit_usd: float,
    job_id: str | None = None,
    user_id: str | None = None,
) -> str:
    if amount_usd < 0:
        raise ValueError("budget reservation must be non-negative")
    reservation_id = str(uuid.uuid4())
    now = utcnow()
    with transaction(conn):
        # The advisory lock serialises the read-plus-insert across processes,
        # as BEGIN IMMEDIATE did: without it two workers read the same spend,
        # both find room under the ceiling, and both reserve.
        advisory_lock(conn, f"budget:{period}")
        # The period is a UTC month everywhere it is produced, so the column is
        # read in UTC rather than in whatever the session timezone happens to
        # be -- otherwise the first hours of a month land in the previous one.
        spent = float(
            conn.execute(
                """SELECT COALESCE(SUM(cost_usd),0) AS total FROM judge_runs
                    WHERE to_char(created_at AT TIME ZONE 'UTC','YYYY-MM')=%s""",
                (period,),
            ).fetchone()["total"]
        )
        reserved = float(
            conn.execute(
                """SELECT COALESCE(SUM(reserved_usd),0) AS total FROM budget_reservations
                    WHERE period=%s AND status='active'""",
                (period,),
            ).fetchone()["total"]
        )
        if spent + reserved + amount_usd > limit_usd + 1e-12:
            raise BudgetExceeded(
                f"cost ceiling exceeded: {spent + reserved + amount_usd:.6f} > {limit_usd:.6f}"
            )
        conn.execute(
            """INSERT INTO budget_reservations
               (id,job_id,user_id,period,reserved_usd,status,created_at,updated_at)
               VALUES (%s,%s,%s,%s,%s,'active',%s,%s)""",
            (reservation_id, job_id, user_id, period, amount_usd, now, now),
        )
    return reservation_id


def reconcile_budget(conn: psycopg.Connection, reservation_id: str, *, actual_usd: float) -> None:
    changed = conn.execute(
        """UPDATE budget_reservations
              SET actual_usd=%s,status='reconciled',updated_at=%s
            WHERE id=%s AND status='active'""",
        (actual_usd, utcnow(), reservation_id),
    ).rowcount
    if not changed:
        raise RuntimeError("unknown or inactive budget reservation")


def release_budget(conn: psycopg.Connection, reservation_id: str) -> None:
    changed = conn.execute(
        """UPDATE budget_reservations
              SET actual_usd=0,status='released',updated_at=%s
            WHERE id=%s AND status='active'""",
        (utcnow(), reservation_id),
    ).rowcount
    if not changed:
        raise RuntimeError("unknown or inactive budget reservation")


def recover_stale(conn: psycopg.Connection) -> dict[str, int]:
    """Requeue abandoned jobs and release their unreconciled spend reservations."""
    now = utcnow()
    with transaction(conn):
        # Picking and requeueing in one statement is what makes a second
        # recovery running at the same time harmless: the rows it would take
        # are locked, and SKIP LOCKED leaves them to whoever got there first
        # instead of double-counting them.
        stale_ids = [
            str(row["id"])
            for row in conn.execute(
                """UPDATE jobs SET status='queued',holder=NULL,lease_expires_at=NULL,
                                   updated_at=%s
                    WHERE id IN (SELECT id FROM jobs WHERE status='running'
                                   AND (lease_expires_at IS NULL OR lease_expires_at<=%s)
                                 FOR UPDATE SKIP LOCKED)
                 RETURNING id""",
                (now, now),
            ).fetchall()
        ]
        released_for_stale = 0
        released_claims = 0
        if stale_ids:
            released_for_stale = conn.execute(
                """UPDATE budget_reservations SET status='released',actual_usd=0,updated_at=%s
                     WHERE status='active' AND job_id = ANY(%s::uuid[])""",
                (now, stale_ids),
            ).rowcount
            conn.execute(
                """INSERT INTO job_events(job_id,status,detail,created_at)
                   SELECT id,'recovered',%s,%s FROM unnest(%s::uuid[]) AS t(id)""",
                (Jsonb({}), now, stale_ids),
            )
            # The claim token is "<job id>:<token>", so a job's claims are the
            # rows whose token starts with its id. The literal per-cent has to
            # be doubled: this query carries parameters, and psycopg reads a
            # single one as a placeholder.
            released_claims = conn.execute(
                """UPDATE messages SET claim_token=NULL,claim_expires_at=NULL
                     WHERE NOT processed AND EXISTS (
                         SELECT 1 FROM jobs j WHERE j.id = ANY(%s::uuid[])
                           AND messages.claim_token LIKE j.id::text || ':%%'
                     )""",
                (stale_ids,),
            ).rowcount
        released = conn.execute(
            """UPDATE budget_reservations SET status='released',actual_usd=0,updated_at=%s
                 WHERE status='active' AND job_id IS NOT NULL
                   AND job_id IN (SELECT id FROM jobs WHERE status!='running')""",
            (now,),
        ).rowcount
    return {
        "jobs": len(stale_ids),
        "reservations": int(released_for_stale) + int(released),
        "message_claims": int(released_claims),
    }


def acquire_lease(conn: psycopg.Connection, *, name: str, holder: str, ttl_seconds: int) -> bool:
    """Take a named lease unless a different holder still owns a live one.

    The upsert's WHERE clause is the whole test, so the decision and the write
    are one statement: renewing our own lease and taking over an expired one
    both succeed, a live lease held by someone else returns no row.
    """
    now = utcnow()
    row = conn.execute(
        """INSERT INTO leases(name,holder,expires_at,updated_at) VALUES (%s,%s,%s,%s)
           ON CONFLICT (name) DO UPDATE SET holder=excluded.holder,
               expires_at=excluded.expires_at,updated_at=excluded.updated_at
             WHERE leases.holder=excluded.holder OR leases.expires_at<=excluded.updated_at
           RETURNING name""",
        (name, holder, now + timedelta(seconds=ttl_seconds), now),
    ).fetchone()
    return row is not None


def release_lease(conn: psycopg.Connection, *, name: str, holder: str) -> None:
    conn.execute("DELETE FROM leases WHERE name=%s AND holder=%s", (name, holder))
