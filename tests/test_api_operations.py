from __future__ import annotations

from tests.httpharness import ApiTestCase


class TestOperationalApi(ApiTestCase):
    def test_platform_jobs_profiles_and_admin_contracts(self) -> None:
        namespace = self.client.post(
            "/v1/namespaces",
            headers=self.auth,
            json={"name": "personal", "description": "Owned structured data"},
        )
        self.assertEqual(namespace.status_code, 201, namespace.text)
        self.assertEqual(
            self.client.get("/v1/namespaces", headers=self.auth).json()["items"][0]["name"],
            "personal",
        )

        collection = self.client.post(
            "/v1/namespaces/personal/collections",
            headers=self.auth,
            json={
                "name": "contacts",
                "schema": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                },
            },
        )
        self.assertEqual(collection.status_code, 201, collection.text)
        self.assertEqual(
            self.client.get("/v1/collections/personal/contacts", headers=self.auth).json()["name"],
            "contacts",
        )
        self.assertEqual(
            len(
                self.client.get("/v1/namespaces/personal/collections", headers=self.auth).json()[
                    "items"
                ]
            ),
            1,
        )

        record = self.client.post(
            "/v1/collections/personal/contacts/records",
            headers=self.auth,
            json={"value": {"name": "Ada"}, "metadata": {"source": "manual"}},
        )
        self.assertEqual(record.status_code, 201, record.text)
        record_id = record.json()["id"]
        updated = self.client.patch(
            f"/v1/collections/personal/contacts/records/{record_id}",
            headers=self.auth,
            json={"expected_revision": 1, "value": {"name": "Ada Lovelace"}},
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        searched = self.client.post(
            "/v1/collections/personal/contacts/search",
            headers=self.auth,
            json={"filter": {"field": "value.name", "op": "eq", "value": "Ada Lovelace"}},
        )
        self.assertEqual([item["id"] for item in searched.json()["items"]], [record_id])
        history_path = f"/v1/collections/personal/contacts/records/{record_id}/history"
        self.assertEqual(
            [
                item["revision"]
                for item in self.client.get(history_path, headers=self.auth).json()["items"]
            ],
            [2, 1],
        )

        link = self.client.post(
            "/v1/namespaces/personal/links",
            headers=self.auth,
            json={"from_ref": record_id, "relation": "knows", "to_ref": "contact:grace"},
        )
        self.assertEqual(link.status_code, 201, link.text)
        self.assertEqual(
            self.client.get("/v1/namespaces/personal/links", headers=self.auth).json()["items"][0][
                "relation"
            ],
            "knows",
        )

        policy = self.client.post(
            "/v1/policies",
            headers=self.auth,
            json={
                "namespace": "personal",
                "kind": "retention",
                "name": "contact-retention",
                "version": 1,
                "config": {"days": 365},
            },
        )
        self.assertEqual(policy.status_code, 201, policy.text)
        self.assertTrue(
            self.client.get("/v1/policies?namespace=personal", headers=self.auth).json()["items"]
        )

        memory_id = self.seed_memory(text="Prefers concise answers")
        profile = self.client.post("/v1/profiles/render", headers=self.auth, json={})
        self.assertEqual(profile.status_code, 200, profile.text)
        self.assertEqual(profile.json()["stable"][0]["id"], memory_id)

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
        self.assertTrue(self.client.get("/v1/admin/sessions", headers=self.auth).json()["items"])
        self.assertEqual(
            self.client.get("/v1/admin/sessions/ops-session/messages", headers=self.auth).json()[
                "total"
            ],
            1,
        )

        queued = self.client.post("/v1/export", headers=self.auth)
        self.assertEqual(queued.status_code, 202, queued.text)
        job_id = queued.json()["job_id"]
        self.assertEqual(
            self.client.get(f"/v1/jobs/{job_id}", headers=self.auth).json()["status"], "queued"
        )
        self.assertTrue(self.client.get("/v1/jobs", headers=self.auth).json()["items"])
        cancelled = self.client.post(f"/v1/jobs/{job_id}/cancel", headers=self.auth)
        self.assertEqual(cancelled.status_code, 202, cancelled.text)

        for path, body in (
            ("/v1/admin/reindex", None),
            ("/v1/admin/consolidate", {"dry_run": True}),
            ("/v1/admin/reextract", {"apply": False}),
        ):
            response = self.client.post(path, headers=self.auth, json=body)
            self.assertEqual(response.status_code, 202, response.text)

        self.assertEqual(
            self.client.get("/v1/admin/judge-runs", headers=self.auth).status_code, 200
        )
        self.assertEqual(self.client.get("/v1/admin/health", headers=self.auth).status_code, 200)
        self.assertEqual(self.client.get("/v1/admin/metrics", headers=self.auth).status_code, 200)

        deleted = self.client.delete(
            f"/v1/collections/personal/contacts/records/{record_id}?expected_revision=2",
            headers=self.auth,
        )
        self.assertEqual(deleted.status_code, 200, deleted.text)
