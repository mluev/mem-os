from __future__ import annotations

import unittest
from datetime import UTC, datetime

from memkit import retrieval, store
from memkit.db import transaction
from tests.fixtures import OWNER, StubEmbedder, StubQdrant, make_db


class TestHybridRetrieval(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = make_db()
        self.qdrant = StubQdrant()
        self.embedder = StubEmbedder()

    def add(self, text: str, **kwargs) -> str:
        with transaction(self.conn):
            return store.add_memory(
                self.conn,
                owner_id=OWNER,
                text=text,
                kind=kwargs.pop("kind", "fact"),
                **kwargs,
            )

    def test_exact_term_lexical_arm_and_context_filter(self) -> None:
        wanted = self.add(
            "The deploy failed with ERR_X91Q",
            context={"workspace": "mem-os"},
            source_role="user",
        )
        self.add(
            "The deploy uses a release script",
            context={"workspace": "other"},
            source_role="user",
        )
        result = retrieval.explain(
            self.conn,
            self.qdrant,
            self.embedder,
            query="ERR_X91Q",
            owner_id=OWNER,
            expression={"field": "context.workspace", "op": "eq", "value": "mem-os"},
        )
        self.assertEqual([item.id for item in result.chosen], [wanted])

    def test_expired_and_agent_authored_are_hard_filtered(self) -> None:
        expired = self.add(
            "Old launch code ABC-123",
            valid_until="2020-01-01T00:00:00Z",
            source_role="user",
        )
        untrusted = self.add("Agent guessed launch code ABC-123", source_role="agent")
        result = retrieval.explain(
            self.conn,
            self.qdrant,
            self.embedder,
            query="ABC-123",
            owner_id=OWNER,
            now=datetime(2026, 8, 9, tzinfo=UTC),
        )
        self.assertEqual(result.chosen, [])
        self.assertIn(expired, result.dropped_validity)
        self.assertIn(untrusted, result.dropped_trust)

    def test_irrelevant_query_can_stay_silent(self) -> None:
        self.add("Prefers pnpm for JavaScript packages", source_role="user")
        result = retrieval.explain(
            self.conn,
            self.qdrant,
            self.embedder,
            query="quantum chromodynamics",
            owner_id=OWNER,
        )
        self.assertEqual(result.chosen, [])


if __name__ == "__main__":
    unittest.main()
