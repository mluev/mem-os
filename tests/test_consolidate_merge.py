"""Semantic consolidation merge (decisions/0056): clustered, LLM-confirmed,
provenance-preserving, reversible.

Offline: clustering runs on a controllable embedder; the merge provider is
monkeypatched. The important claims:

* clusters form only within one context and never restate exact groups;
* a null merge answer ("these differ") leaves the store untouched;
* a confirmed merge supersedes members reversibly, inherits every evidence
  row, logs a `judge_runs` row with kind='merge', and the survivor carries
  provenance.weakest() of its members — a merge cannot launder assistant
  text into a user-sourced fact;
* dry-run and merge=False change nothing (the roadmap promise).
"""

from __future__ import annotations

import unittest
from unittest import mock

from memkit import consolidate, providers, store
from memkit.db import transaction
from tests.fixtures import OWNER, make_db


class PairedEmbedder:
    """Embeds chosen text pairs as near-duplicates, everything else orthogonal."""

    def __init__(self, twins: set[frozenset[str]]) -> None:
        self.twins = twins
        self._axes: dict[str, int] = {}

    def _axis(self, text: str) -> int:
        for pair in self.twins:
            if text in pair:
                key = "|".join(sorted(pair))
                return self._axes.setdefault(key, len(self._axes))
        return self._axes.setdefault(text, len(self._axes))

    def encode_one(self, text: str) -> list[float]:
        vector = [0.0] * 64
        vector[self._axis(text)] = 1.0
        return vector

    def encode(self, texts: list[str], batch_size: int = 16) -> list[list[float]]:
        return [self.encode_one(t) for t in texts]


NAME_A = "User's name is Maga Luev"
NAME_B = "User's name is Maga (or MagaLoviev)"
DISTINCT = "Prefers pytest for tests"


class SemanticGroupTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = make_db()
        self.embedder = PairedEmbedder({frozenset({NAME_A, NAME_B})})

    def tearDown(self) -> None:
        self.conn.close()

    def _add(self, text: str, *, context: dict | None = None, role: str = "user") -> str:
        with transaction(self.conn):
            return store.add_memory(
                self.conn,
                owner_id=OWNER,
                text=text,
                kind="fact",
                context=context or {},
                source_role=role,
            )

    def test_twins_cluster_and_distinct_facts_do_not(self) -> None:
        a = self._add(NAME_A)
        b = self._add(NAME_B)
        self._add(DISTINCT)
        outcome = consolidate.plan(
            self.conn,
            owner_id=OWNER,
            stale_days=90,
            embedder=self.embedder,
            consolidate_cosine=0.92,
        )
        self.assertEqual(len(outcome.semantic_groups), 1)
        self.assertEqual(set(outcome.semantic_groups[0]), {a, b})

    def test_contexts_never_cross(self) -> None:
        self._add(NAME_A, context={"workspace": "one"})
        self._add(NAME_B, context={"workspace": "two"})
        outcome = consolidate.plan(
            self.conn,
            owner_id=OWNER,
            stale_days=90,
            embedder=self.embedder,
            consolidate_cosine=0.92,
        )
        self.assertEqual(outcome.semantic_groups, [])

    def test_exact_duplicate_groups_are_not_restated(self) -> None:
        self._add(NAME_A)
        self._add(NAME_A)
        outcome = consolidate.plan(
            self.conn,
            owner_id=OWNER,
            stale_days=90,
            embedder=self.embedder,
            consolidate_cosine=0.92,
        )
        self.assertEqual(len(outcome.candidate_groups), 1)
        self.assertEqual(outcome.semantic_groups, [])

    def test_without_embedder_plan_is_unchanged(self) -> None:
        self._add(NAME_A)
        self._add(NAME_B)
        outcome = consolidate.plan(self.conn, owner_id=OWNER, stale_days=90)
        self.assertEqual(outcome.semantic_groups, [])


class MergeApplyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = make_db()
        self.embedder = PairedEmbedder({frozenset({NAME_A, NAME_B})})
        with transaction(self.conn):
            self.a = store.add_memory(
                self.conn, owner_id=OWNER, text=NAME_A, kind="fact", source_role="user"
            )
            self.b = store.add_memory(
                self.conn, owner_id=OWNER, text=NAME_B, kind="fact", source_role="assistant"
            )
            message_id, _, _ = store.add_message(
                self.conn,
                session_id="s-1",
                owner_id=OWNER,
                agent_id="chat",
                role="user",
                content="меня зовут Maga Luev, кстати",
            )
            self.conn.execute(
                "INSERT INTO memory_sources(memory_id,message_id) VALUES (?,?)",
                (self.a, message_id),
            )
            self.conn.execute(
                """INSERT INTO memory_evidence
                   (memory_id,message_id,start_char,end_char,excerpt_sha256)
                   VALUES (?,?,0,10,'deadbeef')""",
                (self.a, message_id),
            )

    def tearDown(self) -> None:
        self.conn.close()

    def run_merge(self, merge_result: providers.ProviderResult):
        with mock.patch.object(providers, "call_merge", return_value=merge_result):
            return consolidate.run(
                self.conn,
                owner_id=OWNER,
                stale_days=90,
                demotion=0.1,
                dry_run=False,
                embedder=self.embedder,
                consolidate_cosine=0.92,
                merge=True,
                merge_model="gemini-3.5-flash-lite",
                monthly_limit_usd=15.0,
                gemini_api_key="test",
            )

    def actives(self) -> list[str]:
        return [
            row["id"] for row in self.conn.execute("SELECT id FROM memories WHERE status='active'")
        ]

    def test_confirmed_merge_supersedes_and_inherits_everything(self) -> None:
        outcome = self.run_merge(
            providers.ProviderResult(
                raw={"text": "User's name is Maga Luev (MagaLoviev)", "importance": 0.8},
                input_tokens=100,
                output_tokens=30,
            )
        )
        self.assertEqual(len(outcome.merged), 1)
        survivor = outcome.merged[0]["survivor"]
        self.assertEqual(self.actives(), [survivor])
        row = self.conn.execute("SELECT * FROM memories WHERE id=?", (survivor,)).fetchone()
        # assistant is weaker than user: the merge must not launder provenance.
        self.assertEqual(row["source_role"], "assistant")
        self.assertEqual(row["importance"], 0.8)
        for member in (self.a, self.b):
            state = self.conn.execute(
                "SELECT status,superseded_by FROM memories WHERE id=?", (member,)
            ).fetchone()
            self.assertEqual((state["status"], state["superseded_by"]), ("superseded", survivor))
        inherited = self.conn.execute(
            "SELECT COUNT(*) FROM memory_evidence WHERE memory_id=?", (survivor,)
        ).fetchone()[0]
        self.assertEqual(inherited, 1)
        run = self.conn.execute(
            "SELECT kind,model,cost_usd FROM judge_runs WHERE kind='merge'"
        ).fetchone()
        self.assertIsNotNone(run)
        self.assertGreater(run["cost_usd"], 0)

    def test_null_merge_answer_changes_nothing(self) -> None:
        outcome = self.run_merge(
            providers.ProviderResult(raw={"text": None, "importance": None, "reason": "differ"})
        )
        self.assertEqual(outcome.merged, [])
        self.assertEqual(set(self.actives()), {self.a, self.b})
        self.assertEqual(outcome.merge_skipped[0]["reason"], "null_merge")

    def test_provider_error_changes_nothing(self) -> None:
        outcome = self.run_merge(providers.ProviderResult(error="boom"))
        self.assertEqual(outcome.merged, [])
        self.assertEqual(set(self.actives()), {self.a, self.b})

    def test_dry_run_reports_but_never_merges(self) -> None:
        with mock.patch.object(providers, "call_merge") as call:
            outcome = consolidate.run(
                self.conn,
                owner_id=OWNER,
                stale_days=90,
                demotion=0.1,
                dry_run=True,
                embedder=self.embedder,
                consolidate_cosine=0.92,
                merge=True,
                merge_model="gemini-3.5-flash-lite",
                monthly_limit_usd=15.0,
            )
        call.assert_not_called()
        self.assertEqual(len(outcome.semantic_groups), 1)
        self.assertEqual(set(self.actives()), {self.a, self.b})

    def test_apply_without_merge_flag_never_calls_the_provider(self) -> None:
        with mock.patch.object(providers, "call_merge") as call:
            consolidate.run(
                self.conn,
                owner_id=OWNER,
                stale_days=90,
                demotion=0.1,
                dry_run=False,
                embedder=self.embedder,
                consolidate_cosine=0.92,
            )
        call.assert_not_called()
        self.assertEqual(set(self.actives()), {self.a, self.b})


if __name__ == "__main__":
    unittest.main()
