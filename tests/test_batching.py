"""Embedding call shape, which is a cost and latency claim.

Every embedding acquires one lock around a local model, so the difference
between one call for a batch and one call per row is the difference between a
fast request and a visibly slow one. These tests assert the shape, because
nothing else notices when it regresses.
"""

from __future__ import annotations

import json
import unittest

from memkit import extract, judge, outbox, store, vectors
from memkit.db import transaction
from tests.fixtures import OWNER, CountingEmbedder, StubQdrant, make_db


class OutboxBatchTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = make_db()
        self.client = StubQdrant()
        self.embedder = CountingEmbedder()

    def tearDown(self) -> None:
        self.conn.close()

    def _queue_messages(self, count: int) -> None:
        with transaction(self.conn):
            for i in range(count):
                store.add_message(
                    self.conn,
                    session_id="s-1",
                    owner_id=OWNER,
                    agent_id="chat",
                    role="user",
                    content=f"a message long enough to be indexed, number {i}",
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
        with transaction(self.conn):
            memory_id = store.add_memory(
                self.conn,
                owner_id=OWNER,
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
                payload={"owner_id": OWNER},
            )
        result = outbox.drain(self.conn, self.client, self.embedder, limit=100)
        self.assertEqual(result.applied, 6)
        self.assertEqual(result.failed, 1)
        row = self.conn.execute(
            """SELECT status,attempts,last_error FROM index_outbox
                WHERE entity_id=? ORDER BY id DESC LIMIT 1""",
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


class DedupBatchTest(unittest.TestCase):
    def test_one_embedding_call_covers_every_add(self) -> None:
        conn = make_db()
        embedder = CountingEmbedder()
        ops = [
            judge.Op(op="ADD", reason="stated", text=f"a durable preference {i}", kind="preference")
            for i in range(3)
        ]
        ops.append(judge.Op(op="DELETE", reason="obsolete", id="x"))
        planned = extract.plan_dedup(
            conn,
            ops=ops,
            owner_id=OWNER,
            client=StubQdrant(),
            embedder=embedder,
            threshold=0.9,
        )
        self.assertEqual(planned, {})
        self.assertEqual(embedder.encode_calls, [3], "ADD texts were embedded one at a time")
        self.assertEqual(embedder.encode_one_calls, 0)
        conn.close()

    def test_no_adds_means_no_embedding(self) -> None:
        conn = make_db()
        embedder = CountingEmbedder()
        extract.plan_dedup(
            conn,
            ops=[judge.Op(op="DELETE", reason="obsolete", id="x")],
            owner_id=OWNER,
            client=StubQdrant(),
            embedder=embedder,
            threshold=0.9,
        )
        self.assertEqual(embedder.encode_calls, [])
        conn.close()


class EvidenceIndexingTest(unittest.TestCase):
    """Evidence writes must not wait on the index.

    The endpoints drained the outbox inline, so posting a hundred events paid a
    hundred sequential embeddings before responding. The response distinguishes
    `stored` from `indexed` precisely so indexing can be someone else's problem.
    """

    def test_a_queued_message_is_stored_before_it_is_indexed(self) -> None:
        conn = make_db()
        with transaction(conn):
            message_id, _, _ = store.add_message(
                conn,
                session_id="s-1",
                owner_id=OWNER,
                agent_id="chat",
                role="user",
                content="a message long enough to be indexed at all",
            )
        row = conn.execute(
            "SELECT status,payload_json FROM index_outbox WHERE entity_id=?", (str(message_id),)
        ).fetchone()
        self.assertEqual(row["status"], "pending")
        self.assertIn("text", json.loads(row["payload_json"]))
        conn.close()


class QueryEmbeddingTest(unittest.TestCase):
    """A search that also reads raw turns must embed its query once."""

    def test_include_raw_reuses_the_memory_search_vector(self) -> None:
        from memkit import retrieval
        from tests.fixtures import SearchableQdrant

        conn = make_db()
        embedder = CountingEmbedder()
        client = SearchableQdrant()
        with transaction(conn):
            store.add_memory(
                conn,
                owner_id=OWNER,
                text="Prefers pnpm over npm on every project",
                kind="preference",
                source_role="user",
            )
        outbox.drain(conn, client, embedder, limit=100)
        embedder.encode_calls.clear()
        embedder.encode_one_calls = 0

        result = retrieval.explain(
            conn, client, embedder, query="which package manager", owner_id=OWNER
        )
        self.assertIsNotNone(result.query_vector)
        self.assertNotIn("query_vector", result.as_dict())

        store.search_raw(
            client,
            embedder,
            query="which package manager",
            owner_id=OWNER,
            vector=result.query_vector,
        )
        self.assertEqual(embedder.encode_one_calls, 1, "the query was embedded twice")
        conn.close()


if __name__ == "__main__":
    unittest.main()
