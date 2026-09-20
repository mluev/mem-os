"""Operational statistics cannot disclose another member's private activity."""

from psycopg.types.json import Jsonb

from memkit import jobs
from tests.httpharness import ApiTestCase


class MetricsIsolationTest(ApiTestCase):
    def test_member_sees_only_own_spend_and_no_instance_diagnostics(self):
        for user_id, cost in ((self.team.alice_id, 9), (self.team.bob_id, 2)):
            self.db.execute(
                """INSERT INTO judge_runs(user_id,kind,model,prompt_version,input,error,cost_usd)
                   VALUES (%s,'extract','fake','test',%s,'test failure',%s)""",
                (user_id, Jsonb({}), cost),
            )
        response = self.client.get("/v1/admin/metrics", headers=self.as_bob)
        self.assertEqual(response.status_code, 200)
        row = response.json()
        self.assertEqual(row["month_spend_usd"], 2)
        self.assertEqual(row["provider_errors"], 1)
        for key in (
            "outbox_pending",
            "outbox_retries",
            "month_limit_usd",
            "backup_freshness_seconds",
        ):
            self.assertIsNone(row[key], key)
        self.assertIsNone(row["index_parity"]["qdrant_active"])
        admin = self.client.get("/v1/admin/metrics", headers=self.auth).json()
        self.assertEqual(admin["month_spend_usd"], 11)

    def test_detached_erasure_job_is_admin_only(self):
        job_id = jobs.create(self.db, kind="erase", input_data={"user_id": "erased"})
        self.assertEqual(
            self.client.get(f"/v1/jobs/{job_id}", headers=self.as_bob).status_code, 404
        )
        self.assertEqual(
            self.client.post(f"/v1/jobs/{job_id}/cancel", headers=self.as_bob).status_code, 404
        )
        items = self.client.get("/v1/jobs", headers=self.as_bob).json()["items"]
        self.assertNotIn(job_id, [item["id"] for item in items])
        self.assertEqual(self.client.get(f"/v1/jobs/{job_id}", headers=self.auth).status_code, 200)
