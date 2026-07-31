"""The invariants the whole design rests on, each asserted end to end.

These are the "layer 1 — plumbing" tests named in the original testing strategy
(now `docs/08-testing.md`). They were specified, never written, and every one of
them guards a property that other documents state as fact:

    reindex roundtrip  — "SQLite is the source of truth, Qdrant is derived, and
                          Qdrant rebuilds from SQLite with one command"
    idempotent ingest  — "the same turn delivered twice leaves one message"
    soft delete        — "raw messages are never deleted; facts expire"
    scope isolation    — "a fact from another project must not be returned"

They are separate from the per-route tests in `test_api.py` because each spans
several endpoints: an invariant is exactly a claim no single route can prove.
"""

from __future__ import annotations

import unittest

from memkit import retrieval, store, vectors
from tests.fixtures import HashEmbedder, StubQdrant, make_db
from tests.httpharness import ApiTestCase


class TestReindexRoundtrip(ApiTestCase):
    """Qdrant must be reconstructible from SQLite, exactly.

    This is invariant #1 in `docs/README.md`, and it is what makes the embedding
    model and the extraction prompt safe to change: if a rebuild is lossy, every
    later decision is irreversible.
    """

    def test_counts_and_ids_survive_a_rebuild(self):
        ids = {
            self.seed_memory(text=f"Prefers tool number {i} for its own reasons")
            for i in range(5)
        }
        self.seed_message(content="I always use pnpm rather than npm, everywhere")
        before = set(self.qdrant.points)
        self.assertEqual(before, ids)

        body = self.client.post("/v1/admin/reindex", headers=self.auth).json()

        self.assertEqual(set(self.qdrant.points), ids, "point ids changed on rebuild")
        self.assertEqual(body["memories"], self.scalar(
            "SELECT COUNT(*) FROM memories WHERE status='active'"
        ))
        self.assertEqual(body["raw"], self.scalar(
            "SELECT COUNT(*) FROM messages WHERE role='user' AND length(content) >= 25"
        ))

    def test_rebuild_is_idempotent(self):
        self.seed_memory()
        first = self.client.post("/v1/admin/reindex", headers=self.auth).json()
        snapshot = dict(self.qdrant.points)
        second = self.client.post("/v1/admin/reindex", headers=self.auth).json()
        self.assertEqual(
            (first["memories"], first["raw"]), (second["memories"], second["raw"])
        )
        self.assertEqual(self.qdrant.points, snapshot)

    def test_a_rebuild_does_not_resurrect_expired_facts(self):
        """The failure this exists to prevent: a soft delete undone by a rebuild."""
        live = self.seed_memory(text="Currently prefers pnpm over npm")
        gone = self.seed_memory(text="Used to prefer yarn, back in 2019")
        self.client.delete(f"/v1/memories/{gone}", headers=self.auth)
        self.client.post("/v1/admin/reindex", headers=self.auth)
        self.assertEqual(set(self.qdrant.points), {live})
        self.assertEqual(
            self.scalar("SELECT COUNT(*) FROM memories"), 2,
            "the expired row itself must survive in SQLite",
        )

    def test_index_drift_is_zero_after_a_rebuild(self):
        for i in range(3):
            self.seed_memory(text=f"Distinct durable preference number {i}")
        self.client.post("/v1/admin/reindex", headers=self.auth)
        health = self.client.get("/v1/admin/stats", headers=self.auth).json()["health"]
        self.assertEqual(health["index_drift"], 0)
        self.assertEqual(health["raw_drift"], 0)


