"""Regressions that only showed up under interleaving, restart, or retry.

Each of these reproduces a bug that survived a green suite once: a queued index
write that was silently overwritten while it was being delivered, a claim whose
holder died and took the row with it, an erasure racing a delivery that could
put the vector back, two jobs paying for the same conversation window, and a
correction that reported success while writing the wrong revision.
"""

from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from memkit import extract, jobs, outbox, privacy, store, vectors
from memkit.db import connect, transaction
from tests.fixtures import StubEmbedder, StubQdrant, add_messages, make_db, seed_team
from tests.httpharness import ApiTestCase


class FilterAwareQdrant(StubQdrant):
    """StubQdrant that also understands the filter erasure deletes by.

    Erasure deletes by predicate rather than by enumerating ids, precisely so
    it cannot race a concurrent delivery. A stub that only accepts a list of
    ids would make that call look like a no-op and quietly pass the test it is
    supposed to be checking.
    """

    def delete(self, collection_name, points_selector, wait=True):
        condition = getattr(points_selector, "filter", None)
        if condition is None:
            super().delete(collection_name, points_selector, wait=wait)
            return
        collection = self._col(collection_name)
        for point_id, payload in list(collection.items()):
            if all(payload.get(item.key) == item.match.value for item in (condition.must or [])):
                self.deleted.append(point_id)
                collection.pop(point_id, None)


class OutboxDeliveryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = make_db(seed=False)
        self.team = seed_team(self.conn)
        self.scope_id = self.team.scope_of("alice")

    def test_a_newer_write_never_mutates_a_claimed_delivery(self) -> None:
        """A row being delivered is immutable; a change appends a second row.

        Rewriting the claimed row in place made the worker deliver a payload it
        had never read, and the "old" state was then unrecoverable if the new
        delivery failed.
        """
        with transaction(self.conn):
            first = outbox.enqueue(
                self.conn,
                collection=vectors.MEMORIES,
                entity_id="m-1",
                operation="upsert",
                payload={"text": "old", "scope_id": self.scope_id},
            )
        self.conn.execute(
            "UPDATE index_outbox SET status='processing',claim_token='claim-1' WHERE id=%s",
            (first,),
        )
        with transaction(self.conn):
            second = outbox.enqueue(
                self.conn,
                collection=vectors.MEMORIES,
                entity_id="m-1",
                operation="upsert",
                payload={"text": "new", "scope_id": self.scope_id},
            )

        self.assertGreater(second, first)
        rows = self.conn.execute(
            "SELECT id,status,payload FROM index_outbox ORDER BY id"
        ).fetchall()
        self.assertEqual(
            [(row["id"], row["status"]) for row in rows],
            [(first, "processing"), (second, "pending")],
        )
        self.assertEqual(rows[0]["payload"]["text"], "old")
        self.assertEqual(rows[1]["payload"]["text"], "new")

    def test_a_delivery_whose_holder_died_is_claimable_again(self) -> None:
        """A crashed worker must not strand a row in `processing` for ever."""
        qdrant = StubQdrant()
        with transaction(self.conn):
            memory_id = store.add_memory(
                self.conn,
                scope_id=self.scope_id,
                author_id=self.team.alice_id,
                text="recover me",
                kind="fact",
                source_role="manual",
            )
        self.conn.execute(
            """UPDATE index_outbox SET status='processing',claim_token='dead',
                      lease_expires_at=%s WHERE entity_id=%s""",
            (datetime.now(UTC) - timedelta(minutes=1), memory_id),
        )

        outcome = outbox.drain(self.conn, qdrant, StubEmbedder(), ignore_schedule=True)

        self.assertEqual(outcome.applied, 1)
        self.assertEqual(qdrant.points[memory_id]["text"], "recover me")

    def test_erasure_leaves_no_delivery_that_could_put_the_vector_back(self) -> None:
        """Erasure removes the queue as well as the rows and the points.

        Delivery happens after commit and is retried on a schedule, so an
        undelivered upsert outliving the memory it describes is a vector that
        reappears minutes after somebody was told their data was gone.
        """
        qdrant = FilterAwareQdrant()
        with transaction(self.conn):
            memory_id = store.add_memory(
                self.conn,
                scope_id=self.scope_id,
                author_id=self.team.alice_id,
                text="erase me",
                kind="fact",
                source_role="manual",
            )
        outbox.drain(self.conn, qdrant, StubEmbedder())
        self.assertIn(memory_id, qdrant.points)
        # A second, still-queued delivery for the same memory: exactly the
        # shape that used to resurrect a point after erasure.
        with transaction(self.conn):
            outbox.enqueue(
                self.conn,
                collection=vectors.MEMORIES,
                entity_id=memory_id,
                operation="upsert",
                payload={"text": "erase me", "scope_id": self.scope_id},
            )

        privacy.erase_user(
            self.conn,
            qdrant,
            user_id=self.team.alice_id,
            private_scope_id=self.scope_id,
        )

        self.assertNotIn(memory_id, qdrant.points)
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) AS n FROM index_outbox").fetchone()["n"], 0
        )
        outbox.drain(self.conn, qdrant, StubEmbedder(), ignore_schedule=True)
        self.assertNotIn(memory_id, qdrant.points)

    def test_a_delivery_for_a_deleted_memory_is_dropped_not_applied(self) -> None:
        """The store is rechecked immediately before the external write.

        Without it a delete that overtook a queued upsert would be undone by
        it, which is the same resurrection seen from the other side.
        """
        qdrant = StubQdrant()
        with transaction(self.conn):
            memory_id = store.add_memory(
                self.conn,
                scope_id=self.scope_id,
                author_id=self.team.alice_id,
                text="gone by delivery time",
                kind="fact",
                source_role="manual",
            )
        self.conn.execute("DELETE FROM memories WHERE id=%s", (memory_id,))

        outcome = outbox.drain(self.conn, qdrant, StubEmbedder(), ignore_schedule=True)

        self.assertEqual(outcome.applied, 1)
        self.assertNotIn(memory_id, qdrant.points)


class ClaimExclusivityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = make_db()

    def test_two_jobs_cannot_claim_the_same_conversation_window(self) -> None:
        """A window is one provider call, so a double claim is a double bill."""
        add_messages(self.conn, n=1, content="remember tea")
        first = extract.claim_window(self.conn, session_id="s-1", job_id="job-a")
        second = extract.claim_window(connect(self.conn.info.dsn), session_id="s-1", job_id="job-b")
        self.assertEqual(len(first), 1)
        self.assertEqual(second, [])

    def test_an_abandoned_job_releases_its_window_and_its_money(self) -> None:
        """Recovery has to undo all three effects of a death, not just the job.

        A requeued job whose messages stayed claimed would spin doing nothing,
        and its reservation would hold spend against the ceiling for ever.
        """
        job_id = jobs.create(self.conn, kind="export")
        jobs.claim(self.conn, job_id, holder="dead-worker", lease_seconds=1)
        add_messages(self.conn, n=1, content="recover me")
        self.assertTrue(extract.claim_window(self.conn, session_id="s-1", job_id=job_id))
        reservation_id = jobs.reserve_budget(
            self.conn, period="2026-08", amount_usd=0.5, limit_usd=1.0, job_id=job_id
        )
        stale = datetime(2020, 1, 1, tzinfo=UTC)
        self.conn.execute("UPDATE jobs SET lease_expires_at=%s WHERE id=%s", (stale, job_id))
        self.conn.execute(
            "UPDATE budget_reservations SET updated_at=%s WHERE id=%s", (stale, reservation_id)
        )

        recovered = jobs.recover_stale(self.conn)

        self.assertEqual(recovered["jobs"], 1)
        self.assertEqual(recovered["reservations"], 1)
        self.assertEqual(recovered["message_claims"], 1)
        self.assertEqual(jobs.get(self.conn, job_id)["status"], "queued")
        self.assertEqual(
            self.conn.execute(
                "SELECT status FROM budget_reservations WHERE id=%s", (reservation_id,)
            ).fetchone()["status"],
            "released",
        )
        self.assertIsNone(
            self.conn.execute("SELECT claim_token FROM messages WHERE session_id='s-1'").fetchone()[
                "claim_token"
            ]
        )


class MemoryRevisionRegressionTest(ApiTestCase):
    def test_a_correction_bumps_one_revision_and_still_redacts(self) -> None:
        """Two bugs in one path: a lost update, and text that skipped redaction.

        The revision is incremented by the database in the same statement that
        checks it, so a stale writer loses rather than silently overwriting.
        Redaction applies to the corrected text as well as the original, and a
        metadata-only patch must not lower the flag on text that is still
        scrubbed.
        """
        memory_id = self.seed_memory(text="original")
        revision = self.scalar("SELECT revision FROM memories WHERE id=%s", memory_id)
        response = self.client.patch(
            f"/v1/memories/{memory_id}",
            headers=self.auth,
            json={"expected_revision": revision, "text": "API_KEY=super-secret-value"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["revision"], 2)
        self.assertNotIn(
            "super-secret-value", self.scalar("SELECT text FROM memories WHERE id=%s", memory_id)
        )
        self.assertTrue(self.scalar("SELECT redacted FROM memories WHERE id=%s", memory_id))

        metadata_only = self.client.patch(
            f"/v1/memories/{memory_id}",
            headers=self.auth,
            json={"expected_revision": 2, "importance": 0.8},
        )
        self.assertEqual(metadata_only.status_code, 200, metadata_only.text)
        self.assertTrue(self.scalar("SELECT redacted FROM memories WHERE id=%s", memory_id))

        stale = self.client.patch(
            f"/v1/memories/{memory_id}",
            headers=self.auth,
            json={"expected_revision": 1, "text": "stale overwrite"},
        )
        self.assertEqual(stale.status_code, 409, stale.text)

        history = self.client.get(f"/v1/memories/{memory_id}/history", headers=self.auth)
        self.assertEqual([item["revision"] for item in history.json()["revisions"]], [3, 2, 1])


if __name__ == "__main__":
    unittest.main()
