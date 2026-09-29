"""Cross-encoder reranking, query rewrites with rank fusion, and forgetting.

All three are optional and all three must degrade to the plain behaviour: a
reranker that cannot load keeps the hybrid order, a rewrite that fails searches
the original query alone, and forgetting without a judge still bounds what it
selects and defaults to a dry run.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from memkit import api, config, providers, rerank, retrieval
from tests.fixtures import fake_provider
from tests.httpharness import ApiTestCase


def scored(memory_id: str, score: float, text: str = "") -> retrieval.Scored:
    return retrieval.Scored(
        id=memory_id,
        text=text or memory_id,
        kind="fact",
        context={},
        tags=[],
        source_role="user",
        similarity=0.0,
        lexical=0.0,
        entity=0.0,
        importance=0.5,
        recency=1.0,
        score=score,
        updated_at="2026-09-29T00:00:00Z",
    )


class CrossEncoderTest(unittest.TestCase):
    def test_the_head_is_reordered_by_the_cross_encoder(self) -> None:
        class Model:
            def predict(self, pairs):
                return [5.0 if "dislikes" not in text else -5.0 for _, text in pairs]

        reranker = rerank.CrossEncoderReranker("fake", model=Model(), head=2)
        ranked = reranker.rerank(
            "does the user like dark mode",
            [
                scored("a", 0.9, "The user dislikes dark mode"),
                scored("b", 0.8, "The user likes dark mode"),
                scored("c", 0.1, "tail stays where it was"),
            ],
        )
        self.assertEqual([item.id for item in ranked], ["b", "a", "c"])

    def test_a_failing_model_keeps_the_hybrid_order(self) -> None:
        class Broken:
            def predict(self, pairs):
                raise RuntimeError("out of memory")

        candidates = [scored("a", 0.9), scored("b", 0.8)]
        self.assertEqual(
            rerank.CrossEncoderReranker("fake", model=Broken()).rerank("q", candidates),
            candidates,
        )

    def test_it_is_off_unless_configured(self) -> None:
        self.assertIsNone(rerank.from_settings(config.Settings(rerank_model="")))
        self.assertIsNotNone(rerank.from_settings(config.Settings(rerank_model="some/model")))


class FusionTest(unittest.TestCase):
    def test_agreement_between_phrasings_beats_one_high_score(self) -> None:
        original = retrieval.Explain(chosen=[scored("x", 0.9), scored("y", 0.5)], used_tokens=0)
        first = retrieval.Explain(chosen=[scored("y", 0.4), scored("z", 0.3)], used_tokens=0)
        second = retrieval.Explain(chosen=[scored("y", 0.4)], used_tokens=0)
        fused = retrieval.fuse([original, first, second], budget_tokens=1000)
        self.assertEqual([item.id for item in fused.chosen], ["y", "x", "z"])
        self.assertEqual(fused.timings["fused_queries"], 3.0)

    def test_the_budget_applies_after_fusion(self) -> None:
        original = retrieval.Explain(
            chosen=[scored("x", 0.9, "one two three"), scored("y", 0.5, "four five six")],
            used_tokens=0,
        )
        fused = retrieval.fuse([original], budget_tokens=3, limit=5)
        self.assertEqual([item.id for item in fused.chosen], ["x"])


class RewriteAndForgetApiTest(ApiTestCase):
    def judge(self, handler):
        """Route judge calls to `handler` as if a real judge were configured."""
        self.enterContext(patch.object(config.get_settings(), "judge_model", "fake-judge"))
        self.enterContext(patch("memkit.rewrite.judge_configured", return_value=True))
        self.enterContext(patch("memkit.routers.memory.judge_configured", return_value=True))
        self.enterContext(fake_provider(handler))

    def test_rewrites_are_searched_and_reported(self) -> None:
        wanted = self.seed_memory(text="Alice moved to Lisbon in April", kind="fact")

        def handler(**kwargs):
            return providers.ProviderResult(
                raw={"queries": ["Alice moved to", "where do I live", "where do I live"]},
                input_tokens=100,
                output_tokens=20,
            )

        self.judge(handler)
        response = self.client.post(
            "/v1/memories/search",
            headers=self.auth,
            json={"query": "where do I live", "rewrite_query": True},
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        # Duplicates and the original itself are not searched twice.
        self.assertEqual(body["rewrites"], ["Alice moved to"])
        self.assertIn(wanted, [m["id"] for m in body["memories"]])
        run = self.db.execute("SELECT kind,output FROM judge_runs").fetchone()
        # A rewrite is the query in other words; it is not stored.
        self.assertEqual((run["kind"], run["output"]), ("rewrite", None))

    def test_a_rewrite_failure_searches_the_original_alone(self) -> None:
        self.seed_memory(text="Alice prefers pnpm", kind="preference")
        response = self.client.post(
            "/v1/memories/search",
            headers=self.auth,
            json={"query": "pnpm", "rewrite_query": True},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["rewrites"], [])
        self.assertTrue(response.json()["memories"])

    def test_forgetting_by_ids_is_a_dry_run_until_asked(self) -> None:
        target = self.seed_memory(text="Project Titan ships in Q3", kind="fact")
        preview = self.client.post(
            "/v1/memories/forget", headers=self.auth, json={"ids": [target]}
        ).json()
        self.assertEqual((preview["dry_run"], preview["forgotten"]), (True, []))
        self.assertEqual([c["id"] for c in preview["candidates"]], [target])
        applied = self.client.post(
            "/v1/memories/forget",
            headers=self.auth,
            json={"ids": [target], "dry_run": False, "reason": "project cancelled"},
        ).json()
        self.assertEqual(applied["forgotten"], [target])
        row = self.db.execute(
            "SELECT status,forget_reason FROM memories WHERE id=%s", (target,)
        ).fetchone()
        self.assertEqual((row["status"], row["forget_reason"]), ("archived", "project cancelled"))
        search = self.client.post(
            "/v1/memories/search", headers=self.auth, json={"query": "Project Titan"}
        ).json()
        self.assertNotIn(target, [m["id"] for m in search["memories"]])

    def test_nobody_forgets_what_they_cannot_write(self) -> None:
        theirs = self.seed_memory(text="Alice's private plan", kind="fact")
        response = self.client.post(
            "/v1/memories/forget",
            headers=self.as_bob,
            json={"ids": [theirs], "dry_run": False},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["candidates"], [])
        self.assertEqual(self.scalar("SELECT status FROM memories WHERE id=%s", theirs), "active")

    def test_the_judge_keeps_only_what_the_request_is_about(self) -> None:
        titan = self.seed_memory(text="Project Titan ships in Q3", kind="fact")
        other = self.seed_memory(text="Alice named her cat Titan after a project", kind="fact")
        seen = {}

        def handler(**kwargs):
            seen["prompt"] = kwargs["prompt"]
            number = next(
                line.split(".")[0]
                for line in kwargs["prompt"].splitlines()
                if "ships in Q3" in line and line[:1].isdigit()
            )
            return providers.ProviderResult(raw={"forget": [int(number), 99]})

        self.judge(handler)
        body = self.client.post(
            "/v1/memories/forget",
            headers=self.auth,
            json={"query": "Project Titan", "threshold": 0.0, "dry_run": False},
        ).json()
        self.assertTrue(body["verified"])
        self.assertEqual(body["forgotten"], [titan])
        self.assertEqual(self.scalar("SELECT status FROM memories WHERE id=%s", other), "active")
        # The cat was a candidate the judge saw and declined.
        self.assertIn("named her cat Titan", seen["prompt"])

    def test_exactly_one_selector_is_required(self) -> None:
        for payload in ({}, {"ids": ["x"], "query": "y"}):
            response = self.client.post("/v1/memories/forget", headers=self.auth, json=payload)
            self.assertEqual(response.status_code, 422, payload)


assert api.app is not None
