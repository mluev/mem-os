"""One database gate for memory writes, index rebuilds and erasure.

Normal mutations hold a shared transaction lock. Maintenance holds an exclusive
session lock on its working connection, leaving no transaction open while models
or external stores run. All callers acquire this gate before scope or row locks.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from functools import wraps
from typing import Any

import psycopg
from psycopg.pq import TransactionStatus

_LOCK = "memkit:memory-maintenance"


class MaintenanceBusy(Exception):
    """Memory maintenance or an in-flight writer requires a retry."""


def require_write(conn: psycopg.Connection) -> None:
    """Join the write gate until the caller's transaction ends; never wait."""
    if conn.info.transaction_status != TransactionStatus.INTRANS:
        raise RuntimeError("memory writes require an explicit transaction")
    row = conn.execute(
        "SELECT pg_try_advisory_xact_lock_shared(hashtext(%s)) AS ok", (_LOCK,)
    ).fetchone()
    if not row["ok"]:
        raise MaintenanceBusy("memory maintenance is in progress; retry shortly")


@contextmanager
def shared(conn: psycopg.Connection) -> Iterator[None]:
    """Protect an export including its file write without a long transaction."""
    row = conn.execute(
        "SELECT pg_try_advisory_lock_shared(hashtext(%s)) AS ok", (_LOCK,)
    ).fetchone()
    if not row["ok"]:
        raise MaintenanceBusy("memory maintenance is in progress; retry shortly")
    try:
        yield
    finally:
        if not conn.closed:
            conn.execute("SELECT pg_advisory_unlock_shared(hashtext(%s))", (_LOCK,))


@contextmanager
def exclusive(conn: psycopg.Connection) -> Iterator[None]:
    """Freeze writers using the same connection that performs maintenance."""
    if conn.info.transaction_status != TransactionStatus.IDLE:
        raise RuntimeError("maintenance must start outside a transaction")
    row = conn.execute("SELECT pg_try_advisory_lock(hashtext(%s)) AS ok", (_LOCK,)).fetchone()
    if not row["ok"]:
        raise MaintenanceBusy("memory writes or maintenance are in progress; retry shortly")
    try:
        yield
    finally:
        if not conn.closed:
            conn.execute("SELECT pg_advisory_unlock(hashtext(%s))", (_LOCK,))


def write_transaction(operation: Callable[..., Any]) -> Callable[..., Any]:
    """Make a store operation atomic for both standalone and nested callers."""

    @wraps(operation)
    def write(conn: psycopg.Connection, *args: Any, **kwargs: Any) -> Any:
        with conn.transaction():
            require_write(conn)
            return operation(conn, *args, **kwargs)

    return write
