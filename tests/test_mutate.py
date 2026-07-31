"""Mutation invariants that protect SQLite/Qdrant ordering."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from memkit import mutate, store  # noqa: E402
from memkit.db import transaction  # noqa: E402
from tests.fixtures import OWNER, StubEmbedder, StubQdrant, add_messages, make_db  # noqa: E402


class CountingEmbedder(StubEmbedder):
    def __init__(self) -> None:
        self.one_calls = 0
        self.batch_calls = 0

    def encode_one(self, text: str) -> list[float]:
        self.one_calls += 1
        return super().encode_one(text)

    def encode(self, texts: list[str], batch_size: int = 16) -> list[list[float]]:
        self.batch_calls += 1
        return [StubEmbedder.encode_one(self, text) for text in texts]


class AdminQdrant(StubQdrant):
    def __init__(self) -> None:
        super().__init__()
        self.payload_calls: list[tuple[list[str], dict]] = []

    def set_payload(self, collection_name, points, payload, wait=True):
        self.payload_calls.append(([str(point) for point in points], payload))
        for point in points:
            self.points[str(point)].update(payload)


class TestMutate(unittest.TestCase):
    def setUp(self):
        self.conn = make_db()
        self.q = AdminQdrant()
        self.embedder = CountingEmbedder()
        with transaction(self.conn):
            self.memory_id = store.add_memory(
                self.conn,
                self.q,
                self.embedder,
                owner_id=OWNER,
                text="Prefers pnpm",
                type="preference",
                importance=0.8,
            )
        self.embedder.one_calls = 0

    def test_text_edit_preserves_created_at_in_row_and_payload(self):
        before = self.conn.execute(
            "SELECT * FROM memories WHERE id=?", (self.memory_id,)
        ).fetchone()
        result = mutate.update_memory(
            self.conn,
            self.q,
            self.embedder,
            memory_id=self.memory_id,
            changes={"text": "Prefers pnpm over npm"},
        )
        self.assertTrue(self.conn.in_transaction)
        self.assertEqual(result.row["created_at"], before["created_at"])
        self.assertEqual(result.point[2]["created_at"], before["created_at"])
        self.assertEqual(self.embedder.one_calls, 1)
        self.conn.rollback()

    def test_importance_only_uses_payload_without_embedding(self):
        with transaction(self.conn):
            result = mutate.update_memory(
                self.conn,
                self.q,
                self.embedder,
                memory_id=self.memory_id,
                changes={"importance": 0.95},
            )
        self.assertEqual(result.qdrant_op, "payload")
        self.assertEqual(self.embedder.one_calls, 0)
        result.apply_index(self.q)
        self.assertEqual(len(self.q.payload_calls), 1)

    def test_confidence_only_does_not_touch_index(self):
        result = mutate.update_memory(
            self.conn,
            self.q,
            self.embedder,
            memory_id=self.memory_id,
            changes={"confidence": 0.4},
        )
        self.assertEqual(result.qdrant_op, "none")
        self.assertEqual(self.embedder.one_calls, 0)
        self.conn.rollback()

    def test_expire_then_restore_recreates_point(self):
        with transaction(self.conn):
            expired = mutate.set_status(
                self.conn, self.q, self.embedder,
                memory_id=self.memory_id, status="expired",
            )
        expired.apply_index(self.q)
        self.assertNotIn(self.memory_id, self.q.points)
        with transaction(self.conn):
            restored = mutate.set_status(
                self.conn, self.q, self.embedder,
                memory_id=self.memory_id, status="active",
            )
        self.assertTrue(restored.reembedded)
        restored.apply_index(self.q)
        self.assertIn(self.memory_id, self.q.points)

    def test_stale_expected_timestamp_writes_nothing(self):
        with self.assertRaises(mutate.MutationError) as caught:
            mutate.update_memory(
                self.conn,
                self.q,
                self.embedder,
                memory_id=self.memory_id,
                changes={"text": "wrong"},
                expected_updated_at="2000-01-01T00:00:00Z",
            )
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(
            self.conn.execute(
                "SELECT text FROM memories WHERE id=?", (self.memory_id,)
            ).fetchone()["text"],
            "Prefers pnpm",
        )

    def test_bulk_restore_uses_one_embedding_batch(self):
        ids = [self.memory_id]
        for index in range(4):
            ids.append(
                store.add_memory(
                    self.conn,
                    self.q,
                    self.embedder,
                    owner_id=OWNER,
                    text=f"fact {index}",
                    type="fact",
                )
            )
        self.conn.execute(
            f"UPDATE memories SET status='expired' WHERE id IN ({','.join('?' for _ in ids)})",
            ids,
        )
        self.embedder.one_calls = 0
        self.embedder.batch_calls = 0
        result = mutate.bulk(
            self.conn,
            self.q,
            self.embedder,
            ids=ids,
            op="restore",
        )
        self.assertEqual(result.applied, 5)
        self.assertEqual(self.embedder.batch_calls, 1)
        self.assertEqual(self.embedder.one_calls, 0)
        self.conn.rollback()

    def test_hard_delete_clears_both_foreign_key_edges(self):
        message_id = add_messages(self.conn, n=1)[0]
        self.conn.execute(
            "INSERT INTO memory_sources(memory_id,message_id) VALUES(?,?)",
            (self.memory_id, message_id),
        )
        successor = store.add_memory(
            self.conn,
            self.q,
            self.embedder,
            owner_id=OWNER,
            text="Uses pnpm everywhere",
            type="preference",
        )
        self.conn.execute(
            "UPDATE memories SET status='superseded', superseded_by=? WHERE id=?",
            (self.memory_id, successor),
        )
        with transaction(self.conn):
            result = mutate.hard_delete(
                self.conn, self.q, memory_id=self.memory_id
            )
        self.assertEqual(result.sources_unlinked, 1)
        self.assertEqual(result.successors_unlinked, 1)
        self.assertIsNone(
            self.conn.execute(
                "SELECT superseded_by FROM memories WHERE id=?", (successor,)
            ).fetchone()["superseded_by"]
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) n FROM messages WHERE id=?", (message_id,)
            ).fetchone()["n"],
            1,
        )


if __name__ == "__main__":
    unittest.main()
