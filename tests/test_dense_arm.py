"""The dense arm, against real similarity scores.

Most deterministic retrieval tests run on a stub whose `query_points` returns
nothing, so the 0.60-weight dense term -- the largest in the ranking formula --
is never exercised, and an abstention assertion passes only because the index is
empty. These use a stub that computes actual dot products.

That also makes the authorization claim testable end to end. Qdrant is a derived
index: it can lag, it can hold a point whose payload no longer describes the
row, and a membership can be revoked between the write and the read. The rule is
that none of that can widen what a caller sees, because Postgres re-applies the
scope predicate over whatever the index proposed.
"""

from __future__ import annotations

import unittest

from memkit import entities, outbox, principal, retrieval, store, vectors
from tests.fixtures import HashEmbedder, SearchableQdrant, make_db, seed_team

INDEXED_TEXT = "Prefers pnpm over npm on every project"


class DenseArmTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = make_db(seed=False)
        self.team = seed_team(self.conn)
        self.caller = self.team.principal("alice")
        self.client = SearchableQdrant()
        self.embedder = HashEmbedder()

    def tearDown(self) -> None:
        self.conn.close()

    def _add(self, text: str, **kw) -> str:
        with self.conn.transaction():
            memory_id = store.add_memory(
                self.conn,
                scope_id=kw.pop("scope_id", self.caller.own_entity_id),
                author_id=kw.pop("author_id", self.team.alice_id),
                text=text,
                kind=kw.pop("kind", "preference"),
                source_role=kw.pop("source_role", "user"),
                **kw,
            )
        # Indexing is what puts a vector in front of the dense arm.
        outbox.drain(self.conn, self.client, self.embedder, limit=100)
        return memory_id

    def _search(self, query: str, *, scope_ids: list[str] | None = None, **kw):
        return retrieval.explain(
            self.conn,
            self.client,
            self.embedder,
            query=query,
            scope_ids=self.caller.scopes() if scope_ids is None else scope_ids,
            **kw,
        )

    def test_the_dense_arm_scores_an_indexed_memory(self) -> None:
        memory_id = self._add(INDEXED_TEXT)
        result = self._search(INDEXED_TEXT)
        self.assertEqual([item.id for item in result.chosen], [memory_id])
        hit = result.chosen[0]
        self.assertGreater(hit.similarity, 0.0, "the dense arm contributed nothing")
        self.assertGreaterEqual(hit.score, hit.similarity * 0.60)

    def test_another_scopes_vectors_are_never_scored(self) -> None:
        mine = self._add(INDEXED_TEXT)
        self._add(INDEXED_TEXT, scope_id=self.team.scope_of("bob"), author_id=self.team.bob_id)
        result = self._search(INDEXED_TEXT)
        self.assertEqual([item.id for item in result.chosen], [mine])

    def test_an_archived_memory_leaves_the_index(self) -> None:
        memory_id = self._add(INDEXED_TEXT)
        with self.conn.transaction():
            store.set_memory_status(
                self.conn,
                memory_id=memory_id,
                scopes=self.caller.scopes(),
                status="archived",
            )
        outbox.drain(self.conn, self.client, self.embedder, limit=100)
        self.assertEqual(self._search(INDEXED_TEXT).chosen, [])

    def test_a_dissimilar_query_is_dropped_by_the_relevance_floor(self) -> None:
        """The floor must be provable against a real score, not an empty index.

        HashEmbedder makes unrelated texts orthogonal, which is the ideal case;
        it shows the floor is reached and applied. Whether the floor is high
        enough for a real embedding model is a separate, measured question.
        """
        self._add(INDEXED_TEXT)
        result = self._search("wholly unrelated subject matter")
        self.assertEqual(result.chosen, [])
        self.assertEqual(len(result.dropped_relevance), 1)

    def test_a_high_floor_drops_a_scoring_hit(self) -> None:
        """Abstention is policy, and the policy has to bind."""
        self._add(INDEXED_TEXT)
        strict = retrieval.RetrievalPolicy(min_relevance=0.99)
        result = self._search(INDEXED_TEXT, policy=strict)
        self.assertEqual(result.chosen, [])
        self.assertEqual(len(result.dropped_relevance), 1)

        permissive = retrieval.RetrievalPolicy(min_relevance=0.0)
        allowed = self._search(INDEXED_TEXT, policy=permissive)
        self.assertEqual(len(allowed.chosen), 1)


class IndexIsDerivedTest(unittest.TestCase):
    """Postgres decides who may read a memory; Qdrant only proposes candidates."""

    def setUp(self) -> None:
        self.conn = make_db(seed=False)
        self.team = seed_team(self.conn)
        self.alice = self.team.principal("alice")
        self.client = SearchableQdrant()
        self.embedder = HashEmbedder()

    def tearDown(self) -> None:
        self.conn.close()

    def _drain(self) -> None:
        outbox.drain(self.conn, self.client, self.embedder, limit=100)

    def test_a_point_whose_payload_lies_about_its_scope_is_still_refused(self) -> None:
        """The payload is a copy of a column, and a copy can be wrong.

        A point written before a fact moved scope, or left behind by a failed
        delivery, can advertise a scope the caller belongs to while the row it
        stands for lives somewhere the caller cannot reach. The dense arm will
        happily return it; `_candidate_rows` re-runs `scope_id = ANY(...)` on the
        authoritative table, which is the only reason that cannot leak.
        """
        with self.conn.transaction():
            hidden = store.add_memory(
                self.conn,
                scope_id=self.team.scope_of("bob"),
                author_id=self.team.bob_id,
                text=INDEXED_TEXT,
                kind="preference",
                source_role="user",
            )
        self._drain()
        self.client.set_payload(vectors.MEMORIES, [hidden], {"scope_id": self.alice.own_entity_id})

        offered = vectors.search(
            self.client,
            vectors.MEMORIES,
            self.embedder.encode_one(INDEXED_TEXT),
            limit=10,
            must=[vectors.keyword("scope_id", self.alice.scopes())],
        )
        self.assertEqual([str(hit.id) for hit in offered], [hidden], "the index did not offer it")

        result = retrieval.explain(
            self.conn,
            self.client,
            self.embedder,
            query=INDEXED_TEXT,
            scope_ids=self.alice.scopes(),
        )
        self.assertEqual(result.chosen, [])

    def test_revoking_a_membership_takes_effect_before_the_index_catches_up(self) -> None:
        """Access ends when the grant does, not when the reindex finishes."""
        with self.conn.transaction():
            memory_id = store.add_memory(
                self.conn,
                scope_id=self.team.project_id,
                author_id=self.team.alice_id,
                text=INDEXED_TEXT,
                kind="preference",
                source_role="user",
            )
        self._drain()
        bob = principal.load(self.conn, self.team.bob_id)
        found = retrieval.explain(
            self.conn,
            self.client,
            self.embedder,
            query=INDEXED_TEXT,
            scope_ids=bob.scopes(),
        )
        self.assertEqual([item.id for item in found.chosen], [memory_id])

        with self.conn.transaction():
            entities.remove_member(
                self.conn, entity_id=self.team.project_id, user_id=self.team.bob_id
            )
        revoked = principal.load(self.conn, self.team.bob_id)
        self.assertNotIn(self.team.project_id, revoked.scopes())
        # Nothing touched the index: the point is still there, unchanged.
        self.assertIn(memory_id, self.client.points)
        after = retrieval.explain(
            self.conn,
            self.client,
            self.embedder,
            query=INDEXED_TEXT,
            scope_ids=revoked.scopes(),
        )
        self.assertEqual(after.chosen, [])


if __name__ == "__main__":
    unittest.main()
