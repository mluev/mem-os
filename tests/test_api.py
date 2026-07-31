"""HTTP contract tests for the routes defined in api.py.

Each test pins a claim the documentation makes. Where a doc and the code
disagreed, the code was checked first and the doc is what changed -- with one
exception noted in `test_post_message_returns_201`.

See tests/httpharness.py for what is stubbed (Qdrant, the embedder) and what is
not (everything else, including SQLite).
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from memkit import api, extract, judge
from tests.httpharness import (
    ApiTestCase,
    guarded_operations,
    open_operations,
    sample_path,
)

HEALTHZ_KEYS = {
    "ok", "qdrant", "embedder", "embedder_device", "memories", "raw", "db",
    "queue_depth", "index_dirty", "reindex",
}
SEARCH_KEYS = {"memories", "raw", "used_tokens", "took_ms"}
SOURCES_KEYS = {
    "memory", "task_board", "messages", "judge_run", "judge_ops",
    "superseded_by", "supersedes",
}
LIST_KEYS = {"memories", "count", "total", "limit", "offset", "sort", "order"}


class TestAuth(ApiTestCase):
    """The API key, asserted over every route the schema says is guarded.

    Mounting a router without `dependencies=[Depends(require_key)]` is one line
    away at all times, and would expose the whole admin surface silently. This
    reads the route list from the OpenAPI schema, so a new route is covered the
    moment it exists -- there is no list here to forget to update.
    """

    def test_every_guarded_route_rejects_a_missing_key(self):
        ops = guarded_operations()
        self.assertGreaterEqual(len(ops), 29, "route inventory shrank unexpectedly")
        for method, path in ops:
            with self.subTest(route=f"{method} {path}"):
                r = self.client.request(method, sample_path(path), json={})
                self.assertEqual(r.status_code, 401, r.text)

    def test_every_guarded_route_rejects_a_wrong_key(self):
        for method, path in guarded_operations():
            with self.subTest(route=f"{method} {path}"):
                r = self.client.request(
                    method, sample_path(path), json={},
                    headers={"X-API-Key": "not-the-key"},
                )
                self.assertEqual(r.status_code, 401, r.text)

    def test_healthz_is_the_only_unauthenticated_route(self):
        self.assertEqual(open_operations(), [("GET", "/healthz")])
        self.assertEqual(self.client.get("/healthz").status_code, 200)

    def test_error_body_does_not_echo_the_submitted_key(self):
        r = self.client.get("/v1/memories", headers={"X-API-Key": "hunter2-secret"})
        self.assertEqual(r.status_code, 401)
        self.assertNotIn("hunter2", r.text)


class TestMutationLock(ApiTestCase):
    """`docs/03-api.md`: while a reindex runs, mutations answer 409.

    The promise exists because reindex drops and refills the collections; a
    memory written in that window used to get no point and no error. Nothing
    tested it.
    """

    ROUTES = [
        ("POST", "/v1/memories", {"text": "x", "type": "fact"}),
        ("PATCH", "/v1/memories/{id}", {"text": "y"}),
        ("DELETE", "/v1/memories/{id}", None),
        ("POST", "/v1/memories/{id}/supersede", {"by": "other"}),
        ("POST", "/v1/admin/memories/bulk", {"ids": ["{id}"], "op": "expire"}),
        ("POST", "/v1/admin/reextract", {"dry_run": True}),
        ("POST", "/v1/admin/consolidate", {"dry_run": True}),
    ]

    def test_mutations_are_refused_during_reindex(self):
        mem_id = self.seed_memory()
        self.set_reindex_running()
        for method, path, body in self.ROUTES:
            with self.subTest(route=f"{method} {path}"):
                url = path.replace("{id}", mem_id)
                payload = body
                if isinstance(payload, dict):
                    payload = {
                        k: ([mem_id] if v == ["{id}"] else v)
                        for k, v in payload.items()
                    }
                r = self.client.request(
                    method, url, json=payload, headers=self.auth
                )
                self.assertEqual(r.status_code, 409, r.text)

    def test_reads_still_work_during_reindex(self):
        """A rebuild must not take the read path down with it."""
        self.seed_memory()
        self.set_reindex_running()
        for method, url in [
            ("GET", "/v1/memories"),
            ("GET", "/healthz"),
            ("POST", "/v1/search"),
        ]:
            with self.subTest(route=f"{method} {url}"):
                r = self.client.request(
                    method, url, json={"query": "pnpm"}, headers=self.auth
                )
                self.assertEqual(r.status_code, 200, r.text)


class TestHealthz(ApiTestCase):
    def test_shape(self):
        body = self.client.get("/healthz").json()
        self.assertKeys(body, HEALTHZ_KEYS)
        self.assertTrue(body["ok"])
        self.assertEqual(body["reindex"], {"status": "idle"})
        self.assertIs(body["index_dirty"], False)

    def test_queue_depth_is_the_unprocessed_backlog(self):
        """There is no queue. `queue_depth` counts messages with processed = 0."""
        self.assertEqual(self.client.get("/healthz").json()["queue_depth"], 0)
        self.seed_message()
        self.seed_message(content="Second unrelated durable statement here")
        depth = self.client.get("/healthz").json()["queue_depth"]
        self.assertEqual(depth, self.scalar(
            "SELECT COUNT(*) FROM messages WHERE processed = 0"
        ))
        self.assertEqual(depth, 2)


class TestPostMessage(ApiTestCase):
    def test_post_message_returns_201(self):
        """201, not the 202 the pre-reconciliation docs claimed.

        The message is written synchronously before the response, so 201 Created
        is correct and the doc was wrong. Extraction is what happens later, and
        that is reported by `extraction_queued`, not by the status code.
        """
        r = self.client.post(
            "/v1/messages",
            json={"session_id": "s-1", "role": "user", "content": "hello world"},
            headers=self.auth,
        )
        self.assertEqual(r.status_code, 201, r.text)
        self.assertKeys(r.json(), {"message_id", "extraction_queued", "deduplicated"})

    def test_no_judge_credential_means_nothing_is_queued(self):
        r = self.client.post(
            "/v1/messages",
            json={"session_id": "s-1", "role": "user",
                  "content": "remember that I always use pnpm"},
            headers=self.auth,
        )
        self.assertIs(r.json()["extraction_queued"], False)

    def test_external_id_makes_delivery_idempotent(self):
        """Hermes sends the same turn through three paths; only one may land."""
        body = {
            "session_id": "s-1", "role": "user", "content": "I live in Tashkent",
            "external_source": "hermes", "external_id": "fixed-1",
        }
        first = self.client.post("/v1/messages", json=body, headers=self.auth).json()
        second = self.client.post("/v1/messages", json=body, headers=self.auth).json()
        self.assertEqual(first["message_id"], second["message_id"])
        self.assertIs(first["deduplicated"], False)
        self.assertIs(second["deduplicated"], True)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM messages"), 1)

    def test_role_vocabulary_is_enforced(self):
        r = self.client.post(
            "/v1/messages",
            json={"session_id": "s-1", "role": "tool", "content": "x"},
            headers=self.auth,
        )
        self.assertEqual(r.status_code, 422)

    def test_extraction_is_scheduled_when_the_gate_opens(self):
        """The gate, not the judge: assert the hand-off, never make a call."""
        calls = []
        with patch.object(api, "judge_configured", return_value=True), \
             patch.object(api, "_extract_now", side_effect=lambda *a: calls.append(a)):
            self.client.post(
                "/v1/messages",
                json={"session_id": "s-9", "role": "user",
                      "content": "запомни: я всегда ставлю ширину 880 пикселей"},
                headers=self.auth,
            )
        self.assertEqual(len(calls), 1, "explicit 'remember' must open the gate")
        self.assertEqual(calls[0], ("s-9", self.scalar(
            "SELECT owner_id FROM sessions WHERE id='s-9'"), "chat", True))

    def test_raw_indexing_respects_the_length_floor(self):
        """Short turns are stored but never indexed."""
        self.seed_message(content="ok")
        self.assertEqual(len(self.qdrant.raw_points), 0)
        self.seed_message(content="I prefer pnpm over npm on all of my projects")
        self.assertEqual(len(self.qdrant.raw_points), 1)

    def test_assistant_turns_are_stored_but_never_indexed(self):
        self.seed_message(
            role="assistant",
            content="You should consider using Pinia instead of Vuex for this",
        )
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM messages"), 1)
        self.assertEqual(len(self.qdrant.raw_points), 0)


class TestCloseSession(ApiTestCase):
    def test_unknown_session_is_404(self):
        r = self.client.post("/v1/sessions/nope/close", headers=self.auth)
        self.assertEqual(r.status_code, 404)

    def test_close_without_a_judge_reports_the_missing_credential(self):
        self.seed_message()
        r = self.client.post("/v1/sessions/s-1/close", headers=self.auth)
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["extracted"], 0)
        self.assertIn("no judge configured", body["error"])
        self.assertIsNotNone(
            self.scalar("SELECT ended_at FROM sessions WHERE id='s-1'"),
            "the session must still be closed when no judge is configured",
        )

    def test_close_drains_the_tail_and_never_calls_the_judge_twice(self):
        self.seed_message()
        outcome = extract.ExtractionOutcome()
        with patch.object(api, "judge_configured", return_value=True), \
             patch.object(extract, "run_extraction", return_value=outcome) as run:
            r = self.client.post("/v1/sessions/s-1/close", headers=self.auth)
        self.assertEqual(r.status_code, 200, r.text)
        # judge_run_id None + nothing fast-forwarded or abandoned == drained.
        self.assertEqual(run.call_count, 1)


class TestPostMemory(ApiTestCase):
    def test_created(self):
        r = self.client.post(
            "/v1/memories",
            json={"text": "Lives in Tashkent", "type": "fact"},
            headers=self.auth,
        )
        self.assertEqual(r.status_code, 201, r.text)
        self.assertIn("id", r.json())

    def test_manual_write_is_indexed_and_active(self):
        mem_id = self.seed_memory()
        self.assertIn(mem_id, self.qdrant.points)
        self.assertEqual(
            self.scalar("SELECT status FROM memories WHERE id=?", mem_id), "active"
        )
        self.assertEqual(
            self.scalar("SELECT extraction_version FROM memories WHERE id=?", mem_id),
            "manual",
        )

    def test_type_vocabulary_is_enforced(self):
        r = self.client.post(
            "/v1/memories",
            json={"text": "x", "type": "vibe"},
            headers=self.auth,
        )
        self.assertEqual(r.status_code, 422)

    def test_importance_is_bounded(self):
        for value in (1.5, -0.1):
            with self.subTest(importance=value):
                r = self.client.post(
                    "/v1/memories",
                    json={"text": "x", "type": "fact", "importance": value},
                    headers=self.auth,
                )
                self.assertEqual(r.status_code, 422)


class TestListMemories(ApiTestCase):
    def test_envelope(self):
        self.seed_memory()
        body = self.client.get("/v1/memories", headers=self.auth).json()
        self.assertKeys(body, LIST_KEYS)
        self.assertEqual(body["total"], 1)
        self.assertEqual(body["sort"], "updated_at")
        self.assertEqual(body["order"], "desc")

    def test_sort_is_an_allowlist_not_interpolation(self):
        r = self.client.get(
            "/v1/memories",
            params={"sort": "updated_at; DROP TABLE memories"},
            headers=self.auth,
        )
        self.assertEqual(r.status_code, 422)
        # The table is still there, which is the actual assertion.
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM memories"), 0)

    def test_query_parameter_bounds(self):
        for params in ({"order": "sideways"}, {"limit": 0}, {"limit": 501},
                       {"min_importance": 2}):
            with self.subTest(params=params):
                r = self.client.get("/v1/memories", params=params, headers=self.auth)
                self.assertEqual(r.status_code, 422)

    def test_cyrillic_search_is_case_insensitive_over_http(self):
        """SQLite's lower() is ASCII-only; db.py registers a unicode `lowerx`."""
        self.seed_memory(text="Предпочитает pnpm вместо npm", type="preference")
        body = self.client.get(
            "/v1/memories", params={"q": "ПРЕДПОЧИТАЕТ"}, headers=self.auth
        ).json()
        self.assertEqual(body["total"], 1)


