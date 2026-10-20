"""Dynamic dreaming and the daily maintenance pass (decisions/0085).

Dreaming used to run after every extraction that wrote something, so each dream
saw one window's worth of memories. Dynamic mode waits until a scope goes
quiet, a session closes, or a batch piles up, and a periodic tick decides.
These tests pin the decision itself -- what is due and what waits -- and the
two things it may not break: a dream's supersession is visible and
reversible, and the daily pass needs no actor and spends nothing.
"""

from __future__ import annotations

import unittest
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from psycopg.types.json import Jsonb

from memkit import config, dream, job_runner, jobs, store
from memkit.db import ConnectionPool, utcnow
from tests import test_dream
from tests.fixtures import StubEmbedder, StubQdrant, make_session, seed_team
from tests.httpharness import test_settings as offline_settings

IDLE = {"idle_minutes": 15, "batch": 20, "min_interval_minutes": 30}


@pytest.fixture
def system(database_url, clean_database, monkeypatch):
    conn = clean_database
    team = seed_team(conn)
    settings = offline_settings()
    monkeypatch.setattr(config, "_settings", settings)
    pool = ConnectionPool(database_url, max_size=3)
    app = SimpleNamespace(
        state=SimpleNamespace(db=pool, qdrant=StubQdrant(), embedder=StubEmbedder(), worker=Mock())
    )
    try:
        yield conn, team, app, monkeypatch
    finally:
        pool.close_all()


def add(conn, team, text: str, *, minutes_ago: float = 0, role: str = "user", scope=None) -> str:
    memory_id = store.add_memory(
        conn,
        scope_id=scope or team.scope_of("alice"),
        author_id=team.alice_id,
        text=text,
        kind="fact",
        source_role=role,
    )
    conn.execute(
        "UPDATE memories SET updated_at = now() - make_interval(secs => %s) WHERE id=%s",
        (minutes_ago * 60, memory_id),
    )
    return memory_id


def dreamt(conn, team, *, through: str | None, finished_minutes_ago: float) -> None:
    """Record a completed dream whose watermark reaches `through`."""
    watermark = None
    if through is not None:
        row = conn.execute("SELECT updated_at FROM memories WHERE id=%s", (through,)).fetchone()
        watermark = {"at": row["updated_at"].isoformat(), "id": through}
    job_id = jobs.create(
        conn,
        kind="dream",
        input_data={"scope_id": team.scope_of("alice"), "dry_run": False},
        user_id=team.alice_id,
    )
    conn.execute(
        """UPDATE jobs SET status='complete', result=%s,
                  finished_at = now() - make_interval(secs => %s) WHERE id=%s""",
        (Jsonb({"watermark": watermark}), finished_minutes_ago * 60, job_id),
    )


def judged(monkeypatch, **changes):
    settings = config.get_settings().model_copy(update={"gemini_api_key": "test", **changes})
    monkeypatch.setattr(config, "_settings", settings)
    return settings


def test_a_quiet_scope_is_due_and_a_busy_one_waits(system):
    conn, team, _, _ = system
    memory = add(conn, team, "Alice lives in Lisbon")
    assert dream.due_scopes(conn, **IDLE) == []
    conn.execute(
        "UPDATE memories SET updated_at = now() - interval '20 minutes' WHERE id=%s", (memory,)
    )
    [due] = dream.due_scopes(conn, **IDLE)
    assert (due.scope_id, due.user_id, due.fresh, due.reason) == (
        team.scope_of("alice"),
        team.alice_id,
        1,
        "idle",
    )


def test_a_full_batch_is_due_even_while_the_scope_is_busy(system):
    conn, team, _, _ = system
    for n in range(3):
        add(conn, team, f"Alice owns plant number {n}")
    [due] = dream.due_scopes(conn, idle_minutes=15, batch=3, min_interval_minutes=30)
    assert due.reason == "batch"


def test_a_scope_that_just_dreamt_waits_out_the_interval(system):
    conn, team, _, _ = system
    covered = add(conn, team, "Alice lives in Porto", minutes_ago=60)
    add(conn, team, "Alice lives in Lisbon", minutes_ago=20)
    dreamt(conn, team, through=covered, finished_minutes_ago=5)
    assert dream.due_scopes(conn, **IDLE) == []
    assert len(dream.due_scopes(conn, **{**IDLE, "min_interval_minutes": 0})) == 1


def test_what_a_dream_covered_is_never_due_again(system):
    conn, team, _, _ = system
    last = add(conn, team, "Alice lives in Lisbon", minutes_ago=60)
    dreamt(conn, team, through=last, finished_minutes_ago=50)
    assert dream.due_scopes(conn, **IDLE) == []


def test_only_stated_memories_make_a_scope_due(system):
    conn, team, _, _ = system
    add(conn, team, "Alice probably likes the coast", minutes_ago=60, role="inference")
    add(
        conn, team, "The assistant recommended Hotel Lisboa Plaza", minutes_ago=60, role="assistant"
    )
    assert dream.due_scopes(conn, **IDLE) == []


def test_a_disabled_author_is_never_the_actor(system):
    conn, team, _, _ = system
    add(conn, team, "Alice lives in Lisbon", minutes_ago=60)
    conn.execute("UPDATE users SET disabled_at=now() WHERE id=%s", (team.alice_id,))
    assert dream.due_scopes(conn, **IDLE) == []


