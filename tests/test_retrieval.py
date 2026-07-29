"""Read-path tests: scoring, forgetting, scope rules, dedup, budget fill.

Fully deterministic — a stub hit object stands in for Qdrant and `now` is
injected, so no container, model, or API key is involved. The scope filter's
behaviour against real Qdrant was verified separately; what is tested here is
the ranking logic layered on top of it.
"""

from __future__ import annotations

import math
import sys
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from memkit import retrieval  # noqa: E402

NOW = datetime(2026, 7, 28, tzinfo=UTC)


def iso(days_ago: int) -> str:
    return (NOW - timedelta(days=days_ago)).isoformat().replace("+00:00", "Z")


class Hit:
    """Stands in for a qdrant ScoredPoint."""

    def __init__(
        self, text, score=0.8, *, type="fact", scope="user", scope_key=None,
        importance=0.5, days_ago=0, vector=None, id=None,
    ):
        self.id = id or text
        self.score = score
        self.vector = {"dense": vector} if vector else None
        self.payload = {
            "text": text, "type": type, "scope": scope, "scope_key": scope_key,
            "importance": importance, "updated_at": iso(days_ago),
            "status": "active",
        }


class TestAgeAndRecency(unittest.TestCase):
    def test_age_from_updated_at(self):
        self.assertEqual(retrieval.age_days(iso(44), NOW), 44)

    def test_age_never_negative(self):
        future = (NOW + timedelta(days=5)).isoformat().replace("+00:00", "Z")
        self.assertEqual(retrieval.age_days(future, NOW), 0)

    def test_malformed_and_empty_timestamps(self):
        self.assertEqual(retrieval.age_days("", NOW), 0)
        self.assertEqual(retrieval.age_days("not-a-date", NOW), 0)

    def test_fresh_fact_has_recency_one(self):
        self.assertAlmostEqual(retrieval.recency(0, "fact"), 1.0)

    def test_task_decays_almost_immediately(self):
        # tau=2 days. "fixing bug #14 today" must be worthless within days.
        self.assertLess(retrieval.recency(7, "task"), 0.04)

    def test_fact_survives_a_year(self):
        # tau=900. "lives in Tashkent" is still true a year later.
        self.assertGreater(retrieval.recency(365, "fact"), 0.6)

    def test_type_ordering_of_decay(self):
        # At the same age, the longer-lived types must score higher.
        at = 200
        order = ["fact", "preference", "skill", "project", "task"]
        vals = [retrieval.recency(at, t) for t in order]
        self.assertEqual(vals, sorted(vals, reverse=True))

    def test_unknown_type_uses_default_tau(self):
        self.assertAlmostEqual(
            retrieval.recency(180, "no-such-type"),
            math.exp(-180 / retrieval.TAU_DEFAULT),
        )


class TestScopeBoost(unittest.TestCase):
    def test_user_scope_is_background(self):
        self.assertEqual(
            retrieval.scope_boost("user", None, project="p", task="t"), 0.0
        )

    def test_matching_project(self):
        self.assertEqual(
            retrieval.scope_boost("project", "memkit", project="memkit", task=None),
            0.5,
        )

    def test_matching_task_outranks_project(self):
        proj = retrieval.scope_boost("project", "p", project="p", task="t")
        task = retrieval.scope_boost("task", "t", project="p", task="t")
        self.assertGreater(task, proj)

    def test_foreign_project_is_discarded_not_downweighted(self):
        # None means "wrong", not "less relevant". A fact from another repo has
        # no business in the answer at any rank.
        self.assertIsNone(
            retrieval.scope_boost("project", "notiky", project="memkit", task=None)
        )

    def test_foreign_task_is_discarded(self):
        self.assertIsNone(
            retrieval.scope_boost("task", "t-1", project=None, task="t-9")
        )

    def test_project_fact_with_no_key_is_discarded(self):
        self.assertIsNone(
            retrieval.scope_boost("project", None, project="memkit", task=None)
        )

    def test_scoped_fact_discarded_when_no_current_scope(self):
        self.assertIsNone(
            retrieval.scope_boost("project", "memkit", project=None, task=None)
        )


