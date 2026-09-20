"""The release journey works on a fresh database and after a populated v1 upgrade."""

import os

from qdrant_client import QdrantClient

from memkit import api, db, job_runner, vectors
from tests.httpharness import ApiTestCase


class ReleaseJourneyTest(ApiTestCase):
    def journey(self, *, upgrade):
        index = QdrantClient(":memory:")
        self.addCleanup(index.close)
        vectors.ensure_collections(index)
        api.app.state.qdrant = index
        evidence_id = self.seed_message(content="I prefer pnpm except in the legacy npm project.")
        memory_id = self.seed_memory(text="I prefer pnpm except in the legacy npm project.")
        if upgrade:
            # These rows use unchanged v1 columns; remove only additive v2 objects
            # to exercise startup migration with already-populated history/evidence.
            self.db.execute("DROP TABLE memory_revision_evidence")
            self.db.execute("ALTER TABLE jobs DROP COLUMN available_at")
            self.db.execute("DELETE FROM schema_migrations WHERE version=2")
            db.init_db(os.environ["MEMKIT_DATABASE_URL"])

        response = self.client.post(
            "/v1/memories/search",
            headers=self.auth,
            json={"query": "pnpm", "include_raw": True},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn(memory_id, [item["id"] for item in response.json()["memories"]])
        self.assertIn(evidence_id, [item["message_id"] for item in response.json()["raw"]])
        correction = self.client.patch(
            f"/v1/memories/{memory_id}",
            headers=self.auth,
            json={"expected_revision": 1, "text": "I now prefer npm across all projects."},
        )
        self.assertEqual(correction.status_code, 200, correction.text)
        review = self.client.post(
            f"/v1/memories/{memory_id}/review",
            headers=self.auth,
            json={"decision": "confirm", "expected_revision": 2},
        )
        self.assertEqual(review.status_code, 200, review.text)
        archived = self.client.delete(f"/v1/memories/{memory_id}", headers=self.auth)
        self.assertEqual(archived.status_code, 200, archived.text)
        recalled = self.client.post("/v1/memories/search", headers=self.auth, json={"query": "npm"})
        self.assertNotIn(memory_id, [item["id"] for item in recalled.json()["memories"]])
        restored = self.client.post(f"/v1/memories/{memory_id}/restore", headers=self.auth)
        self.assertEqual(restored.status_code, 200, restored.text)
        history = self.client.get(f"/v1/memories/{memory_id}/history", headers=self.auth).json()
        self.assertEqual(len(history["revisions"]), 5)
        self.assertEqual(history["revisions"][0]["text"], "I now prefer npm across all projects.")
        self.assertEqual(
            self.client.get(f"/v1/memories/{memory_id}", headers=self.as_bob).status_code, 404
        )
        exported = self.client.post("/v1/export", headers=self.auth)
        self.assertEqual(exported.status_code, 202, exported.text)
        job_id = exported.json()["job_id"]
        job_runner.run(api.app, job_id)
        job = self.client.get(f"/v1/jobs/{job_id}", headers=self.auth).json()
        self.assertEqual(job["status"], "complete", job)
        download = self.client.get(f"/v1/jobs/{job_id}/download", headers=self.auth)
        self.assertEqual(download.status_code, 200, download.text)
        payload = download.json()
        self.assertIn(memory_id, [str(row["id"]) for row in payload["memories"]])
        self.assertEqual(len(payload["memory_revisions"]), 5)
        self.assertEqual(
            self.client.get(f"/v1/jobs/{job_id}/download", headers=self.as_bob).status_code, 404
        )

    def test_fresh_capture_recall_correct_review_archive_restore_export(self):
        self.journey(upgrade=False)

    def test_populated_v1_upgrade_preserves_the_full_journey(self):
        self.journey(upgrade=True)