def test_the_tick_queues_one_dream_only_in_dynamic_mode_with_a_judge(system):
    conn, team, app, monkeypatch = system
    add(conn, team, "Alice lives in Lisbon", minutes_ago=60)
    assert job_runner.tick(app, conn)["dream_job_ids"] == []
    judged(monkeypatch, dreaming="after_extraction")
    assert job_runner.tick(app, conn)["dream_job_ids"] == []
    judged(monkeypatch, dreaming="dynamic")
    [queued] = job_runner.tick(app, conn)["dream_job_ids"]
    assert jobs.get(conn, queued)["input"]["scope_id"] == team.scope_of("alice")
    # The next tick finds the dream already waiting.
    assert job_runner.tick(app, conn)["dream_job_ids"] == []


def test_daily_maintenance_is_scheduled_once_a_day_without_an_actor(system):
    conn, _, app, monkeypatch = system
    assert job_runner.tick(app, conn)["maintenance_job_id"] is None
    judged(monkeypatch, maintenance="daily")
    first = job_runner.tick(app, conn)["maintenance_job_id"]
    assert first is not None
    assert job_runner.tick(app, conn)["maintenance_job_id"] is None
    job = jobs.get(conn, first)
    assert job["user_id"] is None
    assert (job["input"]["scheduled"], job["input"]["merge"], job["call_limit"]) == (True, False, 0)
    conn.execute("UPDATE jobs SET created_at = now() - interval '25 hours' WHERE id=%s", (first,))
    assert job_runner.tick(app, conn)["maintenance_job_id"] not in (None, first)


def test_the_scheduled_pass_expires_lapsed_memories_and_merges_nothing(system):
    conn, team, app, monkeypatch = system
    judged(monkeypatch, maintenance="daily")
    lapsed = store.add_memory(
        conn,
        scope_id=team.project_id,
        author_id=team.bob_id,
        text="The offsite is booked until Friday",
        kind="fact",
        valid_until=utcnow() - timedelta(days=1),
    )
    twin_a = add(conn, team, "Alice prefers tea", minutes_ago=60)
    twin_b = add(conn, team, "Alice likes tea", minutes_ago=50)
    job_id = job_runner.schedule_maintenance(conn)
    job_runner.run(app, job_id)
    job = jobs.get(conn, job_id)
    assert job["status"] == "complete", job
    status = {
        str(row["id"]): row["status"]
        for row in conn.execute(
            "SELECT id,status FROM memories WHERE id = ANY(%s)", ([lapsed, twin_a, twin_b],)
        )
    }
    assert status == {lapsed: "expired", twin_a: "active", twin_b: "active"}
    assert conn.execute("SELECT COUNT(*) AS n FROM judge_runs").fetchone()["n"] == 0


def test_a_closed_session_dreams_the_scopes_its_memories_live_in(system):
    conn, team, _, _ = system
    make_session(conn, team, session_id="trip")
    message, _, _ = store.add_message(
        conn,
        session_id="trip",
        user_id=team.alice_id,
        scope_id=team.scope_of("alice"),
        agent_id="chat",
        role="user",
        content="I moved to Lisbon in March",
    )
    memory = add(conn, team, "Alice moved to Lisbon in 2026-03")
    conn.execute(
        """INSERT INTO memory_evidence (memory_id,message_id,start_char,end_char,excerpt_sha256)
           VALUES (%s,%s,0,10,'x')""",
        (memory, message),
    )
    [queued] = job_runner._queue_session_dreams(conn, session_id="trip", user_id=team.alice_id)
    assert jobs.get(conn, queued)["input"]["scope_id"] == team.scope_of("alice")
    assert job_runner._queue_session_dreams(conn, session_id="trip", user_id=team.alice_id) == []


class DreamReviewTest(unittest.TestCase):
    """A dream's supersession applies at once and is listed for a person."""

    # DreamTest's harness, borrowed rather than inherited so its own tests do
    # not run a second time from this module.
    setUp = test_dream.DreamTest.setUp
    tearDown = test_dream.DreamTest.tearDown
    add = test_dream.DreamTest.add
    dream = test_dream.DreamTest.dream
    row = test_dream.DreamTest.row

    def test_a_dream_supersession_is_queued_for_review_and_restorable(self) -> None:
        porto = self.add("Alice lives in Porto", "2026-01-05T00:00:00Z")
        lisbon = self.add("Alice lives in Lisbon", "2026-04-02T00:00:00Z")
        outcome = self.dream(
            lambda n: {
                "links": [
                    {
                        "from": n["Alice lives in Lisbon"],
                        "to": n["Alice lives in Porto"],
                        "relation": "updates",
                        "reason": "moved",
                    }
                ],
                "inferences": [],
            },
        )
        self.assertEqual(outcome.superseded, 1)
        self.assertTrue(outcome.caught_up)
        item = self.conn.execute("SELECT * FROM needs_attention WHERE kind='conflict'").fetchone()
        self.assertEqual(str(item["ref_memory_id"]), porto)
        self.assertEqual(str(item["user_id"]), self.team.alice_id)
        self.assertEqual(item["payload"]["source"], "dream")
        self.assertEqual(item["payload"]["replaced_by"], lisbon)
        with self.conn.transaction():
            store.set_memory_status(
                self.conn, memory_id=porto, scopes=[self.scope], status="active"
            )
        self.assertEqual(self.row(porto)["status"], "active")

    def test_a_dry_run_has_not_caught_up(self) -> None:
        self.add("Alice lives in Porto", "2026-01-05T00:00:00Z")
        self.add("Alice lives in Lisbon", "2026-04-02T00:00:00Z")
        self.assertFalse(self.dream(lambda n: {}, dry_run=True).caught_up)

    def test_an_empty_scope_has_caught_up(self) -> None:
        self.assertTrue(self.dream(lambda n: {}).caught_up)