class TestScoreFormula(unittest.TestCase):
    def test_weights_sum_to_one(self):
        self.assertAlmostEqual(
            retrieval.W_SIMILARITY + retrieval.W_IMPORTANCE
            + retrieval.W_RECENCY + retrieval.W_SCOPE,
            1.0,
        )

    def test_arithmetic(self):
        got = retrieval.score_of(
            similarity=0.79, importance=0.8, recency_=0.5, boost=0.0
        )
        self.assertAlmostEqual(got, 0.55 * 0.79 + 0.20 * 0.8 + 0.15 * 0.5)

    def test_similarity_dominates_but_does_not_decide_alone(self):
        # The whole reason for reranking: a slightly less similar fact that is
        # important and fresh should beat a marginally closer stale one.
        stale = retrieval.score_of(similarity=0.80, importance=0.2, recency_=0.05, boost=0.0)
        fresh = retrieval.score_of(similarity=0.72, importance=0.9, recency_=1.0, boost=0.0)
        self.assertGreater(fresh, stale)


class TestRank(unittest.TestCase):
    def test_sorted_by_score_descending(self):
        hits = [
            Hit("weak", score=0.5, importance=0.1, days_ago=400, type="project"),
            Hit("strong", score=0.9, importance=0.9, days_ago=0),
        ]
        ranked = retrieval.rank(hits, project=None, task=None, now=NOW)
        self.assertEqual([s.text for s in ranked], ["strong", "weak"])

    def test_foreign_project_dropped_during_rank(self):
        hits = [
            Hit("mine", scope="project", scope_key="memkit", score=0.7),
            Hit("theirs", scope="project", scope_key="notiky", score=0.99),
        ]
        ranked = retrieval.rank(hits, project="memkit", task=None, now=NOW)
        # Higher cosine does not save it.
        self.assertEqual([s.text for s in ranked], ["mine"])

    def test_stale_task_sinks_below_durable_fact(self):
        hits = [
            Hit("today's bug", score=0.85, type="task", scope="user",
                importance=0.5, days_ago=30),
            Hit("lives in Tashkent", score=0.70, type="fact", scope="user",
                importance=0.9, days_ago=30),
        ]
        ranked = retrieval.rank(hits, project=None, task=None, now=NOW)
        self.assertEqual(ranked[0].text, "lives in Tashkent")

    def test_exposes_components_for_debugging(self):
        ranked = retrieval.rank([Hit("x")], project=None, task=None, now=NOW)
        d = ranked[0].as_dict()
        for field in ("score", "similarity", "importance", "recency",
                      "scope_boost", "age_days"):
            self.assertIn(field, d)

    def test_empty_input(self):
        self.assertEqual(retrieval.rank([], project=None, task=None, now=NOW), [])