class TestIdempotentIngest(ApiTestCase):
    """The same turn, delivered twice, must leave one message.

    Hermes sends a turn through `sync_turn`, and the same content can arrive
    again via `on_session_end`. Without this the corpus double-counts and the
    judge pays twice to read the same window.
    """

    def test_same_external_id_is_stored_once(self):
        body = {
            "session_id": "s-1", "role": "user",
            "content": "I always set the side editor width to 880 pixels",
            "external_source": "hermes", "external_id": "fixed-1",
        }
        ids = [
            self.client.post("/v1/messages", json=body, headers=self.auth).json()
            for _ in range(3)
        ]
        self.assertEqual({r["message_id"] for r in ids}, {ids[0]["message_id"]})
        self.assertEqual([r["deduplicated"] for r in ids], [False, True, True])
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM messages"), 1)

    def test_identity_is_scoped_to_its_source(self):
        """Two importers may legitimately use the same id namespace."""
        base = {"session_id": "s-1", "role": "user",
                "content": "I live in Tashkent, Uzbekistan", "external_id": "1"}
        a = self.client.post(
            "/v1/messages", json={**base, "external_source": "hermes"},
            headers=self.auth,
        ).json()
        b = self.client.post(
            "/v1/messages", json={**base, "external_source": "claude-code"},
            headers=self.auth,
        ).json()
        self.assertNotEqual(a["message_id"], b["message_id"])
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM messages"), 2)

    def test_no_external_id_means_no_deduplication(self):
        """Identical chat turns are legitimate; only declared identity dedups."""
        for _ in range(2):
            self.seed_message(content="I always use pnpm rather than npm here")
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM messages"), 2)

    def test_a_duplicate_delivery_is_not_re_indexed(self):
        body = {
            "session_id": "s-1", "role": "user",
            "content": "I prefer modal editors with tabs over separate pages",
            "external_source": "hermes", "external_id": "fixed-2",
        }
        self.client.post("/v1/messages", json=body, headers=self.auth)
        self.assertEqual(len(self.qdrant.raw_points), 1)
        self.client.post("/v1/messages", json=body, headers=self.auth)
        self.assertEqual(len(self.qdrant.raw_points), 1)


class TestSoftDelete(ApiTestCase):
    """Deleting a fact hides it from search and keeps the evidence."""

    def test_deleted_fact_leaves_sqlite_intact_and_the_index_clean(self):
        mem_id = self.seed_memory()
        self.client.delete(f"/v1/memories/{mem_id}", headers=self.auth)

        self.assertNotIn(mem_id, self.qdrant.points)
        row = self.sql("SELECT status, text FROM memories WHERE id=?", mem_id)
        self.assertEqual(len(row), 1, "the row must not be deleted")
        self.assertEqual(row[0]["status"], "expired")

    def test_deleted_fact_is_absent_from_the_default_listing(self):
        mem_id = self.seed_memory()
        self.client.delete(f"/v1/memories/{mem_id}", headers=self.auth)
        active = self.client.get("/v1/memories", headers=self.auth).json()
        self.assertEqual(active["total"], 0)
        expired = self.client.get(
            "/v1/memories", params={"status": "expired"}, headers=self.auth
        ).json()
        self.assertEqual(expired["total"], 1)

    def test_deletion_is_reversible(self):
        mem_id = self.seed_memory()
        self.client.delete(f"/v1/memories/{mem_id}", headers=self.auth)
        self.client.post(
            "/v1/admin/memories/bulk",
            json={"ids": [mem_id], "op": "restore"}, headers=self.auth,
        )
        self.assertEqual(
            self.scalar("SELECT status FROM memories WHERE id=?", mem_id), "active"
        )
        self.assertIn(mem_id, self.qdrant.points)

    def test_raw_messages_are_never_deleted_by_a_fact_deletion(self):
        """Invariant #2: the corpus is what makes re-extraction possible."""
        self.seed_message()
        mem_id = self.seed_memory()
        self.client.delete(
            f"/v1/memories/{mem_id}", params={"hard": "true"}, headers=self.auth
        )
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM messages"), 1)

    def test_hard_delete_clears_both_foreign_keys(self):
        task = self.client.post(
            "/v1/admin/tasks", json={"text": "A task with board metadata"},
            headers=self.auth,
        ).json()["task"]
        mid = self.seed_message()
        self.db.execute(
            "INSERT INTO memory_sources (memory_id, message_id) VALUES (?, ?)",
            (task["id"], mid),
        )
        self.db.commit()

        self.client.delete(
            f"/v1/memories/{task['id']}", params={"hard": "true"}, headers=self.auth
        )
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM task_board"), 0)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM memory_sources"), 0)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM messages"), 1)


