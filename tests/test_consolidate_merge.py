"""Semantic consolidation: clustered, LLM-confirmed, provenance-preserving,
reversible, and doubly gated.

Offline: clustering runs on a controllable embedder and the merge provider is
monkeypatched. The claims worth keeping:

* clusters form only within one scope and one context, and never restate a group
  the exact-duplicate path already owns;
* a null merge answer ("these differ") leaves the store untouched;
* a confirmed merge supersedes its members reversibly, inherits every evidence
  row, logs a `judge_runs` row with kind='merge', and the survivor carries
  `provenance.weakest()` of its members -- a merge cannot launder assistant text
  into a user-sourced fact, and cannot launder unreviewed text into a confirmed
  one either;
* dry-run and merge=False change nothing, so rewriting a fact takes both
  `--apply` and `--merge`;
* a cluster larger than the cap is reported, never merged, because a transitive
  chain can gather facts that are not pairwise similar at all.
"""

from __future__ import annotations

import unittest
import uuid
from datetime import UTC, datetime, timedelta
from unittest import mock

from memkit import consolidate, outbox, providers, store
from tests.fixtures import (
    CountingEmbedder,
    SearchableQdrant,
    StubEmbedder,
    make_db,
    make_session,
    seed_team,
)


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


class ConsolidateTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = make_db(seed=False)
        self.team = seed_team(self.conn)
        make_session(self.conn, self.team)
        self.caller = self.team.principal("alice")
        self.scope = self.caller.own_entity_id
        self.scopes = [self.scope]

    def tearDown(self) -> None:
        self.conn.close()

    def _add(self, text: str, **kw) -> str:
        with self.conn.transaction():
            return store.add_memory(
                self.conn,
                scope_id=kw.pop("scope_id", self.scope),
                author_id=kw.pop("author_id", self.team.alice_id),
                text=text,
                kind=kw.pop("kind", "fact"),
                context=kw.pop("context", {}),
                source_role=kw.pop("source_role", "user"),
                **kw,
            )

    def _actives(self) -> list[str]:
        return [
            str(row["id"])
            for row in self.conn.execute("SELECT id FROM memories WHERE status='active'")
        ]