class TestDedup(unittest.TestCase):
    def test_near_duplicate_removed_keeping_higher_score(self):
        a = [1.0, 0.0, 0.0]
        b = [0.999, 0.0447, 0.0]   # cosine ~0.999 against a
        hits = [
            Hit("kept", score=0.9, vector=a),
            Hit("dropped", score=0.8, vector=b),
        ]
        ranked = retrieval.rank(hits, project=None, task=None, now=NOW)
        kept = retrieval.dedup(ranked)
        self.assertEqual([s.text for s in kept], ["kept"])

    def test_distinct_facts_both_survive(self):
        hits = [
            Hit("pnpm", score=0.9, vector=[1.0, 0.0, 0.0]),
            Hit("pytest", score=0.8, vector=[0.0, 1.0, 0.0]),
        ]
        ranked = retrieval.rank(hits, project=None, task=None, now=NOW)
        self.assertEqual(len(retrieval.dedup(ranked)), 2)

    def test_missing_vectors_are_kept_not_silently_dropped(self):
        # If Qdrant was queried without with_vectors=True the dedup pass must
        # degrade to a no-op, never discard everything.
        hits = [Hit("a", score=0.9), Hit("b", score=0.8)]
        ranked = retrieval.rank(hits, project=None, task=None, now=NOW)
        self.assertTrue(all(s.vector is None for s in ranked))
        self.assertEqual(len(retrieval.dedup(ranked)), 2)

    def test_threshold_boundary(self):
        # Just under the 0.90 threshold: both kept.
        theta = math.acos(0.88)
        hits = [
            Hit("a", score=0.9, vector=[1.0, 0.0]),
            Hit("b", score=0.8, vector=[math.cos(theta), math.sin(theta)]),
        ]
        ranked = retrieval.rank(hits, project=None, task=None, now=NOW)
        self.assertEqual(len(retrieval.dedup(ranked)), 2)

    def test_three_way_cluster_collapses_to_one(self):
        hits = [
            Hit(f"dup{i}", score=0.9 - i * 0.01, vector=[1.0, i * 0.01])
            for i in range(3)
        ]
        ranked = retrieval.rank(hits, project=None, task=None, now=NOW)
        self.assertEqual([s.text for s in retrieval.dedup(ranked)], ["dup0"])


class TestBudgetFill(unittest.TestCase):
    def _scored(self, *lengths):
        return retrieval.rank(
            [Hit("x" * n, score=0.9 - i * 0.01) for i, n in enumerate(lengths)],
            project=None, task=None, now=NOW,
        )

    def test_respects_budget(self):
        out, used = retrieval.fill_budget(self._scored(300, 300, 300), 200)
        self.assertLessEqual(used, 200)
        self.assertEqual(len(out), 2)  # 300 chars ~ 100 tokens each

    def test_zero_budget_means_unlimited(self):
        ranked = self._scored(300, 300)
        out, _ = retrieval.fill_budget(ranked, 0)
        self.assertEqual(len(out), 2)

    def test_oversized_fact_is_skipped_not_terminating(self):
        # A single very long fact must not truncate everything cheaper behind it.
        ranked = self._scored(30_000, 60, 60)
        out, used = retrieval.fill_budget(ranked, 100)
        self.assertEqual(len(out), 2)
        self.assertLessEqual(used, 100)

    def test_preserves_score_order(self):
        out, _ = retrieval.fill_budget(self._scored(60, 60, 60), 800)
        scores = [s.score for s in out]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_recommended_range_is_reachable(self):
        # docs/05-retrieval.md puts the useful range at 600-1000 tokens.
        ranked = self._scored(*([150] * 40))
        out, used = retrieval.fill_budget(ranked, 800)
        self.assertGreater(len(out), 10)
        self.assertLessEqual(used, 800)


class TestScopeFilterShape(unittest.TestCase):
    def test_owner_and_status_are_mandatory(self):
        f = retrieval.scope_filter(owner_id="u-1", project=None, task=None)
        keys = {c.key for c in f.must}
        self.assertEqual(keys, {"owner_id", "status"})

    def test_should_grows_with_scope_context(self):
        none = retrieval.scope_filter(owner_id="u", project=None, task=None)
        both = retrieval.scope_filter(owner_id="u", project="p", task="t")
        self.assertEqual(len(none.should), 1)   # user scope only
        self.assertEqual(len(both.should), 3)

    def test_min_should_set_so_should_is_required_not_a_boost(self):
        # Without min_should, Qdrant can treat `should` as optional when `must`
        # is also present — which would let foreign-project facts through.
        f = retrieval.scope_filter(owner_id="u", project="p", task=None)
        self.assertIsNotNone(f.min_should)
        self.assertEqual(f.min_should.min_count, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
