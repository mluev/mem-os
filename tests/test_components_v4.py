"""The two seams the design promises are open: the judge and the reranker.

Neither is a plugin system. They are the two places where the pipeline hands
control to something it did not write, and the point of testing them is that a
replacement is reached at all -- a seam nothing exercises stops being a seam the
first time somebody inlines the default.
"""

from __future__ import annotations

import unittest

from memkit import providers, retrieval, store
from tests.fixtures import StubEmbedder, StubQdrant, fake_provider, make_db, seed_team


class JudgeProviderTest(unittest.TestCase):
    def test_a_registered_provider_receives_the_call(self) -> None:
        calls: list[str] = []

        def handler(**kwargs):
            calls.append(kwargs["model"])
            return providers.ProviderResult(raw={"operations": []})

        with fake_provider(handler, family="test", prefix="test-"):
            result = providers.call(model="test-small", prompt="hello")

        self.assertIsNone(result.error)
        self.assertEqual(calls, ["test-small"])

    def test_the_registration_is_undone_with_the_context(self) -> None:
        """A provider left behind changes the routing of every later test."""
        with fake_provider(lambda **_: providers.ProviderResult(), family="test", prefix="test-"):
            self.assertEqual(providers.provider_of("test-small"), "test")
        with self.assertRaises(ValueError):
            providers.provider_of("test-small")


class RerankerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = make_db(seed=False)
        self.team = seed_team(self.conn)
        self.caller = self.team.principal("alice")

    def tearDown(self) -> None:
        self.conn.close()

    def _add(self, text: str) -> str:
        with self.conn.transaction():
            return store.add_memory(
                self.conn,
                scope_id=self.caller.own_entity_id,
                author_id=self.team.alice_id,
                text=text,
                kind="fact",
                source_role="user",
            )

    def test_a_custom_reranker_decides_the_final_order(self) -> None:
        first = self._add("alpha exact")
        second = self._add("alpha second")

        class Reverse:
            def rerank(self, query, candidates):
                return sorted(candidates, key=lambda item: item.id != second)

        result = retrieval.explain(
            self.conn,
            StubQdrant(),
            StubEmbedder(),
            query="alpha",
            scope_ids=self.caller.scopes(),
            reranker=Reverse(),
        )
        self.assertEqual({item.id for item in result.chosen}, {first, second})
        self.assertEqual(result.chosen[0].id, second)

    def test_a_reranker_cannot_widen_what_the_caller_may_read(self) -> None:
        """It reorders the candidate list; it never gets to add to it."""
        self._add("alpha exact")
        hidden = store.add_memory(
            self.conn,
            scope_id=self.team.scope_of("bob"),
            author_id=self.team.bob_id,
            text="alpha secret",
            kind="fact",
            source_role="user",
        )
        self.conn.commit()

        seen: list[list[str]] = []

        class Watching:
            def rerank(self, query, candidates):
                seen.append([item.id for item in candidates])
                return candidates

        result = retrieval.explain(
            self.conn,
            StubQdrant(),
            StubEmbedder(),
            query="alpha",
            scope_ids=self.caller.scopes(),
            reranker=Watching(),
        )
        self.assertNotIn(hidden, seen[0])
        self.assertNotIn(hidden, [item.id for item in result.chosen])


if __name__ == "__main__":
    unittest.main()
