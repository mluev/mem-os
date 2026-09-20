"""Concurrency contracts at the HTTP and durable-work boundaries."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import patch

import anyio
import httpx
import pytest
from fastapi import Depends, FastAPI

from memkit import api, jobs, worker
from memkit.db import ConnectionPool
from tests.fixtures import StubEmbedder, StubQdrant


def test_overlapping_requests_never_share_a_connection(database_url):
    application = FastAPI()
    pool = ConnectionPool(database_url, max_size=2)
    application.state.db = pool

    async def exercise():
        # Force dependency setup through one worker thread. Thread-local storage
        # then incorrectly gives both overlapping requests the same connection.
        limiter = anyio.to_thread.current_default_thread_limiter()
        limiter.total_tokens = 1
        arrived = 0
        both = asyncio.Event()

        @application.get("/")
        async def endpoint(conn=Depends(api.get_conn)):
            nonlocal arrived
            arrived += 1
            if arrived == 2:
                both.set()
            await asyncio.wait_for(both.wait(), 2)
            return {"pid": conn.execute("SELECT pg_backend_pid() AS pid").fetchone()["pid"]}

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application), base_url="http://test"
        ) as client:
            first, second = await asyncio.gather(client.get("/"), client.get("/"))
            assert first.json()["pid"] != second.json()["pid"]
        assert pool._pool.get_stats()["pool_available"] == 2

    try:
        asyncio.run(exercise())
    finally:
        pool.close_all()


def test_expired_holder_cannot_renew(clean_database):
    conn = clean_database
    job_id = jobs.create(conn, kind="test")
    jobs.claim(conn, job_id, holder="old", lease_seconds=-1)
    assert jobs.renew(conn, job_id, holder="old") is False


def test_standalone_heartbeat_reconnects_with_original_database_credentials(clean_database):
    conn = clean_database
    job_id = jobs.create(conn, kind="test")
    claimed = jobs.claim(conn, job_id, holder="standalone", lease_seconds=2)
    with jobs.heartbeat(
        conn, job_id, holder="standalone", interval_seconds=0.01, lease_seconds=60
    ) as lost:
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and not lost.wait(0.01):
            current = jobs.get(conn, job_id)
            if current["lease_expires_at"] > claimed["lease_expires_at"]:
                break
        assert not lost.is_set()
        assert jobs.get(conn, job_id)["lease_expires_at"] > claimed["lease_expires_at"]


def test_stale_completion_cannot_overwrite_reclaimed_job(clean_database):
    conn = clean_database
    job_id = jobs.create(conn, kind="test")
    jobs.claim(conn, job_id, holder="old", lease_seconds=-1)
    jobs.recover_stale(conn)
    jobs.claim(conn, job_id, holder="new")
    with pytest.raises(jobs.LeaseLost):
        jobs.finish(conn, job_id, holder="old", status="failed")
    jobs.finish(conn, job_id, holder="new", status="complete")
    with pytest.raises(jobs.LeaseLost):
        jobs.finish(conn, job_id, holder="new", status="failed")
    assert jobs.get(conn, job_id)["status"] == "complete"
    assert [row["status"] for row in jobs.history(conn, job_id)][-1] == "complete"


def test_worker_recovers_after_restart_even_when_qdrant_is_down(database_url, clean_database):
    conn = clean_database
    job_id = jobs.create(conn, kind="test")
    jobs.claim(conn, job_id, holder="dead", lease_seconds=1)
    pool = ConnectionPool(database_url, max_size=2)
    instance = worker.Worker(pool, StubQdrant(), StubEmbedder(), lambda *_: None, poll_seconds=0.01)
    try:
        with (
            patch("memkit.worker.vectors.ensure_collections", side_effect=OSError("offline")),
            patch("memkit.worker.DEGRADED_POLL_SECONDS", 0.02),
        ):
            instance.start()
            deadline = time.monotonic() + 3
            while jobs.get(conn, job_id)["status"] == "running" and time.monotonic() < deadline:
                time.sleep(0.02)
            assert jobs.get(conn, job_id)["status"] == "queued"
    finally:
        instance.stop()
        pool.close_all()


def test_requests_beyond_pool_capacity_complete_and_return_connections(database_url):
    import threading

    application = FastAPI()
    pool = ConnectionPool(database_url, max_size=2)
    application.state.db = pool
    active = maximum = 0
    lock = threading.Lock()

    @application.get("/")
    def endpoint(conn=Depends(api.get_conn)):
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
        try:
            with conn.transaction():
                conn.execute("SELECT pg_sleep(0.02)")
            return {"ok": True}
        finally:
            with lock:
                active -= 1

    async def exercise():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application), base_url="http://test"
        ) as client:
            responses = await asyncio.wait_for(
                asyncio.gather(*(client.get("/") for _ in range(12))), timeout=5
            )
        assert all(response.status_code == 200 for response in responses)
        assert maximum == 2
        assert pool._pool.get_stats()["pool_available"] == 2

    try:
        asyncio.run(exercise())
    finally:
        pool.close_all()


def test_cancelled_reindex_is_recorded_as_cancelled(database_url, clean_database):
    from types import SimpleNamespace

    from memkit import job_runner, reindex

    conn = clean_database
    job_id = jobs.create(conn, kind="reindex")
    pool = ConnectionPool(database_url, max_size=2)
    application = SimpleNamespace(state=SimpleNamespace(db=pool))
    try:
        with patch("memkit.job_runner._execute", side_effect=reindex.ReindexCancelled("cancelled")):
            job_runner.run(application, job_id)
        assert jobs.get(conn, job_id)["status"] == "cancelled"
    finally:
        pool.close_all()


def test_inline_drain_maintenance_does_not_mark_index_unhealthy():
    from contextlib import nullcontext
    from types import SimpleNamespace

    from memkit import maintenance
    from memkit.http import _drain

    state = SimpleNamespace(
        index_ready=True,
        db=SimpleNamespace(borrow=lambda: nullcontext(None)),
        qdrant=StubQdrant(),
        embedder=StubEmbedder(),
    )
    request = SimpleNamespace(app=SimpleNamespace(state=state))
    with patch("memkit.http.outbox.drain", side_effect=maintenance.MaintenanceBusy("rebuilding")):
        _drain(request)
    assert state.index_ready is True


def test_cancelled_extraction_does_not_queue_more_work(database_url, clean_database):
    from types import SimpleNamespace
    from unittest.mock import Mock

    from memkit import extract, job_runner

    conn = clean_database
    job_id = jobs.create(
        conn, kind="extraction", input_data={"session_id": "cancelled", "agent_id": "agent"}
    )
    pool = ConnectionPool(database_url, max_size=2)
    application = SimpleNamespace(
        state=SimpleNamespace(db=pool, qdrant=StubQdrant(), embedder=StubEmbedder(), worker=Mock())
    )

    def extraction(*args, **kwargs):
        jobs.request_cancel(conn, job_id)
        return extract.ExtractionOutcome(claimed=10)

    try:
        with (
            patch("memkit.job_runner.extract.run_session_extraction", side_effect=extraction),
            patch("memkit.job_runner.extract.messages_since_last", return_value=50),
        ):
            job_runner.run(application, job_id)
        assert jobs.get(conn, job_id)["status"] == "cancelled"
        assert conn.execute("SELECT count(*) AS n FROM jobs").fetchone()["n"] == 1
    finally:
        pool.close_all()


def test_process_death_releases_maintenance_and_rolls_back_partial_write(
    database_url, clean_database
):
    import select
    import subprocess
    import sys

    from memkit import maintenance
    from tests.fixtures import seed_team

    conn = clean_database
    team = seed_team(conn)
    job_id = jobs.create(conn, kind="reindex")
    program = """