class TestScopeIsolation(unittest.TestCase):
    """A fact belonging to another project must not be returned. Ever.

    Asserted against `retrieval.rank`, not over HTTP, because the harness's
    `StubQdrant.query_points` returns nothing -- reimplementing Qdrant's
    `min_should` filter in a stub would be a second, wrong copy of the read
    path. What the read path does with a foreign fact *after* Qdrant is the part
    worth pinning here, and it is a discard, not a demotion: a down-weighted
    foreign fact still surfaces once the corpus is thin.
    """

    def test_foreign_project_fact_is_discarded_not_demoted(self):
        self.assertIsNone(
            retrieval.scope_boost("project", "other-repo", project="memkit", task=None)
        )
        self.assertEqual(
            retrieval.scope_boost("project", "memkit", project="memkit", task=None),
            0.5,
        )

    def test_a_project_fact_with_no_key_is_unreachable(self):
        """Emitting one is a bug; serving it to every project would be worse."""
        self.assertIsNone(
            retrieval.scope_boost("project", None, project="memkit", task=None)
        )

    def test_user_facts_cross_every_boundary(self):
        for project in (None, "memkit", "some-other-repo"):
            with self.subTest(project=project):
                self.assertEqual(
                    retrieval.scope_boost("user", None, project=project, task=None),
                    0.0,
                )

    def test_unkeyed_task_facts_stay_visible_without_a_current_task(self):
        self.assertEqual(
            retrieval.scope_boost("task", None, project="memkit", task=None), 1.0
        )

    def test_foreign_task_fact_is_discarded(self):
        self.assertIsNone(
            retrieval.scope_boost("task", "other-task", project=None, task="mine")
        )

    def test_the_qdrant_filter_requires_a_scope_clause(self):
        """The discard above is belt; this is braces, applied server-side."""
        flt = retrieval.scope_filter(owner_id="u-test", project="memkit", task=None)
        self.assertIsNotNone(flt.min_should, "should-clauses must be mandatory")
        rendered = str(flt)
        self.assertIn("memkit", rendered)
        self.assertIn("u-test", rendered)
        self.assertIn("active", rendered)

    def test_ranking_drops_foreign_facts_before_they_can_be_returned(self):
        class Hit:
            def __init__(self, id, text, scope, scope_key):
                self.id = id
                self.score = 0.9
                self.vector = None
                self.payload = {
                    "text": text, "type": "project", "scope": scope,
                    "scope_key": scope_key, "importance": 0.9,
                    "updated_at": "2026-07-01T00:00:00Z",
                }

        ranked = retrieval.rank(
            [
                Hit("mine", "Auth lives in src/auth", "project", "memkit"),
                Hit("theirs", "Auth lives in app/auth", "project", "other-repo"),
            ],
            project="memkit",
            task=None,
        )
        self.assertEqual([r.id for r in ranked], ["mine"])


class TestStoreLevelIsolation(unittest.TestCase):
    """Scope isolation at the write/read boundary, with real vector maths.

    Uses `HashEmbedder` so two facts are genuinely distinct -- with the constant
    vector of `StubEmbedder` every pair has cosine 1.0 and dedup would collapse
    the result set to one item, hiding the very thing under test.
    """

    def setUp(self):
        self.conn = make_db()
        self.q = StubQdrant()
        self.emb = HashEmbedder()

    def test_distinct_texts_get_distinct_vectors(self):
        a = self.emb.encode_one("Prefers pnpm over npm")
        b = self.emb.encode_one("Prefers pytest over unittest")
        cosine = sum(x * y for x, y in zip(a, b))
        self.assertLess(abs(cosine), 0.5, "hash vectors must not be near-parallel")
        self.assertAlmostEqual(sum(x * x for x in a) ** 0.5, 1.0, places=6)

    def test_a_project_scoped_write_carries_its_key_into_the_payload(self):
        mem_id = store.add_memory(
            self.conn, self.q, self.emb, owner_id="u-test",
            text="The auth module lives in src/auth", type="project",
            scope="project", scope_key="memkit",
        )
        payload = self.q._store[vectors.MEMORIES][mem_id]
        self.assertEqual(payload["scope"], "project")
        self.assertEqual(payload["scope_key"], "memkit")

    def test_a_user_scoped_write_never_carries_a_key(self):
        """`scope='user'` with a key would be reachable from one project only."""
        mem_id = store.add_memory(
            self.conn, self.q, self.emb, owner_id="u-test",
            text="Prefers pnpm over npm", type="preference",
            scope="user", scope_key="memkit",
        )
        self.assertIsNone(
            self.conn.execute(
                "SELECT scope_key FROM memories WHERE id=?", (mem_id,)
            ).fetchone()["scope_key"]
        )


if __name__ == "__main__":
    unittest.main()
