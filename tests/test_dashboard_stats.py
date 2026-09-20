"""Dashboard series execute real SQL and respect identities and reporting windows."""

from memkit import telemetry
from tests.httpharness import ApiTestCase


class DashboardStatisticsTest(ApiTestCase):
    def stats(self, name, *, headers=None, query=""):
        response = self.client.get(f"/v1/admin/stats/{name}{query}", headers=headers or self.auth)
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertEqual(result["bucket"], "day")
        self.assertIsInstance(result["series"], list)
        self.assertIsInstance(result["totals"], dict)
        return result

    def test_all_dashboard_series_execute_against_an_empty_database(self):
        for name in ("memories", "pipeline", "retrieval", "review", "entities", "users"):
            with self.subTest(name=name):
                self.stats(name)
        self.assertIsNone(self.stats("retrieval")["totals"]["p95_ms"])
        self.assertIsNone(self.stats("pipeline")["totals"]["acceptance_rate"])

    def test_memory_entity_and_review_counts_do_not_include_private_teammate_rows(self):
        self.seed_memory(text="Alice private fact")
        self.seed_memory(text="Shared project fact", scope=self.team.project_id)
        self.client.post(
            "/v1/memories",
            headers=self.as_bob,
            json={"text": "Bob private fact", "kind": "fact", "source_role": "manual"},
        )
        self.assertEqual(self.stats("memories", headers=self.as_bob)["totals"]["active"], 2)
        people = self.stats("entities", headers=self.as_bob)["totals"]["entities"]
        self.assertNotIn("alice", [p["slug"] for p in people])
        review = self.stats("review", headers=self.as_bob)
        self.assertEqual(review["totals"]["pending"], 1)
        self.assertEqual(sum(p["value"] for p in review["series"] if p["key"] == "opened"), 1)

    def test_people_counts_distinguish_the_window_from_all_time(self):
        old = self.seed_memory(text="Old preference")
        self.seed_memory(text="Recent preference")
        self.db.execute(
            "UPDATE memories SET created_at=now()-interval '60 days' WHERE id=%s", (old,)
        )
        people = self.stats("users", query="?days=7")["totals"]["people"]
        alice = next(p for p in people if p["handle"] == "alice")
        self.assertEqual((alice["memories"], alice["memories_all_time"]), (1, 2))
        response = self.client.get("/v1/admin/stats/users", headers=self.as_bob)
        self.assertEqual(response.status_code, 403)

    def test_retrieval_tail_latency_does_not_disappear_in_small_samples(self):
        for who, latency in (
            (self.team.alice_id, 10_000),
            (self.team.bob_id, 10),
            (self.team.bob_id, 1000),
        ):
            telemetry.record_retrieval_run(
                self.db,
                user_id=who,
                query_hash="fixture",
                policy_id="neutral-v1",
                results=[],
                timings={"total_ms": latency},
                used_tokens=0,
            )
        report = self.stats("retrieval", headers=self.as_bob)
        self.assertEqual(report["totals"]["searches"], 2)
        self.assertEqual(report["totals"]["p50_ms"], 505)
        self.assertEqual(report["totals"]["p95_ms"], 1000)
        self.assertEqual(next(p["value"] for p in report["series"] if p["key"] == "p95"), 1000)
