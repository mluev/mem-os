"""Failure-oriented tests for redaction, outbox, jobs, leases and budgets."""

from __future__ import annotations

import json
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from memkit import jobs, judge, outbox, providers, security, store, vectors
from memkit.db import connect, transaction
from tests.fixtures import OWNER, StubEmbedder, StubQdrant, make_db


class TestRedaction(unittest.TestCase):
    def test_secret_is_removed_before_any_boundary(self) -> None:
        raw = "use API_KEY=super-secret-value and ghp_abcdefghijklmnopqrstuvwxyz1234567890"
        result = security.redact(raw)
        self.assertTrue(result.redacted)
        self.assertNotIn("super-secret-value", result.text)
        self.assertNotIn("ghp_", result.text)
        self.assertGreaterEqual(result.count, 2)


class TestOutbox(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = make_db()
        self.qdrant = StubQdrant()
        self.embedder = StubEmbedder()

    def test_rollback_never_reaches_qdrant(self) -> None:
        with self.assertRaises(RuntimeError), transaction(self.conn):
            outbox.enqueue(
                self.conn,
                collection=vectors.MEMORIES,
                entity_id="m-1",
                operation="upsert",
                payload={"text": "durable fact", "owner_id": "u-test"},
            )
            raise RuntimeError("forced rollback")
        outbox.drain(self.conn, self.qdrant, self.embedder)
        self.assertNotIn("m-1", self.qdrant.points)

    def test_commit_leaves_retryable_work_after_index_failure(self) -> None:
        with transaction(self.conn):
            memory_id = store.add_memory(
                self.conn,
                owner_id=OWNER,
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
            "SELECT status,attempts,last_error FROM index_outbox WHERE entity_id=?",
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
        self.conn = make_db()

    def test_budget_reservations_cannot_cross_hard_limit(self) -> None:
        first = jobs.reserve_budget(self.conn, period="2026-08", amount_usd=0.7, limit_usd=1.0)
        self.assertIsNotNone(first)
        with self.assertRaises(jobs.BudgetExceeded):
            jobs.reserve_budget(self.conn, period="2026-08", amount_usd=0.31, limit_usd=1.0)
        total = self.conn.execute(
            "SELECT SUM(reserved_usd) FROM budget_reservations WHERE status='active'"
        ).fetchone()[0]
        self.assertAlmostEqual(total, 0.7)

    def test_parallel_reservations_are_serialized(self) -> None:
        path = Path(self.conn.execute("PRAGMA database_list").fetchone()[2])
        barrier = threading.Barrier(2)
        outcomes: list[str] = []

        def reserve() -> None:
            conn = connect(path)
            barrier.wait()
            try:
                jobs.reserve_budget(conn, period="2026-08", amount_usd=0.6, limit_usd=1.0)
                outcomes.append("reserved")
            except jobs.BudgetExceeded:
                outcomes.append("rejected")
            finally:
                conn.close()

        threads = [threading.Thread(target=reserve) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertCountEqual(outcomes, ["reserved", "rejected"])

    def test_slow_provider_does_not_hold_a_sqlite_write_transaction(self) -> None:
        path = Path(self.conn.execute("PRAGMA database_list").fetchone()[2])
        provider_entered = threading.Event()
        provider_release = threading.Event()
        completed: list[object] = []

        def slow_provider(**_kwargs):
            provider_entered.set()
            provider_release.wait(timeout=5)
            return providers.ProviderResult(raw={"operations": []})

        def call_judge() -> None:
            conn = connect(path)
            completed.append(
                judge.extract(
                    conn,
                    window=[{"id": 1, "role": "user", "content": "remember tea"}],
                    candidates=[],
                    monthly_limit_usd=1,
                    owner_id=OWNER,
                )
            )
            conn.close()

        with patch("memkit.providers.call", side_effect=slow_provider):
            thread = threading.Thread(target=call_judge)
            thread.start()
            self.assertTrue(provider_entered.wait(timeout=2))
            other = connect(path)
            with transaction(other):
                store.add_memory(
                    other,
                    owner_id=OWNER,
                    text="Concurrent durable write",
                    kind="observation",
                )
            other.close()
            provider_release.set()
            thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(completed), 1)

    def test_job_lifecycle_and_cooperative_cancel(self) -> None:
        job_id = jobs.create(self.conn, kind="reindex", input_data={"reason": "test"}, call_limit=1)
        claimed = jobs.claim(self.conn, job_id)
        self.assertEqual(claimed["status"], "running")
        jobs.consume_call(self.conn, job_id)
        with self.assertRaises(jobs.CallLimitExceeded):
            jobs.consume_call(self.conn, job_id)
        jobs.request_cancel(self.conn, job_id)
        self.assertTrue(jobs.cancel_requested(self.conn, job_id))
        jobs.finish(self.conn, job_id, status="cancelled", result={"safe": True})
        row = jobs.get(self.conn, job_id)
        self.assertEqual(row["status"], "cancelled")
        self.assertEqual(json.loads(row["result_json"]), {"safe": True})
        self.assertEqual(
            [event["status"] for event in jobs.history(self.conn, job_id)],
            ["queued", "running", "cancellation_requested", "cancelled"],
        )


if __name__ == "__main__":
    unittest.main()
