"""HTTP contract tests for admin.py's routes.

`tests/test_admin_queries.py` already covers three of admin.py's data functions
by calling them directly. This covers the ~19 routes: status codes, optimistic
locking, the 422s the docs promise, and -- for the two expensive endpoints --
that `dry_run` genuinely makes no model call.

The dry-run assertions are written with the judge patched to *raise*. Asserting
"no call happened" by inspecting a mock is weaker: it passes if the code path
changed shape. Making the call explode means a regression fails loudly.
"""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from memkit import admin, consolidate as consolidator, judge, prompts
from memkit import reextract as reextractor
from tests.httpharness import ApiTestCase

STATS_KEYS = {"memories", "corpus", "backlog", "cost", "analytics", "health"}
PLAN_KEYS = {
    "messages_to_process", "sessions", "estimated_calls", "facts_to_supersede",
    "input_tokens_per_call", "output_tokens_per_call", "basis",
    "estimated_cost_usd",
}


def _boom(*args, **kwargs):
    raise AssertionError("a model call was made during a dry run")


class TestPatchMemory(ApiTestCase):
    def test_text_change_reembeds(self):
        mem_id = self.seed_memory()
        r = self.client.patch(
            f"/v1/memories/{mem_id}",
            json={"text": "Prefers pnpm, and refuses npm entirely"},
            headers=self.auth,
        )
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIs(r.json()["reembedded"], True)

    def test_importance_only_change_does_not_reembed(self):
        """A payload-only edit must not pay for an embedding."""
        mem_id = self.seed_memory()
        r = self.client.patch(
            f"/v1/memories/{mem_id}", json={"importance": 0.95}, headers=self.auth
        )
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIs(r.json()["reembedded"], False)
        self.assertEqual(self.qdrant.points[mem_id]["importance"], 0.95)

    def test_unknown_memory_is_404(self):
        r = self.client.patch(
            "/v1/memories/nope", json={"importance": 0.5}, headers=self.auth
        )
        self.assertEqual(r.status_code, 404)

    def test_stale_expected_updated_at_is_409(self):
        """Two dashboard tabs must not silently overwrite each other."""
        mem_id = self.seed_memory()
        r = self.client.patch(
            f"/v1/memories/{mem_id}",
            json={"text": "edited", "expected_updated_at": "2020-01-01T00:00:00Z"},
            headers=self.auth,
        )
        self.assertEqual(r.status_code, 409, r.text)
        self.assertNotEqual(
            self.scalar("SELECT text FROM memories WHERE id=?", mem_id), "edited"
        )

    def test_blank_text_is_422(self):
        mem_id = self.seed_memory()
        r = self.client.patch(
            f"/v1/memories/{mem_id}", json={"text": "   "}, headers=self.auth
        )
        self.assertEqual(r.status_code, 422)

    def test_status_vocabulary_excludes_superseded(self):
        """`superseded` is set by the supersede route, never by a hand edit."""
        mem_id = self.seed_memory()
        r = self.client.patch(
            f"/v1/memories/{mem_id}", json={"status": "superseded"}, headers=self.auth
        )
        self.assertEqual(r.status_code, 422)


class TestDeleteMemory(ApiTestCase):
    def test_soft_delete_keeps_the_row_and_drops_the_point(self):
        mem_id = self.seed_memory()
        r = self.client.delete(f"/v1/memories/{mem_id}", headers=self.auth)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIs(r.json()["hard"], False)
        self.assertEqual(
            self.scalar("SELECT status FROM memories WHERE id=?", mem_id), "expired"
        )
        self.assertNotIn(mem_id, self.qdrant.points)

    def test_hard_delete_removes_the_row(self):
        mem_id = self.seed_memory()
        r = self.client.delete(
            f"/v1/memories/{mem_id}", params={"hard": "true"}, headers=self.auth
        )
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIs(r.json()["hard"], True)
        self.assertEqual(
            self.scalar("SELECT COUNT(*) FROM memories WHERE id=?", mem_id), 0
        )

    def test_unknown_memory_is_404(self):
        self.assertEqual(
            self.client.delete("/v1/memories/nope", headers=self.auth).status_code, 404
        )