import sys, time
from memkit import jobs, maintenance, store
from memkit.db import connect
conn = connect(sys.argv[1])
jobs.claim(conn, sys.argv[2], holder='crashed-worker')
with maintenance.exclusive(conn):
    with conn.transaction():
        store.add_memory(conn, scope_id=sys.argv[3], author_id=sys.argv[4],
                         text='uncommitted crashed write', kind='fact', source_role='manual')
        print('mutation-open', flush=True)
        time.sleep(30)
"""
    process = subprocess.Popen(  # noqa: S603 -- fixed code against a disposable test database
        [
            sys.executable,
            "-c",
            program,
            database_url,
            job_id,
            team.scope_of("alice"),
            team.alice_id,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert select.select([process.stdout], [], [], 10)[0], "child did not reach crash boundary"
        assert process.stdout.readline().strip() == "mutation-open"
        process.kill()
        process.communicate(timeout=5)
        # PostgreSQL releases the killed process's session gate and transaction.
        with maintenance.exclusive(conn):
            assert (
                conn.execute(
                    "SELECT count(*) AS n FROM memories WHERE text='uncommitted crashed write'"
                ).fetchone()["n"]
                == 0
            )
        conn.execute(
            "UPDATE jobs SET lease_expires_at=now()-interval '1 second' WHERE id=%s", (job_id,)
        )
        jobs.recover_stale(conn)
        assert jobs.get(conn, job_id)["status"] == "queued"
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=5)
