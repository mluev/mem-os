"""Dreaming: links and inferences across memories, verified before any write.

The model proposes; the database decides. Every proposal here is checked for
the thing that would make it harmful if trusted: a supersession that runs
backwards in time, an inference that rests on one memory or none, a guess below
the confidence floor, a claim already stated, a scope the caller cannot write.
"""

from __future__ import annotations

import re
import unittest
from types import SimpleNamespace

from memkit import dream, providers, retrieval, store
from memkit.principal import ScopeForbidden
from tests.fixtures import StubEmbedder, StubQdrant, fake_provider, make_db, seed_team

MODEL = "fake-dreamer"


class NeighbourQdrant(StubQdrant):
    """Every active memory in the requested scope is a close neighbour."""

    def __init__(self, conn) -> None:
        super().__init__()
        self.conn = conn

    def query_points(self, collection_name, **kwargs):
        rows = self.conn.execute("SELECT id FROM memories WHERE status='active'").fetchall()
        return SimpleNamespace(points=[SimpleNamespace(id=str(r["id"]), score=0.8) for r in rows])


class DreamTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = make_db(seed=False)
        self.team = seed_team(self.conn)
        self.scope = self.team.scope_of("alice")
        self.qdrant = NeighbourQdrant(self.conn)
        self.calls: list[str] = []

    def tearDown(self) -> None:
        self.conn.close()

    def add(self, text: str, said: str, **kw) -> str:
        with self.conn.transaction():
            return store.add_memory(
                self.conn,
                scope_id=kw.pop("scope_id", self.scope),
                author_id=self.team.alice_id,
                text=text,
                kind=kw.pop("kind", "fact"),
                source_role=kw.pop("source_role", "user"),
                document_date=said,
                **kw,
            )

    def dream(self, answer, **kw):
        """Run a dream whose model answers by memory text, not by number."""

        def handler(**kwargs):
            prompt = kwargs["prompt"]
            self.calls.append(prompt)
            numbers = {
                text: int(number)
                for number, text in re.findall(r"^(\d+)\. \([^)]*\) (.+)$", prompt, re.M)
            }
            return providers.ProviderResult(raw=answer(numbers), input_tokens=500, output_tokens=80)

        with fake_provider(handler):
            return dream.run(
                self.conn,
                scope_id=kw.pop("scope_id", self.scope),
                user_id=kw.pop("user_id", self.team.alice_id),
                client=self.qdrant,
                embedder=StubEmbedder(),
                model=MODEL,
                monthly_limit_usd=kw.pop("monthly_limit_usd", 10.0),
                since=None,
                **kw,
            )

    def row(self, memory_id: str):
        return self.conn.execute("SELECT * FROM memories WHERE id=%s", (memory_id,)).fetchone()

    def test_links_and_an_inference_are_verified_then_written(self) -> None:
        pm = self.add("Alex is a PM at Stripe", "2026-01-10T00:00:00Z")
        apis = self.add("Alex spends every day on payment APIs", "2026-02-01T00:00:00Z")
        porto = self.add("Alice lives in Porto", "2026-01-05T00:00:00Z")
        lisbon = self.add("Alice lives in Lisbon", "2026-04-02T00:00:00Z")

        outcome = self.dream(
            lambda n: {
                "links": [
                    {
                        "from": n["Alice lives in Lisbon"],
                        "to": n["Alice lives in Porto"],
                        "relation": "updates",
                        "reason": "moved",
                    }
                ],
                "inferences": [
                    {
                        "text": "Alex works on Stripe's payments product",
                        "kind": "fact",
                        "premises": [
                            n["Alex is a PM at Stripe"],
                            n["Alex spends every day on payment APIs"],
                        ],
                        "confidence": 0.85,
                    }
                ],
            },
            max_clusters=1,
        )

        self.assertEqual((outcome.superseded, outcome.inferred), (1, 1), outcome.as_dict())
        self.assertEqual(self.row(porto)["status"], "superseded")
        self.assertEqual(str(self.row(porto)["superseded_by"]), lisbon)
        inferred = self.conn.execute(
            "SELECT * FROM memories WHERE source_role='inference'"
        ).fetchone()
        self.assertEqual(inferred["text"], "Alex works on Stripe's payments product")
        self.assertEqual(inferred["review_status"], "pending")
        self.assertEqual(inferred["extraction_version"], "dream-d1")
        premises = {
            str(r["to_id"])
            for r in self.conn.execute(
                "SELECT to_id FROM memory_relations WHERE from_id=%s AND relation='derives'",
                (inferred["id"],),
            )
        }
        self.assertEqual(premises, {pm, apis})
        run = self.conn.execute("SELECT kind,prompt_version,input FROM judge_runs").fetchone()
        self.assertEqual((run["kind"], run["prompt_version"]), ("dream", "d1"))
        # The run records ids, never the prompt: it can carry other people's text.
        self.assertNotIn("Stripe", str(run["input"]))

    def test_an_update_that_runs_backwards_in_time_is_refused(self) -> None:
        older = self.add("Alice lives in Lisbon", "2026-01-05T00:00:00Z")
        newer = self.add("Alice lives in Porto", "2026-04-02T00:00:00Z")
        outcome = self.dream(
            lambda n: {
                "links": [
                    {
                        "from": n["Alice lives in Lisbon"],
                        "to": n["Alice lives in Porto"],
                        "relation": "updates",
                        "reason": "",
                    }
                ],
                "inferences": [],
            }
        )
        self.assertEqual(outcome.superseded, 0)
        self.assertIn({"reason": "update_not_forward"}, outcome.skipped)
        self.assertEqual({self.row(older)["status"], self.row(newer)["status"]}, {"active"})

    def test_weak_or_single_premise_inferences_are_not_written(self) -> None:
        self.add("Alex is a PM at Stripe", "2026-01-10T00:00:00Z")
        self.add("Alex likes coffee", "2026-02-01T00:00:00Z")
        outcome = self.dream(
            lambda n: {
                "links": [],
                "inferences": [
                    {
                        "text": "Alex drinks coffee at Stripe",
                        "kind": "fact",
                        "premises": [n["Alex is a PM at Stripe"], n["Alex likes coffee"]],
                        "confidence": 0.4,
                    },
                    {
                        "text": "Alex is senior",
                        "kind": "fact",
                        "premises": [n["Alex is a PM at Stripe"], 99],
                        "confidence": 0.95,
                    },
                ],
            }
        )
        self.assertEqual(outcome.inferred, 0)
        reasons = [item["reason"] for item in outcome.skipped]
        self.assertEqual(reasons, ["low_confidence", "invalid_inference"])

    def test_an_inference_already_stated_is_not_written_twice(self) -> None:
        self.add("Alex is a PM at Stripe", "2026-01-10T00:00:00Z")
        self.add("Alex works on payments at Stripe", "2026-02-01T00:00:00Z")
        outcome = self.dream(
            lambda n: {
                "links": [],
                "inferences": [
                    {
                        "text": "Alex works on payments at Stripe",
                        "kind": "fact",
                        "premises": [1, 2],
                        "confidence": 0.9,
                    }
                ],
            }
        )
        self.assertEqual(outcome.inferred, 0)
        self.assertEqual(outcome.skipped, [{"reason": "already_stated"}])

    def test_inferences_are_never_premises(self) -> None:
        self.add("Alex is a PM at Stripe", "2026-01-10T00:00:00Z")
        self.add("Alex works on payments", "2026-02-01T00:00:00Z", source_role="inference")
        outcome = self.dream(lambda n: {"links": [], "inferences": []})
        # One stated memory and one guess make no cluster: nothing to ask.
        self.assertEqual((outcome.clusters, self.calls), (0, []))

    def test_a_dry_run_plans_without_calling_a_model(self) -> None:
        self.add("Alex is a PM at Stripe", "2026-01-10T00:00:00Z")
        self.add("Alex leads a team of five", "2026-02-01T00:00:00Z")
        outcome = self.dream(lambda n: {"links": [], "inferences": []}, dry_run=True)
        self.assertEqual((outcome.clusters, outcome.calls, self.calls), (1, 0, []))
        self.assertEqual(len(outcome.planned[0]), 2)

    def test_the_monthly_ceiling_stops_dreaming(self) -> None:
        self.add("Alex is a PM at Stripe", "2026-01-10T00:00:00Z")
        self.add("Alex leads a team of five", "2026-02-01T00:00:00Z")
        outcome = self.dream(lambda n: {"links": [], "inferences": []}, monthly_limit_usd=0.0)
        self.assertEqual(outcome.skipped, [{"reason": "monthly_cost_limit_reached"}])
        self.assertEqual(self.calls, [])

    def test_nobody_dreams_in_a_scope_they_cannot_write(self) -> None:
        self.add("Alex is a PM at Stripe", "2026-01-10T00:00:00Z")
        with self.assertRaises(ScopeForbidden):
            self.dream(lambda n: {"links": [], "inferences": []}, user_id=self.team.bob_id)

    def test_one_dream_per_scope_waits_in_the_queue(self) -> None:
        first = dream.queue(
            self.conn, scope_id=self.scope, user_id=self.team.alice_id, max_clusters=4
        )
        second = dream.queue(
            self.conn, scope_id=self.scope, user_id=self.team.alice_id, max_clusters=4
        )
        self.assertIsNotNone(first)
        self.assertIsNone(second)

    def test_a_confirmed_inference_ranks_like_a_stated_fact(self) -> None:
        stated = self.add("Alex works on payments at Stripe", "2026-01-10T00:00:00Z")
        guessed = self.add(
            "Alex works on payments infrastructure", "2026-01-10T00:00:00Z", source_role="inference"
        )
        policy = retrieval.load_policy(self.conn, "core-retrieval-v2")
        caller = self.team.principal("alice")

        def scores():
            chosen = retrieval.explain(
                self.conn,
                StubQdrant(),
                StubEmbedder(),
                query="payments",
                scope_ids=caller.scopes(),
                policy=policy,
            ).chosen
            return {item.id: item.score for item in chosen}

        before = scores()
        self.assertLess(before[guessed], before[stated])
        with self.conn.transaction():
            store.set_review_status(
                self.conn,
                memory_id=guessed,
                scopes=[self.scope],
                review_status="confirmed",
                reviewed_by=self.team.alice_id,
            )
        after = scores()
        self.assertAlmostEqual(after[guessed] - before[guessed], policy.inference_penalty, 4)