class TestSupersede(ApiTestCase):
    def test_supersede_links_the_pair(self):
        old = self.seed_memory(text="Uses React for the frontend", type="decision")
        new = self.seed_memory(text="Uses Vue 3 for the frontend", type="decision")
        r = self.client.post(
            f"/v1/memories/{old}/supersede", json={"by": new}, headers=self.auth
        )
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(
            self.scalar("SELECT superseded_by FROM memories WHERE id=?", old), new
        )
        self.assertEqual(
            self.scalar("SELECT status FROM memories WHERE id=?", old), "superseded"
        )

    def test_self_supersede_is_refused(self):
        mem_id = self.seed_memory()
        r = self.client.post(
            f"/v1/memories/{mem_id}/supersede", json={"by": mem_id}, headers=self.auth
        )
        self.assertIn(r.status_code, (409, 422), r.text)


class TestBulk(ApiTestCase):
    def test_expire_and_restore_round_trip(self):
        mem_id = self.seed_memory()
        r = self.client.post(
            "/v1/admin/memories/bulk",
            json={"ids": [mem_id], "op": "expire"},
            headers=self.auth,
        )
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["applied"], 1)
        self.assertNotIn(mem_id, self.qdrant.points)

        r = self.client.post(
            "/v1/admin/memories/bulk",
            json={"ids": [mem_id], "op": "restore"},
            headers=self.auth,
        )
        self.assertEqual(r.json()["applied"], 1)
        self.assertIn(mem_id, self.qdrant.points, "restore must re-index the point")

    def test_hard_delete_requires_confirm(self):
        mem_id = self.seed_memory()
        r = self.client.post(
            "/v1/admin/memories/bulk",
            json={"ids": [mem_id], "op": "hard_delete"},
            headers=self.auth,
        )
        self.assertEqual(r.status_code, 422)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM memories"), 1)

    def test_bounds(self):
        for body in ({"ids": [], "op": "expire"},
                     {"ids": ["a"], "op": "delete_everything"}):
            with self.subTest(body=body):
                r = self.client.post(
                    "/v1/admin/memories/bulk", json=body, headers=self.auth
                )
                self.assertEqual(r.status_code, 422)


class TestJudgeRuns(ApiTestCase):
    def _run(self, *, error=None, ops=None, cost=0.001):
        payload = json.dumps({"operations": ops if ops is not None else []})
        cur = self.db.execute(
            """INSERT INTO judge_runs (kind, model, prompt_version, input_json,
                                       output_json, error, cost_usd, created_at)
               VALUES ('extract', ?, ?, '{}', ?, ?, ?, '2026-07-01T00:00:00Z')""",
            (judge.DEFAULT_MODEL, prompts.DEFAULT_VERSION, payload, error, cost),
        )
        self.db.commit()
        return int(cur.lastrowid)

    def test_list_envelope(self):
        self._run()
        body = self.client.get("/v1/admin/judge-runs", headers=self.auth).json()
        self.assertKeys(body, {"items", "total", "limit", "offset"})
        self.assertEqual(body["total"], 1)

    def test_bad_sort_is_422(self):
        r = self.client.get(
            "/v1/admin/judge-runs", params={"sort": "cost_usd; DROP TABLE memories"},
            headers=self.auth,
        )
        self.assertEqual(r.status_code, 422)

    def test_has_ops_partitions_the_set(self):
        """The filter is a LIKE against serialised JSON, which is fragile."""
        self._run(ops=[])
        self._run(ops=[{"op": "ADD", "text": "Prefers pnpm"}])
        with_ops = self.client.get(
            "/v1/admin/judge-runs", params={"has_ops": "true"}, headers=self.auth
        ).json()
        without = self.client.get(
            "/v1/admin/judge-runs", params={"has_ops": "false"}, headers=self.auth
        ).json()
        self.assertEqual(with_ops["total"], 1)
        self.assertEqual(without["total"], 1)

    def test_errors_only(self):
        self._run()
        self._run(error="refusal")
        body = self.client.get(
            "/v1/admin/judge-runs", params={"errors_only": "true"}, headers=self.auth
        ).json()
        self.assertEqual(body["total"], 1)

    def test_detail_and_404(self):
        run_id = self._run(ops=[{"op": "ADD", "text": "Prefers pnpm"}])
        body = self.client.get(
            f"/v1/admin/judge-runs/{run_id}", headers=self.auth
        ).json()
        self.assertKeys(
            body,
            {"run", "input", "output", "ops", "memories", "messages",
             "window_recoverable"},
        )
        self.assertEqual(
            self.client.get("/v1/admin/judge-runs/9999", headers=self.auth).status_code,
            404,
        )