class SemanticGroupTest(ConsolidateTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.embedder = PairedEmbedder({frozenset({NAME_A, NAME_B})})

    def _plan(self, *, scope_ids: list[str] | None = None, **kw):
        return consolidate.plan(
            self.conn,
            scope_ids=self.scopes if scope_ids is None else scope_ids,
            stale_days=90,
            embedder=kw.pop("embedder", self.embedder),
            consolidate_cosine=kw.pop("consolidate_cosine", 0.92),
            **kw,
        )

    def test_twins_cluster_and_distinct_facts_do_not(self) -> None:
        a = self._add(NAME_A)
        b = self._add(NAME_B)
        self._add(DISTINCT)
        outcome = self._plan()
        self.assertEqual(len(outcome.semantic_groups), 1)
        self.assertEqual(set(outcome.semantic_groups[0]), {a, b})

    def test_contexts_never_cross(self) -> None:
        """A fact stated in two workspaces is two facts by this repo's model.

        As with scopes, the four rows are mutually similar; only the context
        half of the grouping key keeps them apart.
        """
        one = {
            self._add(NAME_A, context={"workspace": "one"}),
            self._add(NAME_B, context={"workspace": "one"}),
        }
        two = {
            self._add(NAME_A, context={"workspace": "two"}),
            self._add(NAME_B, context={"workspace": "two"}),
        }
        outcome = self._plan()
        self.assertEqual(
            sorted(sorted(group) for group in outcome.semantic_groups),
            sorted([sorted(one), sorted(two)]),
        )

    def test_scopes_never_cross(self) -> None:
        """The same sentence in two scopes is two facts, and merging them would
        either publish a private claim or delete the shared copy a team relies on.

        Four rows, all mutually similar, two in each scope: with nothing but
        cosine they are one component of four. The `(scope_id, context)` key is
        what turns them into two clusters, each wholly inside one scope.
        """
        private = {self._add(NAME_A), self._add(NAME_B)}
        shared = {
            self._add(NAME_A, scope_id=self.team.team_id),
            self._add(NAME_B, scope_id=self.team.team_id),
        }
        outcome = self._plan(scope_ids=self.caller.scopes())
        self.assertEqual(
            sorted(sorted(group) for group in outcome.semantic_groups),
            sorted([sorted(private), sorted(shared)]),
        )
        self.assertEqual(outcome.oversized_groups, [])

    def test_exact_duplicate_groups_are_not_restated(self) -> None:
        self._add(NAME_A)
        self._add(NAME_A)
        outcome = self._plan()
        self.assertEqual(len(outcome.candidate_groups), 1)
        self.assertEqual(outcome.semantic_groups, [])

    def test_without_an_embedder_the_plan_is_unchanged(self) -> None:
        self._add(NAME_A)
        self._add(NAME_B)
        outcome = consolidate.plan(self.conn, scope_ids=self.scopes, stale_days=90)
        self.assertEqual(outcome.semantic_groups, [])

    def test_a_context_written_differently_still_groups(self) -> None:
        """jsonb normalises key order, so the grouping key is re-derived."""
        a = self._add(NAME_A, context={"workspace": "one", "repo": "mem-os"})
        b = self._add(NAME_B, context={"repo": "mem-os", "workspace": "one"})
        outcome = self._plan()
        self.assertEqual(len(outcome.semantic_groups), 1)
        self.assertEqual(set(outcome.semantic_groups[0]), {a, b})


class IndexedVectorsTest(ConsolidateTestCase):
    """Clustering reads the vectors the index already holds.

    Qdrant stores one vector per active memory -- the same vector the read path
    searches -- so embedding the whole store again to cluster it runs the model
    over data that is already sitting there. Rows the index is missing are
    embedded in a single batch, not one call per row.
    """

    def test_rows_already_in_the_index_are_never_re_embedded(self) -> None:
        client = SearchableQdrant()
        self._add(NAME_A)
        self._add(NAME_B)
        outbox.drain(self.conn, client, StubEmbedder(), limit=100)

        counter = CountingEmbedder()
        outcome = consolidate.plan(
            self.conn,
            scope_ids=self.scopes,
            stale_days=90,
            embedder=counter,
            consolidate_cosine=0.92,
            client=client,
        )
        self.assertEqual(len(outcome.semantic_groups), 1)
        self.assertEqual(counter.encode_calls, [])
        self.assertEqual(counter.encode_one_calls, 0)

    def test_rows_the_index_is_missing_cost_one_batch(self) -> None:
        client = SearchableQdrant()
        self._add(NAME_A)
        self._add(NAME_B)
        outbox.drain(self.conn, client, StubEmbedder(), limit=100)
        self._add("A third claim the index never saw")

        counter = CountingEmbedder()
        consolidate.plan(
            self.conn,
            scope_ids=self.scopes,
            stale_days=90,
            embedder=counter,
            consolidate_cosine=0.92,
            client=client,
        )
        self.assertEqual(counter.encode_calls, [1])


class MergeApplyTest(ConsolidateTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.embedder = PairedEmbedder({frozenset({NAME_A, NAME_B})})
        self.a = self._add(NAME_A, source_role="user")
        self.b = self._add(NAME_B, source_role="assistant")
        with self.conn.transaction():
            message_id, _, _ = store.add_message(
                self.conn,
                session_id="s-1",
                user_id=self.team.alice_id,
                scope_id=self.scope,
                agent_id="chat",
                role="user",
                content="меня зовут Maga Luev, кстати",
            )
            self.conn.execute(
                "INSERT INTO memory_sources(memory_id,message_id) VALUES (%s,%s)",
                (uuid.UUID(self.a), message_id),
            )
            self.conn.execute(
                """INSERT INTO memory_evidence
                   (memory_id,message_id,start_char,end_char,excerpt_sha256)
                   VALUES (%s,%s,0,10,'deadbeef')""",
                (uuid.UUID(self.a), message_id),
            )

    def _run_merge(self, merge_result: providers.ProviderResult):
        with mock.patch.object(providers, "call_merge", return_value=merge_result):
            return consolidate.run(
                self.conn,
                scope_ids=self.scopes,
                stale_days=90,
                demotion=0.1,
                dry_run=False,
                embedder=self.embedder,
                consolidate_cosine=0.92,
                merge=True,
                merge_model="gemini-3.5-flash-lite",
                monthly_limit_usd=15.0,
                gemini_api_key="test",
                user_id=self.team.alice_id,
            )

    def test_a_confirmed_merge_supersedes_and_inherits_everything(self) -> None:
        outcome = self._run_merge(
            providers.ProviderResult(
                raw={"text": "User's name is Maga Luev (MagaLoviev)", "importance": 0.8},
                input_tokens=100,
                output_tokens=30,
            )
        )
        self.assertEqual(len(outcome.merged), 1)
        survivor = outcome.merged[0]["survivor"]
        self.assertEqual(self._actives(), [survivor])

        row = self.conn.execute(
            "SELECT * FROM memories WHERE id=%s", (uuid.UUID(survivor),)
        ).fetchone()
        # assistant is weaker than user: the merge must not launder provenance.
        self.assertEqual(row["source_role"], "assistant")
        self.assertAlmostEqual(float(row["importance"]), 0.8, places=6)
        self.assertEqual(str(row["scope_id"]), self.scope)

        for member in (self.a, self.b):
            state = self.conn.execute(
                "SELECT status,superseded_by FROM memories WHERE id=%s", (uuid.UUID(member),)
            ).fetchone()
            self.assertEqual(state["status"], "superseded")
            self.assertEqual(str(state["superseded_by"]), survivor)

        inherited = self.conn.execute(
            "SELECT COUNT(*) AS n FROM memory_evidence WHERE memory_id=%s",
            (uuid.UUID(survivor),),
        ).fetchone()["n"]
        self.assertEqual(inherited, 1)

        run = self.conn.execute(
            "SELECT kind,model,cost_usd,user_id FROM judge_runs WHERE kind='merge'"
        ).fetchone()
        self.assertIsNotNone(run)
        self.assertGreater(float(run["cost_usd"]), 0)
        self.assertEqual(str(run["user_id"]), self.team.alice_id)

    def test_a_merge_of_unreviewed_facts_is_itself_unreviewed(self) -> None:
        """Confirmation means a human read the wording, and this wording is new."""
        outcome = self._run_merge(
            providers.ProviderResult(raw={"text": "User's name is Maga Luev (MagaLoviev)"})
        )
        survivor = outcome.merged[0]["survivor"]
        row = self.conn.execute(
            "SELECT review_status FROM memories WHERE id=%s", (uuid.UUID(survivor),)
        ).fetchone()
        self.assertEqual(row["review_status"], "pending")

    def test_a_merge_of_confirmed_facts_stays_confirmed(self) -> None:
        with self.conn.transaction():
            self.conn.execute(
                "UPDATE memories SET review_status='confirmed' WHERE id = ANY(%s)",
                ([uuid.UUID(self.a), uuid.UUID(self.b)],),
            )
        outcome = self._run_merge(
            providers.ProviderResult(raw={"text": "User's name is Maga Luev (MagaLoviev)"})
        )
        survivor = outcome.merged[0]["survivor"]
        row = self.conn.execute(
            "SELECT review_status FROM memories WHERE id=%s", (uuid.UUID(survivor),)
        ).fetchone()
        self.assertEqual(row["review_status"], "confirmed")

    def test_a_null_merge_answer_changes_nothing(self) -> None:
        outcome = self._run_merge(
            providers.ProviderResult(raw={"text": None, "importance": None, "reason": "differ"})
        )
        self.assertEqual(outcome.merged, [])
        self.assertEqual(set(self._actives()), {self.a, self.b})
        self.assertEqual(outcome.merge_skipped[0]["reason"], "null_merge")

    def test_a_provider_error_changes_nothing(self) -> None:
        outcome = self._run_merge(providers.ProviderResult(error="boom"))
        self.assertEqual(outcome.merged, [])
        self.assertEqual(set(self._actives()), {self.a, self.b})

    def test_a_dry_run_reports_but_never_merges(self) -> None:
        with mock.patch.object(providers, "call_merge") as call:
            outcome = consolidate.run(
                self.conn,
                scope_ids=self.scopes,
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
        self.assertEqual(set(self._actives()), {self.a, self.b})

    def test_apply_without_the_merge_flag_never_calls_the_provider(self) -> None:
        with mock.patch.object(providers, "call_merge") as call:
            consolidate.run(
                self.conn,
                scope_ids=self.scopes,
                stale_days=90,
                demotion=0.1,
                dry_run=False,
                embedder=self.embedder,
                consolidate_cosine=0.92,
            )
        call.assert_not_called()
        self.assertEqual(set(self._actives()), {self.a, self.b})


class ClusterCapTest(ConsolidateTestCase):
    """ADR 0032 stated a six-member cap; nothing enforced it.

    Connected components link facts transitively, so a chain of pairwise-similar
    texts can gather members that are not similar to each other at all. The
    whole cluster is then serialised into a prompt whose answer must fit 200
    characters, which is how a merge produces nonsense. `merge_cap` bounded the
    number of clusters, never their size.
    """

    def test_an_oversized_cluster_is_reported_and_never_merged(self) -> None:
        texts = [f"variation {i} of one crowded claim" for i in range(7)]
        ids = [self._add(text) for text in texts]
        embedder = PairedEmbedder({frozenset(texts)})

        calls: list[str] = []

        def never_called(**kwargs):
            calls.append(kwargs["prompt"])
            raise AssertionError("an oversized cluster reached the provider")

        with mock.patch.object(providers, "call_merge", side_effect=never_called):
            outcome = consolidate.run(
                self.conn,
                scope_ids=self.scopes,
                stale_days=90,
                demotion=0.1,
                dry_run=False,
                embedder=embedder,
                consolidate_cosine=0.9,
                merge=True,
                merge_model="gemini-3.5-flash-lite",
                monthly_limit_usd=10.0,
                gemini_api_key="k",
            )

        self.assertEqual(calls, [])
        self.assertEqual(outcome.semantic_groups, [])
        self.assertEqual(len(outcome.oversized_groups), 1)
        self.assertEqual(sorted(outcome.oversized_groups[0]), sorted(ids))
        self.assertEqual(len(self._actives()), 7)

    def test_a_cluster_at_the_cap_still_merges(self) -> None:
        texts = [
            f"variation {i} of one crowded claim" for i in range(consolidate.MAX_CLUSTER_MEMBERS)
        ]
        for text in texts:
            self._add(text)
        outcome = consolidate.plan(
            self.conn,
            scope_ids=self.scopes,
            stale_days=90,
            embedder=PairedEmbedder({frozenset(texts)}),
            consolidate_cosine=0.9,
        )
        self.assertEqual(len(outcome.semantic_groups), 1)
        self.assertEqual(outcome.oversized_groups, [])


class MergeCapTest(ConsolidateTestCase):
    """The per-run cluster budget, which had no test."""

    def test_clusters_beyond_the_cap_are_skipped_with_a_reason(self) -> None:
        twins: set[frozenset[str]] = set()
        for index in range(3):
            pair = {f"claim {index} stated one way", f"claim {index} stated another way"}
            twins.add(frozenset(pair))
            for text in sorted(pair):
                self._add(text)

        merges: list[str] = []

        def confirm(**kwargs):
            merges.append(kwargs["prompt"])
            return providers.ProviderResult(raw={"text": "one merged claim"})

        with mock.patch.object(providers, "call_merge", side_effect=confirm):
            outcome = consolidate.run(
                self.conn,
                scope_ids=self.scopes,
                stale_days=90,
                demotion=0.1,
                dry_run=False,
                embedder=PairedEmbedder(twins),
                consolidate_cosine=0.9,
                merge=True,
                merge_model="gemini-3.5-flash-lite",
                monthly_limit_usd=10.0,
                gemini_api_key="k",
                merge_cap=2,
            )

        self.assertEqual(len(merges), 2, "the cap did not bound provider calls")
        self.assertEqual(len(outcome.merged), 2)
        self.assertIn({"reason": "merge_cap", "groups_beyond_cap": 1}, outcome.merge_skipped)


class DecayFloorTest(ConsolidateTestCase):
    """Ageing discounts a fact; it must not erase one.

    Demotion subtracted 0.1 per pass with no lower bound, so ten nightly passes
    took an unretrieved fact to zero importance: last in the profile's ordering
    and no retrieval bonus at all.
    """

    def _stale(self, importance: float) -> str:
        memory_id = self._add(f"a fact nobody searches for, at {importance}", importance=importance)
        stamp = datetime.now(UTC) - timedelta(days=400)
        with self.conn.transaction():
            self.conn.execute(
                "UPDATE memories SET created_at=%s,updated_at=%s WHERE id=%s",
                (stamp, stamp, uuid.UUID(memory_id)),
            )
        return memory_id

    def _run(self) -> None:
        consolidate.run(
            self.conn,
            scope_ids=self.scopes,
            stale_days=90,
            demotion=0.1,
            dry_run=False,
            importance_floor=0.3,
        )

    def _importance(self, memory_id: str) -> float:
        return float(
            self.conn.execute(
                "SELECT importance FROM memories WHERE id=%s", (uuid.UUID(memory_id),)
            ).fetchone()["importance"]
        )

    def _revision(self, memory_id: str) -> int:
        return int(
            self.conn.execute(
                "SELECT revision FROM memories WHERE id=%s", (uuid.UUID(memory_id),)
            ).fetchone()["revision"]
        )

    def test_demotion_stops_at_the_floor(self) -> None:
        memory_id = self._stale(0.35)
        self._run()
        self.assertAlmostEqual(self._importance(memory_id), 0.3, places=6)

    def test_a_fact_at_the_floor_is_left_alone(self) -> None:
        memory_id = self._stale(0.3)
        self._run()
        self.assertAlmostEqual(self._importance(memory_id), 0.3, places=6)
        self.assertEqual(
            self._revision(memory_id), 1, "an unchanged fact should not gain a revision"
        )

    def test_demotion_happens_once_per_idle_period(self) -> None:
        """A second pass in the same period must not compound the discount."""
        memory_id = self._stale(0.6)
        self._run()
        after_first = self._importance(memory_id)
        self.assertAlmostEqual(after_first, 0.5, places=6)
        self._run()
        self.assertAlmostEqual(self._importance(memory_id), after_first, places=6)


class MergeProviderTest(unittest.TestCase):
    """Every provider call needs a deadline.

    The merge path built its own Gemini client without one, so a hung call
    blocked the single worker thread with no bound, for up to twenty clusters
    in a row. The extraction path had always set it.
    """

    def test_the_merge_client_gets_the_provider_timeout(self) -> None:
        with mock.patch("google.genai.Client") as client_cls:
            client_cls.return_value = mock.MagicMock()
            client_cls.return_value.models.generate_content.return_value = mock.MagicMock(
                text='{"merged_text": null}', usage_metadata=None
            )
            providers.call_merge(model="gemini-3.5-flash-lite", prompt="p", gemini_api_key="k")

        options = client_cls.call_args.kwargs["http_options"]
        self.assertEqual(options.timeout, int(providers.PROVIDER_TIMEOUT_SECONDS * 1000))


if __name__ == "__main__":
    unittest.main()
