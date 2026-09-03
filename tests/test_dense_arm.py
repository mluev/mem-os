"""The dense arm, against real similarity scores.

Every deterministic retrieval test runs on a stub whose `query_points` returns
nothing, so the 0.60-weight dense term -- the largest in the ranking formula --
was never exercised, and the one test asserting abstention passed only because
the index was empty. These use a stub that computes actual dot products.
"""

from __future__ import annotations

import unittest

from memkit import outbox, retrieval, store
from memkit.db import transaction
from tests.fixtures import OWNER, HashEmbedder, SearchableQdrant, make_db


class DenseArmTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = make_db()
        self.client = SearchableQdrant()
        self.embedder = HashEmbedder()

    def tearDown(self) -> None:
        self.conn.close()

    def _add(self, text: str, **kw) -> str:
        with transaction(self.conn):
            memory_id = store.add_memory(
                self.conn,
                owner_id=OWNER,
                text=text,
                kind=kw.pop("kind", "preference"),
                source_role=kw.pop("source_role", "user"),
                **kw,
            )
        # Indexing is what puts a vector in front of the dense arm.
        outbox.drain(self.conn, self.client, self.embedder, limit=100)
        return memory_id

    def _search(self, query: str, **kw):
        return retrieval.explain(
            self.conn, self.client, self.embedder, query=query, owner_id=OWNER, **kw
        )

    def test_the_dense_arm_scores_an_indexed_memory(self) -> None:
        memory_id = self._add("Prefers pnpm over npm on every project")
        result = self._search("Prefers pnpm over npm on every project")
        self.assertEqual([item.id for item in result.chosen], [memory_id])
        hit = result.chosen[0]
        self.assertGreater(hit.similarity, 0.0, "the dense arm contributed nothing")
        self.assertGreaterEqual(hit.score, hit.similarity * 0.60)

    def test_the_scope_filter_reaches_the_index(self) -> None:
        """Another owner's vectors must not be scored at all."""
        mine = self._add("Prefers pnpm over npm on every project")
        with transaction(self.conn):
            store.add_memory(
                self.conn,
                owner_id="someone-else",
                text="Prefers pnpm over npm on every project",
                kind="preference",
                source_role="user",
            )
        outbox.drain(self.conn, self.client, self.embedder, limit=100)
        result = self._search("Prefers pnpm over npm on every project")
        self.assertEqual([item.id for item in result.chosen], [mine])

    def test_an_archived_memory_leaves_the_index(self) -> None:
        memory_id = self._add("Prefers pnpm over npm on every project")
        with transaction(self.conn):
            store.set_memory_status(
                self.conn, memory_id=memory_id, owner_id=OWNER, status="archived"
            )
        outbox.drain(self.conn, self.client, self.embedder, limit=100)
        result = self._search("Prefers pnpm over npm on every project")
        self.assertEqual(result.chosen, [])

    def test_a_dissimilar_query_is_dropped_by_the_relevance_floor(self) -> None:
        """The floor must be provable against a real score, not an empty index.

        HashEmbedder makes unrelated texts orthogonal, which is the ideal case;
        it shows the floor is reached and applied. Whether the floor is high
        enough for a real embedding model is a separate, measured question.
        """
        self._add("Prefers pnpm over npm on every project")
        result = self._search("wholly unrelated subject matter")
        self.assertEqual(result.chosen, [])
        self.assertEqual(len(result.dropped_relevance), 1)

    def test_a_high_floor_drops_a_scoring_hit(self) -> None:
        """Abstention is policy, and the policy has to bind."""
        self._add("Prefers pnpm over npm on every project")
        strict = retrieval.RetrievalPolicy(min_relevance=0.99)
        result = self._search("Prefers pnpm over npm on every project", policy=strict)
        self.assertEqual(result.chosen, [])
        self.assertEqual(len(result.dropped_relevance), 1)

        permissive = retrieval.RetrievalPolicy(min_relevance=0.0)
        allowed = self._search("Prefers pnpm over npm on every project", policy=permissive)
        self.assertEqual(len(allowed.chosen), 1)


if __name__ == "__main__":
    unittest.main()
