"""The operational surface: policies, profiles, transcripts, jobs, admin.

These are the routes nobody exercises by hand until something is wrong, which
is exactly when a drifted contract is most expensive. The original version of
this file asserted all of it inside one long test; the claims are the same,
split so a failure names the thing that broke.
"""

from __future__ import annotations

import unittest

from tests.httpharness import ApiTestCase


class TestPolicies(ApiTestCase):
    def test_a_policy_is_stored_under_the_scope_it_was_written_for(self) -> None:
        """Retrieval and retention behaviour is data, not deployment config."""
        created = self.client.post(
            "/v1/policies",
            headers=self.auth,
            json={
                "kind": "retention",
                "name": "contact-retention",
                "version": 1,
                "config": {"days": 365},
                "scope": "team",
            },
        )
        self.assertEqual(created.status_code, 201, created.text)
        scoped = self.client.get("/v1/policies?kind=retention&scope=team", headers=self.auth)
        self.assertEqual(scoped.status_code, 200, scoped.text)
        self.assertIn("contact-retention", [item["name"] for item in scoped.json()["items"]])
        # Without the scope only the instance-wide rows answer, so a team rule
        # cannot be mistaken for a default that applies everywhere.
        instance_wide = self.client.get("/v1/policies?kind=retention", headers=self.auth)
        self.assertNotIn(
            "contact-retention", [item["name"] for item in instance_wide.json()["items"]]
        )

    def test_only_an_administrator_may_write_a_policy(self) -> None:
        """A policy decides what everyone retrieves, so it is not self-service."""
        refused = self.client.post(
            "/v1/policies",
            headers=self.as_bob,
            json={"kind": "retention", "name": "bob-rule", "version": 1, "config": {}},
        )
        self.assertEqual(refused.status_code, 403, refused.text)


class TestProfileRendering(ApiTestCase):
    def test_a_saved_preference_reaches_the_injected_profile(self) -> None:
        """The profile is the only memory most sessions ever see."""
        memory_id = self.seed_memory(text="Prefers concise answers")
        profile = self.client.post("/v1/profiles/render", headers=self.auth, json={})
        self.assertEqual(profile.status_code, 200, profile.text)
        body = profile.json()
        self.assertKeys(body, {"blocks", "used_tokens", "budget_tokens", "policy_id"})
        self.assertEqual([item["id"] for item in body["blocks"]["style"]], [memory_id])


class TestTranscripts(ApiTestCase):
    def test_an_event_is_readable_back_as_a_session_and_its_messages(self) -> None:
        """Raw evidence is what every extracted fact is checked against."""
        event = self.client.post(
            "/v1/evidence/events",
            headers=self.auth,
            json={
                "session_id": "ops-session",
                "agent_id": "chat",
                "role": "user",
                "content": "This operational event is long enough for durable storage.",
            },
        )
        self.assertEqual(event.status_code, 201, event.text)

        sessions = self.client.get("/v1/admin/sessions", headers=self.auth)
        self.assertEqual(sessions.status_code, 200, sessions.text)
        self.assertEqual([item["id"] for item in sessions.json()["items"]], ["ops-session"])

        messages = self.client.get("/v1/admin/sessions/ops-session/messages", headers=self.auth)
        self.assertEqual(messages.status_code, 200, messages.text)
        self.assertEqual(messages.json()["total"], 1)
        self.assertEqual(messages.json()["session"]["agent_id"], "chat")

    def test_a_batch_of_events_is_stored_as_one_unit(self) -> None:
        """A hook flushes a whole turn; a partial flush would cite half of it."""
        batch = self.client.post(
            "/v1/evidence/events:batch",
            headers=self.auth,
            json={
                "events": [
                    {
                        "session_id": "batch-session",
                        "role": "user",
                        "content": f"A durable batched event number {index}",
                    }
                    for index in range(3)
                ]
            },
        )
        self.assertEqual(batch.status_code, 201, batch.text)
        self.assertEqual(batch.json()["count"], 3)
        self.assertEqual(
            self.scalar("SELECT COUNT(*) FROM messages WHERE session_id=%s", "batch-session"), 3
        )


class TestJobs(ApiTestCase):
    def test_an_export_is_a_job_the_caller_can_watch_and_cancel(self) -> None:
        """Export runs on the worker, so the response is a handle, not a file."""
        queued = self.client.post("/v1/export", headers=self.auth)
        self.assertEqual(queued.status_code, 202, queued.text)
        job_id = queued.json()["job_id"]

        job = self.client.get(f"/v1/jobs/{job_id}", headers=self.auth)
        self.assertEqual(job.status_code, 200, job.text)
        self.assertEqual(job.json()["status"], "queued")
        self.assertEqual([event["status"] for event in job.json()["events"]], ["queued"])

        self.assertIn(
            job_id,
            [item["id"] for item in self.client.get("/v1/jobs", headers=self.auth).json()["items"]],
        )

        cancelled = self.client.post(f"/v1/jobs/{job_id}/cancel", headers=self.auth)
        self.assertEqual(cancelled.status_code, 202, cancelled.text)
        self.assertTrue(self.scalar("SELECT cancel_requested FROM jobs WHERE id=%s", job_id))

    def test_another_users_job_does_not_exist_for_a_member(self) -> None:
        """A job id is a guessable handle, so the answer is 404, not 403."""
        job_id = self.client.post("/v1/export", headers=self.auth).json()["job_id"]
        self.assertEqual(
            self.client.get(f"/v1/jobs/{job_id}", headers=self.as_bob).status_code, 404
        )
        self.assertEqual(
            self.client.post(f"/v1/jobs/{job_id}/cancel", headers=self.as_bob).status_code, 404
        )

    def test_a_malformed_job_id_is_not_found_rather_than_a_crash(self) -> None:
        self.assertEqual(self.client.get("/v1/jobs/not-a-uuid", headers=self.auth).status_code, 404)


class TestMaintenanceRoutes(ApiTestCase):
    def test_every_maintenance_route_queues_rather_than_blocking(self) -> None:
        """None of these may run in the request: each is minutes of work."""
        for path, body in (
            ("/v1/admin/reindex", None),
            ("/v1/admin/consolidate", {"dry_run": True}),
            ("/v1/admin/reextract", {}),
        ):
            response = self.client.post(path, headers=self.auth, json=body)
            self.assertEqual(response.status_code, 202, f"{path}: {response.text}")
            self.assertEqual(response.json()["status"], "queued")

    def test_the_administrative_read_routes_answer(self) -> None:
        for path in ("/v1/admin/judge-runs", "/v1/admin/health", "/v1/admin/metrics"):
            self.assertEqual(self.client.get(path, headers=self.auth).status_code, 200, path)

    def test_metrics_report_the_index_parity_an_operator_watches(self) -> None:
        """A store and an index that disagree is the failure worth catching."""
        self.seed_memory(text="Prefers concise answers")
        metrics = self.client.get("/v1/admin/metrics", headers=self.auth).json()
        self.assertKeys(metrics, {"outbox_pending", "index_parity", "pending_review"})
        self.assertEqual(metrics["index_parity"]["database_active"], 1)
        self.assertEqual(metrics["outbox_pending"], 0)


if __name__ == "__main__":
    unittest.main()