class TestSearch(ApiTestCase):
    def test_envelope_on_an_empty_index(self):
        body = self.client.post(
            "/v1/search", json={"query": "pnpm"}, headers=self.auth
        ).json()
        self.assertKeys(body, SEARCH_KEYS)
        self.assertEqual(body["memories"], [])
        self.assertEqual(body["used_tokens"], 0)

    def test_empty_results_do_not_touch_retrieval_counters(self):
        mem_id = self.seed_memory()
        self.client.post("/v1/search", json={"query": "pnpm"}, headers=self.auth)
        self.assertEqual(
            self.scalar("SELECT retrieval_count FROM memories WHERE id=?", mem_id), 0
        )
        self.assertIsNone(
            self.scalar("SELECT last_retrieved_at FROM memories WHERE id=?", mem_id)
        )

    def test_request_bounds(self):
        for body in ({"query": "x", "budget_tokens": 99999},
                     {"query": "x", "limit": 201},
                     {"query": "x", "scopes": ["galaxy"]},
                     {"query": "x", "types": ["vibe"]}):
            with self.subTest(body=body):
                r = self.client.post("/v1/search", json=body, headers=self.auth)
                self.assertEqual(r.status_code, 422)


class TestMemorySources(ApiTestCase):
    def test_unknown_memory_is_404(self):
        r = self.client.get("/v1/memories/nope/sources", headers=self.auth)
        self.assertEqual(r.status_code, 404)

    def test_shape(self):
        mem_id = self.seed_memory()
        body = self.client.get(
            f"/v1/memories/{mem_id}/sources", headers=self.auth
        ).json()
        self.assertKeys(body, SOURCES_KEYS)
        self.assertEqual(body["memory"]["id"], mem_id)
        self.assertEqual(body["messages"], [])
        self.assertIsNone(body["judge_run"])