class TestStats(ApiTestCase):
    def test_shape(self):
        self.seed_memory()
        body = self.client.get("/v1/admin/stats", headers=self.auth).json()
        self.assertKeys(body, STATS_KEYS)
        self.assertKeys(
            body["memories"], {"total", "by_status", "by_type", "by_scope"},
            where="stats.memories: ",
        )

    def test_index_drift_is_qdrant_minus_sqlite(self):
        """The number that says "your index is lying to you"."""
        self.seed_memory()
        health = self.client.get("/v1/admin/stats", headers=self.auth).json()["health"]
        self.assertEqual(
            health["index_drift"], health["qdrant_memories"] - health["sqlite_active"]
        )
        self.assertEqual(health["index_drift"], 0)

    def test_drift_becomes_visible_when_the_index_lags(self):
        mem_id = self.seed_memory()
        self.qdrant.points.pop(mem_id)  # simulate a lost Qdrant write
        health = self.client.get("/v1/admin/stats", headers=self.auth).json()["health"]
        self.assertEqual(health["index_drift"], -1)


class TestSessionsAndMessages(ApiTestCase):
    def test_sessions_envelope_and_counters(self):
        self.seed_message()
        self.seed_message(content="I also prefer Vue 3 over React these days")
        body = self.client.get("/v1/admin/sessions", headers=self.auth).json()
        self.assertKeys(body, {"items", "total", "limit", "offset"})
        item = body["items"][0]
        self.assertKeys(
            item, {"message_count", "unprocessed_count", "memory_count"},
            where="session item: ",
        )
        self.assertEqual(item["message_count"], 2)
        self.assertEqual(item["unprocessed_count"], 2)

    def test_state_partition(self):
        self.seed_message()
        for state, expected in (("open", 1), ("closed", 0), ("all", 1)):
            with self.subTest(state=state):
                body = self.client.get(
                    "/v1/admin/sessions", params={"state": state}, headers=self.auth
                ).json()
                self.assertEqual(body["total"], expected)

    def test_session_messages_and_404(self):
        self.seed_message()
        body = self.client.get(
            "/v1/admin/sessions/s-1/messages", headers=self.auth
        ).json()
        self.assertKeys(body, {"session", "items", "total", "limit", "offset"})
        self.assertKeys(body["items"][0], {"indexed_raw", "memory_ids"},
                        where="message item: ")
        self.assertEqual(
            self.client.get(
                "/v1/admin/sessions/nope/messages", headers=self.auth
            ).status_code,
            404,
        )

    def test_message_detail_and_404(self):
        mid = self.seed_message()
        body = self.client.get(f"/v1/admin/messages/{mid}", headers=self.auth).json()
        self.assertIn("memory_ids", body)
        self.assertEqual(
            self.client.get("/v1/admin/messages/9999", headers=self.auth).status_code,
            404,
        )


class TestReextract(ApiTestCase):
    def test_use_batch_is_refused_not_ignored(self):
        """Silently ignoring it would report a discount that never applied."""
        r = self.client.post(
            "/v1/admin/reextract", json={"use_batch": True}, headers=self.auth
        )
        self.assertEqual(r.status_code, 422, r.text)
        self.assertIn("use_batch", r.text)

    def test_unknown_prompt_version_is_refused_before_any_call(self):
        with patch.object(judge, "extract", _boom):
            r = self.client.post(
                "/v1/admin/reextract",
                json={"prompt_version": "v99"}, headers=self.auth,
            )
        self.assertEqual(r.status_code, 422, r.text)
        self.assertIn("v99", r.text)

    def test_every_registry_version_is_accepted(self):
        with patch.object(judge, "extract", _boom):
            for version in sorted(prompts.REGISTRY):
                with self.subTest(version=version):
                    r = self.client.post(
                        "/v1/admin/reextract",
                        json={"prompt_version": version, "dry_run": True},
                        headers=self.auth,
                    )
                    self.assertEqual(r.status_code, 200, r.text)

    def test_dry_run_makes_no_model_call(self):
        self.seed_message()
        with patch.object(judge, "extract", _boom), \
             patch.object(reextractor, "run", _boom):
            r = self.client.post(
                "/v1/admin/reextract", json={"dry_run": True}, headers=self.auth
            )
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertKeys(body, PLAN_KEYS | {"dry_run", "prompt_version", "model"})
        self.assertIs(body["dry_run"], True)
        self.assertEqual(body["prompt_version"], prompts.DEFAULT_VERSION)


