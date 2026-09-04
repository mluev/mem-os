"""The eval harness must keep working against the library it measures.

eval/ rotted silently against the v4 rebuild -- `score()` called signatures
that no longer existed, so the one instrument that gates every quality change
could not run at all. It rotted a second time against the move to Postgres and
team scopes, for the same reason: nothing imported it. This suite runs it
against a real temp database and a searchable stub index, so signature drift
fails here, offline, instead of at measurement time.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval.run import load_cases, score
from memkit import outbox, store
from tests.fixtures import HashEmbedder, SearchableQdrant, make_db, make_session, seed_team

# The `pref` query carries no word the stored fact lacks. That is a property of
# the *fixture*, not of the eval: the stub embedder scores unrelated strings at
# roughly zero, so the memories case rides entirely on the lexical arm, and
# `plainto_tsquery` combines terms conjunctively -- one extra word and the arm
# returns nothing. With the real embedder the dense arm carries it.
QUERIES_YAML = """\
- id: pref
  query: "favorite color teal"
  expect_any: ["favorite color is teal"]
- id: deploy
  query: "we deployed the new billing service to production"
  expect_any: ["billing service"]
  answerable_by: [raw]
"""


class EvalHarnessTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = make_db(seed=False)
        self.team = seed_team(self.conn)
        make_session(self.conn, self.team)
        self.caller = self.team.principal("alice")
        self.embedder = HashEmbedder()
        self.client = SearchableQdrant()

        scope_id = self.team.scope_of("alice")
        with self.conn.transaction():
            for content in (
                "my favorite color is teal by the way",
                "we deployed the new billing service to production",
            ):
                store.add_message(
                    self.conn,
                    session_id="s-1",
                    user_id=self.team.alice_id,
                    scope_id=scope_id,
                    agent_id="chat",
                    role="user",
                    content=content,
                )
            store.add_memory(
                self.conn,
                scope_id=scope_id,
                author_id=self.team.alice_id,
                text="favorite color is teal",
                kind="preference",
                source_role="user",
                review_status="confirmed",
            )
        outbox.drain(self.conn, self.client, self.embedder, limit=50)

        path = Path(tempfile.mkdtemp()) / "queries.yaml"
        path.write_text(QUERIES_YAML)
        self.cases = load_cases(path)

    def tearDown(self) -> None:
        self.conn.close()

    def _score(self, cases, **kw):
        return score(
            self.conn,
            self.client,
            self.embedder,
            self.caller.scopes(),
            cases,
            limit=kw.pop("limit", 10),
            **kw,
        )

    def test_load_cases_parses_answerable_by(self) -> None:
        by_id = {case.id: case for case in self.cases}
        self.assertEqual(by_id["pref"].answerable_by, ("raw", "memories"))
        self.assertEqual(by_id["deploy"].answerable_by, ("raw",))

    def test_memories_target_scores_end_to_end(self) -> None:
        cases = [c for c in self.cases if "memories" in c.answerable_by]
        m = self._score(cases, target="memories")
        self.assertEqual(m["cases"], 1)
        self.assertEqual(m["recall"], 1.0)
        self.assertEqual(m["rejects"], 0)
        self.assertGreater(m["mean_tokens"], 0)

    def test_raw_target_scores_end_to_end(self) -> None:
        m = self._score(self.cases, target="raw")
        self.assertEqual(m["cases"], 2)
        self.assertEqual(m["recall"], 1.0)
        # The exact rank is the stub embedder's hash talking, not the harness;
        # what this asserts is that reciprocal rank was computed at all.
        self.assertGreater(m["mrr"], 0.0)
        self.assertEqual(m["ranked"], 2)

    def test_the_eval_is_scored_within_one_principals_scopes(self) -> None:
        """A score computed over the whole database would measure a view no
        caller has. Hand the scorer a scope set nobody can read and it must
        find nothing, rather than falling back to everything."""
        m = score(
            self.conn,
            self.client,
            self.embedder,
            [self.team.scope_of("bob")],
            [c for c in self.cases if "memories" in c.answerable_by],
            target="memories",
            limit=10,
        )
        self.assertEqual(m["recall"], 0.0)

    def test_another_users_turns_are_not_searchable(self) -> None:
        m = score(
            self.conn,
            self.client,
            self.embedder,
            [self.team.scope_of("bob")],
            self.cases,
            target="raw",
            limit=10,
        )
        self.assertEqual(m["recall"], 0.0)


if __name__ == "__main__":
    unittest.main()