class TestAdminReindex(ApiTestCase):
    def test_rebuild_reports_counts_and_clears_the_dirty_flag(self):
        self.seed_memory()
        self.seed_message()
        api.app.state.index_dirty = True
        r = self.client.post("/v1/admin/reindex", headers=self.auth)
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertKeys(body, {"memories", "raw", "took_ms"})
        self.assertEqual(body["memories"], 1)
        self.assertEqual(body["raw"], 1)
        self.assertIs(api.app.state.index_dirty, False)
        self.assertEqual(api.app.state.reindex_job["status"], "complete")

    def test_reindex_loads_active_rows_only(self):
        """Reloading everything would resurrect every soft-deleted fact."""
        keep = self.seed_memory(text="Prefers pnpm over npm everywhere")
        drop = self.seed_memory(text="Used to prefer yarn back in 2019")
        self.client.delete(f"/v1/memories/{drop}", headers=self.auth)
        body = self.client.post("/v1/admin/reindex", headers=self.auth).json()
        self.assertEqual(body["memories"], 1)
        self.assertIn(keep, self.qdrant.points)
        self.assertNotIn(drop, self.qdrant.points)

    def test_concurrent_reindex_is_refused(self):
        self.set_reindex_running()
        r = self.client.post("/v1/admin/reindex", headers=self.auth)
        self.assertEqual(r.status_code, 409)


