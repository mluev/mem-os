"""Embedding call shape, which is a cost and latency claim.

Every embedding acquires one lock around a local model, so the difference
between one call for a batch and one call per row is the difference between a
fast request and a visibly slow one. These tests assert the shape, because
nothing else notices when it regresses.
"""

from __future__ import annotations

import unittest

from memkit import extract, judge, outbox, retrieval, store, vectors
from tests.fixtures import (
    CountingEmbedder,
    SearchableQdrant,
    StubQdrant,
    make_db,
    make_session,
    seed_team,
)


class TeamCase(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = make_db(seed=False)
        self.team = seed_team(self.conn)
        make_session(self.conn, self.team)
        self.scope = self.team.scope_of("alice")

    def tearDown(self) -> None:
        self.conn.close()


class OutboxBatchTest(TeamCase):
    def setUp(self) -> None:
        super().setUp()
        self.client = StubQdrant()
        self.embedder = CountingEmbedder()

    def _queue_messages(self, count: int) -> None:
        with self.conn.transaction():
            for index in range(count):
                store.add_message(
                    self.conn,
                    session_id="s-1",
                    user_id=self.team.alice_id,
                    scope_id=self.scope,
                    agent_id="chat",
                    role="user",
                    content=f"a message long enough to be indexed, number {index}",
                )

    def test_one_embedding_call_serves_the_whole_batch(self) -> None:
        self._queue_messages(20)
        result = outbox.drain(self.conn, self.client, self.embedder, limit=100)
        self.assertEqual(result.applied, 20)
        self.assertEqual(result.failed, 0)
        self.assertEqual(self.embedder.encode_one_calls, 0)
        self.assertEqual(self.embedder.encode_calls, [20])
        self.assertEqual(len(self.client.raw_points), 20)

    def test_the_batch_size_bounds_one_embedding_call(self) -> None:
        self._queue_messages(40)
        outbox.drain(self.conn, self.client, self.embedder, limit=100, batch_size=16)
        self.assertEqual(self.embedder.encode_calls, [16, 16, 8])

    def test_a_poison_row_fails_alone(self) -> None:
        """One unusable payload must not cost the rest of its batch."""
        self._queue_messages(5)
        with self.conn.transaction():
            memory_id = store.add_memory(
                self.conn,
                scope_id=self.scope,
                author_id=self.team.alice_id,
                text="a real memory whose queued payload is broken",
                kind="preference",
                source_role="user",
            )
            # The row exists, so this is not an obsolete delivery: the payload
            # itself is unusable, which is the case that must fail alone.
            outbox.enqueue(
                self.conn,
                collection=vectors.MEMORIES,
                entity_id=memory_id,
                operation="upsert",
                payload={"scope_id": self.scope},
            )
        result = outbox.drain(self.conn, self.client, self.embedder, limit=100)
        self.assertEqual(result.applied, 6)
        self.assertEqual(result.failed, 1)
        row = self.conn.execute(
            """SELECT status,attempts,last_error FROM index_outbox
                WHERE entity_id=%s ORDER BY id DESC LIMIT 1""",
            (memory_id,),
        ).fetchone()
        self.assertEqual(row["status"], "pending")
        self.assertEqual(row["attempts"], 1)
        self.assertIn("no text", row["last_error"])

    def test_delivery_still_works_when_batch_embedding_fails(self) -> None:
        class BrokenBatch(CountingEmbedder):
            def encode(self, texts):
                self.encode_calls.append(len(texts))
                raise RuntimeError("batch encode unavailable")

        self._queue_messages(3)
        embedder = BrokenBatch()
        result = outbox.drain(self.conn, self.client, embedder, limit=100)
        self.assertEqual(result.applied, 3)
        self.assertEqual(embedder.encode_one_calls, 3, "no per-row fallback happened")


class DedupBatchTest(TeamCase):
    def test_one_embedding_call_covers_every_add(self) -> None:
        embedder = CountingEmbedder()
        ops = [
            judge.Op(
                op="ADD", reason="stated", text=f"a durable preference {index}", kind="preference"
            )
            for index in range(3)
        ]
        ops.append(judge.Op(op="DELETE", reason="obsolete", id="x"))
        planned = extract.plan_dedup(
            self.conn,
            ops=ops,
            scope_id=self.scope,
            client=StubQdrant(),
            embedder=embedder,
            threshold=0.9,
        )
        self.assertEqual(planned, {})
        self.assertEqual(embedder.encode_calls, [3], "ADD texts were embedded one at a time")
        self.assertEqual(embedder.encode_one_calls, 0)

    def test_no_adds_means_no_embedding(self) -> None:
        embedder = CountingEmbedder()
        extract.plan_dedup(
            self.conn,
            ops=[judge.Op(op="DELETE", reason="obsolete", id="x")],
            scope_id=self.scope,
            client=StubQdrant(),
            embedder=embedder,
            threshold=0.9,
        )
        self.assertEqual(embedder.encode_calls, [])


class EvidenceIndexingTest(TeamCase):
    """Evidence writes must not wait on the index.

    The endpoints drained the outbox inline, so posting a hundred events paid a
    hundred sequential embeddings before responding. The response distinguishes
    `stored` from `indexed` precisely so indexing can be someone else's problem.
    """

    def test_a_queued_message_is_stored_before_it_is_indexed(self) -> None:
        with self.conn.transaction():
            message_id, _, _ = store.add_message(
                self.conn,
                session_id="s-1",
                user_id=self.team.alice_id,
                scope_id=self.scope,
                agent_id="chat",
                role="user",
                content="a message long enough to be indexed at all",
            )
        row = self.conn.execute(
            "SELECT status,payload FROM index_outbox WHERE entity_id=%s", (str(message_id),)
        ).fetchone()
        self.assertEqual(row["status"], "pending")
        self.assertIn("text", row["payload"])


class QueryEmbeddingTest(TeamCase):
    """A search that also reads raw turns must embed its query once."""

    def test_include_raw_reuses_the_memory_search_vector(self) -> None:
        embedder = CountingEmbedder()
        client = SearchableQdrant()
        with self.conn.transaction():
            store.add_memory(
                self.conn,
                scope_id=self.scope,
                author_id=self.team.alice_id,
                text="Prefers pnpm over npm on every project",
                kind="preference",
                source_role="user",
            )
        outbox.drain(self.conn, client, embedder, limit=100)
        embedder.encode_calls.clear()
        embedder.encode_one_calls = 0

        result = retrieval.explain(
            self.conn, client, embedder, query="which package manager", scope_ids=[self.scope]
        )
        self.assertIsNotNone(result.query_vector)
        self.assertNotIn("query_vector", result.as_dict())

        store.search_raw(
            self.conn,
            client,
            embedder,
            query="which package manager",
            scope_ids=[self.scope],
            vector=result.query_vector,
        )
        self.assertEqual(embedder.encode_one_calls, 1, "the query was embedded twice")


if __name__ == "__main__":
    unittest.main()
