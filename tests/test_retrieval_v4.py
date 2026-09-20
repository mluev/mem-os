"""Hybrid retrieval: three arms fused, then filtered, then allowed to abstain.

The claims here are the ones an agent's answer depends on. An exact identifier
has to survive even when nothing else in the query is similar; an expired or
model-authored fact has to be dropped before it can be read back as established
truth; and a query about something the store knows nothing about has to return
nothing rather than the least-bad row.

A result also has to say where it came from. On a team instance one search
returns facts from several scopes at once, so a caller that cannot tell "the
team decided" from "you decided" cannot use the answer, and a caller without the
revision cannot correct a fact it just found to be wrong.
"""

from __future__ import annotations

import unittest
from datetime import UTC, datetime

from memkit import retrieval, store
from tests.fixtures import StubEmbedder, StubQdrant, make_db, seed_team


class HybridRetrievalTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = make_db(seed=False)
        self.team = seed_team(self.conn)
        self.caller = self.team.principal("alice")
        self.qdrant = StubQdrant()
        self.embedder = StubEmbedder()

    def tearDown(self) -> None:
        self.conn.close()

    def _add(self, text: str, **kw) -> str:
        with self.conn.transaction():
            return store.add_memory(
                self.conn,
                scope_id=kw.pop("scope_id", self.caller.own_entity_id),
                author_id=kw.pop("author_id", self.team.alice_id),
                text=text,
                kind=kw.pop("kind", "fact"),
                source_role=kw.pop("source_role", "user"),
                **kw,
            )

    def _search(self, query: str, **kw):
        return retrieval.explain(
            self.conn,
            self.qdrant,
            self.embedder,
            query=query,
            scope_ids=self.caller.scopes(),
            **kw,
        )

    def test_a_context_filter_narrows_an_exact_term_match(self) -> None:
        wanted = self._add(
            "The deploy failed with ERR_X91Q",
            context={"workspace": "mem-os"},
        )
        self._add(
            "The deploy uses a release script",
            context={"workspace": "other"},
        )
        result = self._search(
            "ERR_X91Q",
            expression={"field": "context.workspace", "op": "eq", "value": "mem-os"},
        )
        self.assertEqual([item.id for item in result.chosen], [wanted])

    def test_an_expired_fact_and_a_model_authored_one_are_both_dropped(self) -> None:
        expired = self._add("Old launch code ABC-123", valid_until="2020-01-01T00:00:00Z")
        untrusted = self._add("Agent guessed launch code ABC-123", source_role="agent")
        result = self._search("ABC-123", now=datetime(2026, 8, 9, tzinfo=UTC))
        self.assertEqual(result.chosen, [])
        self.assertIn(expired, result.dropped_validity)
        self.assertIn(untrusted, result.dropped_trust)

    def test_a_query_about_nothing_it_knows_stays_silent(self) -> None:
        self._add("Prefers pnpm for JavaScript packages")
        result = self._search("quantum chromodynamics")
        self.assertEqual(result.chosen, [])

    def test_a_result_names_the_scope_it_came_from(self) -> None:
        """One search spans several scopes, so each hit has to place itself."""
        self._add("We always squash-merge before deploy", scope_id=self.team.team_id)
        [hit] = self._search("squash-merge").chosen
        self.assertEqual(hit.scope, "Test Team")
        self.assertEqual(hit.scope_slug, "test-team")
        self.assertEqual(hit.as_dict()["scope"], "Test Team")

    def test_a_result_names_the_person_it_is_about(self) -> None:
        self._add(
            "Bob owns the deploy pipeline",
            scope_id=self.team.team_id,
            subject_id=self.team.scope_of("bob"),
        )
        [hit] = self._search("deploy").chosen
        self.assertEqual(hit.subject, "Bob Petrov")
        self.assertEqual(hit.subject_slug, "bob-petrov")

    def test_a_fact_about_nobody_in_particular_has_no_subject(self) -> None:
        self._add("Deploys run on Friday mornings")
        [hit] = self._search("deploys").chosen
        self.assertIsNone(hit.subject)
        self.assertIsNone(hit.subject_slug)

    def test_a_result_carries_the_revision_a_correction_needs(self) -> None:
        """A fix is a PATCH with `expected_revision`; without it, nothing to send."""
        memory_id = self._add("Deploys run on Friday mornings")
        [first] = self._search("deploys").chosen
        self.assertEqual(first.revision, 1)
        with self.conn.transaction():
            store.update_memory(
                self.conn,
                memory_id=memory_id,
                scopes=self.caller.scopes(),
                expected_revision=first.revision,
                text="Deploys run on Tuesday mornings",
                kind="fact",
                context={},
                tags=[],
                importance=0.6,
                confidence=0.9,
                valid_until=None,
            )
        [second] = self._search("deploys").chosen
        self.assertEqual(second.revision, 2)
        self.assertEqual(second.as_dict()["revision"], 2)

    def test_a_result_reports_whether_a_human_confirmed_it(self) -> None:
        self._add("Deploys run on Friday mornings", review_status="pending")
        [hit] = self._search("deploys").chosen
        self.assertEqual(hit.review_status, "pending")

    def test_a_teammates_private_fact_is_never_reachable(self) -> None:
        self._add(
            "The deploy failed with ERR_X91Q",
            scope_id=self.team.scope_of("bob"),
            author_id=self.team.bob_id,
        )
        self.assertEqual(self._search("ERR_X91Q").chosen, [])


class PolicyTest(unittest.TestCase):
    """The weights and the abstention floor are data, not code."""

    def setUp(self) -> None:
        self.conn = make_db(seed=False)
        seed_team(self.conn)

    def tearDown(self) -> None:
        self.conn.close()

    def test_the_seeded_neutral_policy_is_the_documented_one(self) -> None:
        policy = retrieval.load_policy(self.conn, "neutral-v1")
        self.assertEqual(policy.id, "core-retrieval-neutral-v1")
        self.assertAlmostEqual(policy.dense_weight, 0.60)
        self.assertAlmostEqual(policy.lexical_weight, 0.30)
        self.assertAlmostEqual(policy.entity_weight, 0.10)
        self.assertAlmostEqual(policy.min_relevance, 0.18)
        self.assertEqual(policy.allowed_source_roles, frozenset({"user", "manual", "tool"}))

    def test_an_unknown_policy_is_refused_rather_than_defaulted(self) -> None:
        """Silently falling back would run a search under weights nobody chose."""
        with self.assertRaises(ValueError):
            retrieval.load_policy(self.conn, "no-such-policy")


if __name__ == "__main__":
    unittest.main()
