"""Failure-oriented tests for redaction, the outbox, jobs, leases and budgets.

Every case here is a way the system loses or duplicates work when something
goes wrong at the worst moment: a transaction rolls back after the index was
told about a row, an index write fails after the store committed, two workers
reserve the same money, or a slow provider call is made while holding a write
transaction and stalls every other writer behind it.
"""

from __future__ import annotations

import os
import threading
import unittest
from unittest.mock import patch

from memkit import jobs, judge, outbox, providers, security, store, vectors
from memkit.db import connect, transaction
from tests.fixtures import StubEmbedder, StubQdrant, make_db, seed_team


def _database_url() -> str:
    return os.environ["MEMKIT_DATABASE_URL"]


class TestRedaction(unittest.TestCase):
    def test_a_secret_is_removed_before_any_boundary(self) -> None:
        """Redaction is central because every boundary is a different module."""
        raw = "use API_KEY=super-secret-value and ghp_abcdefghijklmnopqrstuvwxyz1234567890"
        result = security.redact(raw)
        self.assertTrue(result.redacted)
        self.assertNotIn("super-secret-value", result.text)
        self.assertNotIn("ghp_", result.text)
        self.assertGreaterEqual(result.count, 2)


class TestOutbox(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = make_db(seed=False)
        self.team = seed_team(self.conn)
        self.scope_id = self.team.scope_of("alice")
        self.qdrant = StubQdrant()
        self.embedder = StubEmbedder()

    def test_a_rolled_back_write_never_reaches_the_index(self) -> None:
        """The whole reason the handoff is a table row and not a call.

        Enqueueing inside the caller's transaction means an index write cannot
        outlive the store write that justified it.
        """
        with self.assertRaises(RuntimeError), transaction(self.conn):
            outbox.enqueue(
                self.conn,
                collection=vectors.MEMORIES,
                entity_id="m-1",
                operation="upsert",
                payload={"text": "durable fact"},
            )
            raise RuntimeError("forced rollback")
        outbox.drain(self.conn, self.qdrant, self.embedder)
        self.assertNotIn("m-1", self.qdrant.points)

    def test_a_committed_write_survives_an_index_failure_and_is_retried(self) -> None:
        """The other half: the store is authoritative and the index catches up.

        A failed delivery stays pending with its attempt counted and its error
        recorded, so an outage is visible and self-healing rather than a silent
        hole in the index.
        """
        with transaction(self.conn):
            memory_id = store.add_memory(
                self.conn,
                scope_id=self.scope_id,
                author_id=self.team.alice_id,
                text="durable fact",
                kind="fact",
                source_role="manual",
            )

        class BrokenQdrant(StubQdrant):
            def upsert(self, *args, **kwargs):
                raise RuntimeError("offline")

        outcome = outbox.drain(self.conn, BrokenQdrant(), self.embedder)
        self.assertEqual(outcome.failed, 1)
        row = self.conn.execute(
            "SELECT status,attempts,last_error FROM index_outbox WHERE entity_id=%s",
            (memory_id,),
        ).fetchone()
        self.assertEqual(row["status"], "pending")
        self.assertEqual(row["attempts"], 1)
        self.assertIn("offline", row["last_error"])

        outcome = outbox.drain(self.conn, self.qdrant, self.embedder, ignore_schedule=True)
        self.assertEqual(outcome.applied, 1)
        self.assertIn(memory_id, self.qdrant.points)


class TestJobsAndBudgets(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = make_db(seed=False)
        self.team = seed_team(self.conn)

    def test_reservations_cannot_be_talked_past_the_hard_limit(self) -> None:
        """Spend is reserved before the call, not counted after it."""
        first = jobs.reserve_budget(
            self.conn,
            period="2026-08",
            amount_usd=0.7,
            limit_usd=1.0,
            user_id=self.team.alice_id,
        )
        self.assertIsNotNone(first)
        with self.assertRaises(jobs.BudgetExceeded):
            jobs.reserve_budget(
                self.conn,
                period="2026-08",
                amount_usd=0.31,
                limit_usd=1.0,
                user_id=self.team.alice_id,
            )
        total = self.conn.execute(
            "SELECT SUM(reserved_usd) AS total FROM budget_reservations WHERE status='active'"
        ).fetchone()["total"]
        self.assertAlmostEqual(float(total), 0.7)

    def test_two_workers_reserving_at_once_produce_one_winner(self) -> None:
        """The ceiling is a race, and the advisory lock is what settles it.

        Both connections read the same spend, so without serialisation both
        find room under the limit and both reserve past it.
        """
        barrier = threading.Barrier(2)
        outcomes: list[str] = []
        lock = threading.Lock()

        def reserve() -> None:
            conn = connect(_database_url())
            barrier.wait()
            try:
                jobs.reserve_budget(conn, period="2026-08", amount_usd=0.6, limit_usd=1.0)
                verdict = "reserved"
            except jobs.BudgetExceeded:
                verdict = "rejected"
            finally:
                conn.close()
            with lock:
                outcomes.append(verdict)

        threads = [threading.Thread(target=reserve) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        self.assertCountEqual(outcomes, ["reserved", "rejected"])

    def test_a_slow_provider_call_does_not_hold_a_write_transaction(self) -> None:
        """A model call takes seconds; a write transaction must not.

        The budget reservation and the run row are each their own transaction
        with the network call in between. If the call were inside one of them,
        every other writer would queue behind the slowest model response.
        """
        provider_entered = threading.Event()
        provider_release = threading.Event()
        completed: list[object] = []

        def slow_provider(**_kwargs):
            provider_entered.set()
            provider_release.wait(timeout=5)
            return providers.ProviderResult(raw={"operations": []})

        def call_judge() -> None:
            conn = connect(_database_url())
            completed.append(
                judge.extract(
                    conn,
                    window=[{"id": 1, "role": "user", "content": "remember tea"}],
                    candidates=[],
                    monthly_limit_usd=1,
                    user_id=self.team.alice_id,
                )
            )
            conn.close()

        with patch("memkit.providers.call", side_effect=slow_provider):
            thread = threading.Thread(target=call_judge)
            thread.start()
            self.assertTrue(provider_entered.wait(timeout=5))
            other = connect(_database_url())
            with transaction(other):
                store.add_memory(
                    other,
                    scope_id=self.team.scope_of("alice"),
                    author_id=self.team.alice_id,
                    text="Concurrent durable write",
                    kind="observation",
                )
            other.close()
            provider_release.set()
            thread.join(timeout=10)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(completed), 1)

    def test_a_job_records_every_state_it_passed_through(self) -> None:
        """Cancellation is cooperative, so the trail is the only proof it worked."""
        job_id = jobs.create(
            self.conn,
            kind="reindex",
            input_data={"reason": "test"},
            call_limit=1,
            user_id=self.team.alice_id,
        )
        claimed = jobs.claim(self.conn, job_id)
        self.assertEqual(claimed["status"], "running")
        self.assertEqual(claimed["input"], {"reason": "test"})
        jobs.consume_call(self.conn, job_id)
        with self.assertRaises(jobs.CallLimitExceeded):
            jobs.consume_call(self.conn, job_id)
        jobs.request_cancel(self.conn, job_id)
        self.assertTrue(jobs.cancel_requested(self.conn, job_id))
        jobs.finish(self.conn, job_id, status="cancelled", result={"safe": True})
        row = jobs.get(self.conn, job_id)
        self.assertEqual(row["status"], "cancelled")
        self.assertEqual(row["result"], {"safe": True})
        self.assertEqual(
            [event["status"] for event in jobs.history(self.conn, job_id)],
            ["queued", "running", "cancellation_requested", "cancelled"],
        )

    def test_a_named_lease_is_held_by_one_holder_until_it_expires(self) -> None:
        """Singleton background work depends on this and nothing else."""
        self.assertTrue(
            jobs.acquire_lease(self.conn, name="sweeper", holder="first", ttl_seconds=60)
        )
        self.assertFalse(
            jobs.acquire_lease(self.conn, name="sweeper", holder="second", ttl_seconds=60)
        )
        self.assertTrue(
            jobs.acquire_lease(self.conn, name="sweeper", holder="first", ttl_seconds=60)
        )
        jobs.release_lease(self.conn, name="sweeper", holder="first")
        self.assertTrue(
            jobs.acquire_lease(self.conn, name="sweeper", holder="second", ttl_seconds=60)
        )


if __name__ == "__main__":
    unittest.main()