class TestSchema(unittest.TestCase):
    """Assertions on the generated schema, which need no client."""

    def test_openapi_builds(self):
        """A broken response_model shows up here and nowhere else."""
        spec = api.app.openapi()
        self.assertEqual(spec["info"]["title"], "memkit")
        self.assertGreaterEqual(len(spec["paths"]), 25)

    def test_the_key_is_declared_as_a_header_scheme(self):
        schemes = api.app.openapi()["components"]["securitySchemes"]
        self.assertEqual(
            schemes["APIKeyHeader"],
            {"type": "apiKey", "in": "header", "name": "X-API-Key"},
        )

    def test_judge_configured_follows_the_model_provider(self):
        """A Gemini key must not satisfy a Claude model, or vice versa.

        Note the alias names below. The credential fields declare a
        `validation_alias`, so `Settings(gemini_api_key="k")` is silently
        discarded and the real `.env` value is used instead -- which is how the
        first version of this test passed for the wrong reason.
        """
        from memkit.config import Settings

        blank = dict.fromkeys(
            ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY",
             "GOOGLE_VERTEX_API_KEY", "VERTEX_PROJECT", "GOOGLE_CLOUD_PROJECT"), ""
        )
        gemini_key = {**blank, "GEMINI_API_KEY": "k"}
        claude_key = {**blank, "ANTHROPIC_API_KEY": "k"}

        self.assertEqual(judge.provider_of("gemini-3.5-flash-lite"), "gemini")
        self.assertEqual(judge.provider_of("claude-haiku-4-5"), "anthropic")

        self.assertTrue(api.judge_configured(
            Settings(judge_model="gemini-3.5-flash-lite", **gemini_key)))
        self.assertFalse(api.judge_configured(
            Settings(judge_model="claude-haiku-4-5", **gemini_key)))
        self.assertTrue(api.judge_configured(
            Settings(judge_model="claude-haiku-4-5", **claude_key)))
        self.assertFalse(api.judge_configured(
            Settings(judge_model="gemini-3.5-flash-lite", **claude_key)))
        # Vertex project alone is enough for Gemini: the Developer API key and
        # ADC-via-project are two supported paths, not one.
        self.assertTrue(api.judge_configured(Settings(
            judge_model="gemini-3.5-flash-lite",
            **{**blank, "VERTEX_PROJECT": "some-gcp-project"})))


if __name__ == "__main__":
    unittest.main()