class TestConsolidate(ApiTestCase):
    def test_dry_run_makes_no_model_call(self):
        self.seed_memory()
        with patch.object(consolidator, "_merge_cluster", _boom):
            r = self.client.post(
                "/v1/admin/consolidate", json={"dry_run": True}, headers=self.auth
            )
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertKeys(body, {"dry_run", "threshold", "active_after", "took_ms",
                               "expired", "demoted", "clusters", "merged"})
        self.assertIs(body["dry_run"], True)

    def test_threshold_is_bounded(self):
        for value in (0.4, 1.1):
            with self.subTest(threshold=value):
                r = self.client.post(
                    "/v1/admin/consolidate",
                    json={"dry_run": True, "threshold": value},
                    headers=self.auth,
                )
                self.assertEqual(r.status_code, 422)

    def test_threshold_defaults_to_the_setting(self):
        r = self.client.post(
            "/v1/admin/consolidate", json={"dry_run": True}, headers=self.auth
        )
        self.assertEqual(r.json()["threshold"], 0.92)


class TestAsyncReindex(ApiTestCase):
    def test_start_returns_202_and_refuses_a_second(self):
        with patch.object(admin, "_run_reindex", lambda *a, **k: None):
            r = self.client.post("/v1/admin/reindex/start", headers=self.auth)
            self.assertEqual(r.status_code, 202, r.text)
            again = self.client.post("/v1/admin/reindex/start", headers=self.auth)
            self.assertEqual(again.status_code, 409)

    def test_status_is_idle_on_a_fresh_app(self):
        body = self.client.get("/v1/admin/reindex/status", headers=self.auth).json()
        self.assertEqual(body["status"], "idle")


class TestReadOnlyEndpoints(ApiTestCase):
    """Thin wrappers over functions unit-tested elsewhere: smoke, plus one real
    assertion on search-preview, which is the cheapest place to pin the
    retrieval constants to a live response body."""

    CASES = [
        ("/v1/admin/activity", {"days"}),
        ("/v1/admin/costs", {"total_usd", "by_kind", "monthly_limit_usd"}),
        ("/v1/admin/costs/daily", {"items", "days"}),
        ("/v1/admin/facets", {"type", "status", "scope"}),
    ]

    def test_smoke(self):
        self.seed_memory()
        for path, keys in self.CASES:
            with self.subTest(path=path):
                r = self.client.get(path, headers=self.auth)
                self.assertEqual(r.status_code, 200, r.text)
                self.assertKeys(r.json(), keys, where=f"{path}: ")

    def test_search_preview_reports_the_live_scoring_constants(self):
        from memkit import retrieval

        body = self.client.post(
            "/v1/admin/search-preview", json={"query": "pnpm"}, headers=self.auth
        ).json()
        self.assertEqual(
            body["weights"],
            {
                "similarity": retrieval.W_SIMILARITY,
                "importance": retrieval.W_IMPORTANCE,
                "recency": retrieval.W_RECENCY,
                "scope": retrieval.W_SCOPE,
            },
        )
        self.assertEqual(
            {k: float(v) for k, v in body["tau"].items()},
            {k: float(v) for k, v in retrieval.TAU.items()},
        )
        self.assertEqual(body["dedup_cosine"], 0.90)

    def test_costs_respects_the_configured_ceiling(self):
        body = self.client.get("/v1/admin/costs", headers=self.auth).json()
        self.assertEqual(body["monthly_limit_usd"], 1.0)  # set by the harness


if __name__ == "__main__":
    unittest.main()
