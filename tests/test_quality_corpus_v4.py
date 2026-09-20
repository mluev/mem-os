"""Retrieval quality at a size where a lucky ranking cannot be mistaken for one.

Three claims that hold or fail regardless of which embedding model is loaded,
which is why they run against a stub index: an exact identifier is still first
when ten thousand plausible rows surround it; the temporal and provenance guards
are hard filters rather than another term in the score, so a confident lie still
loses to an unconfident truth; and a query the store has nothing to say about
returns nothing.
"""

from __future__ import annotations

import unittest
from datetime import UTC, datetime

from memkit import retrieval, store
from tests.fixtures import StubEmbedder, StubQdrant, make_db, seed_team

DISTRACTORS = 10_000


class QualityCorpusTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = make_db(seed=False)
        self.team = seed_team(self.conn)
        self.caller = self.team.principal("alice")

    def tearDown(self) -> None:
        self.conn.close()

    def _add(self, text: str, **kw) -> str:
        return store.add_memory(
            self.conn,
            scope_id=self.caller.own_entity_id,
            author_id=self.team.alice_id,
            text=text,
            kind=kw.pop("kind", "fact"),
            source_role=kw.pop("source_role", "user"),
            **kw,
        )

    def _search(self, query: str, **kw):
        return retrieval.explain(
            self.conn,
            StubQdrant(),
            StubEmbedder(),
            query=query,
            scope_ids=self.caller.scopes(),
            **kw,
        )

    def test_an_exact_term_survives_ten_thousand_distractors(self) -> None:
        with self.conn.transaction():
            for index in range(DISTRACTORS):
                self._add(
                    f"ordinary distractor observation number {index}",
                    kind="observation",
                )
            target = self._add(
                "Deployment incident code ZXQ-9173 needs investigation",
                kind="incident",
            )
        result = self._search("ZXQ-9173", limit=5)
        self.assertTrue(result.chosen)
        self.assertEqual(result.chosen[0].id, target)

    def test_the_temporal_and_trust_guards_ignore_confidence(self) -> None:
        """A guard that could be outweighed is not a guard.

        The expired row is stored at maximum confidence and the model-authored
        one at maximum confidence too; the only survivor is the live,
        user-sourced fact recorded at 0.01.
        """
        with self.conn.transaction():
            live = self._add("Current release marker RELEASE-42", kind="release", confidence=0.01)
            expired = self._add(
                "Old release marker RELEASE-42",
                kind="release",
                confidence=1,
                valid_until="2025-01-01T00:00:00Z",
            )
            poisoned = self._add(
                "Agent invented release marker RELEASE-42",
                kind="release",
                confidence=1,
                source_role="agent",
            )
        result = self._search("RELEASE-42", now=datetime(2026, 8, 9, tzinfo=UTC))
        self.assertEqual([item.id for item in result.chosen], [live])
        self.assertNotIn(expired, [item.id for item in result.chosen])
        self.assertNotIn(poisoned, [item.id for item in result.chosen])

    def test_an_unrelated_query_abstains(self) -> None:
        with self.conn.transaction():
            self._add("Prefers pnpm for JavaScript packages", kind="preference")
        self.assertEqual(self._search("history of medieval astronomy").chosen, [])


if __name__ == "__main__":
    unittest.main()
