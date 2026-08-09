from __future__ import annotations

from tests.httpharness import ApiTestCase


class TestV4Contract(ApiTestCase):
    def test_single_owner_strict_memory_contract(self) -> None:
        rejected = self.client.post(
            "/v1/memories",
            headers=self.auth,
            json={
                "owner_id": "someone-else",
                "text": "Prefers pnpm",
                "kind": "preference",
                "source_role": "user",
            },
        )
        self.assertEqual(rejected.status_code, 422)

        created = self.client.post(
            "/v1/memories",
            headers=self.auth,
            json={
                "text": "Prefers pnpm",
                "kind": "preference",
                "context": {"workspace": "mem-os"},
                "source_role": "user",
            },
        )
        self.assertEqual(created.status_code, 201, created.text)
        self.assertTrue(created.json()["stored"])
        self.assertTrue(created.json()["indexed"])

        found = self.client.post(
            "/v1/memories/search",
            headers=self.auth,
            json={
                "query": "pnpm",
                "filter": {"field": "context.workspace", "op": "eq", "value": "mem-os"},
            },
        )
        self.assertEqual(found.status_code, 200, found.text)
        self.assertEqual(found.json()["memories"][0]["text"], "Prefers pnpm")

    def test_evidence_is_redacted_and_session_identity_is_immutable(self) -> None:
        first = self.client.post(
            "/v1/evidence/events",
            headers=self.auth,
            json={
                "session_id": "s-redact",
                "agent_id": "chat",
                "role": "user",
                "content": "API_KEY=super-secret-value remember my preference",
            },
        )
        self.assertEqual(first.status_code, 201, first.text)
        self.assertTrue(first.json()["redacted"])
        stored = self.db.execute(
            "SELECT content FROM messages WHERE id=?", (first.json()["message_id"],)
        ).fetchone()[0]
        self.assertNotIn("super-secret-value", stored)

        mismatch = self.client.post(
            "/v1/evidence/events",
            headers=self.auth,
            json={
                "session_id": "s-redact",
                "agent_id": "other-agent",
                "role": "user",
                "content": "second message",
            },
        )
        self.assertEqual(mismatch.status_code, 422)

    def test_generic_collection_round_trip_and_task_routes_are_gone(self) -> None:
        namespace = self.client.post("/v1/namespaces", headers=self.auth, json={"name": "life"})
        self.assertEqual(namespace.status_code, 201, namespace.text)
        collection = self.client.post(
            "/v1/namespaces/life/collections",
            headers=self.auth,
            json={
                "name": "items",
                "schema": {
                    "type": "object",
                    "properties": {"title": {"type": "string"}},
                    "required": ["title"],
                    "additionalProperties": False,
                },
            },
        )
        self.assertEqual(collection.status_code, 201, collection.text)
        record = self.client.post(
            "/v1/collections/life/items/records",
            headers=self.auth,
            json={"value": {"title": "Opaque caller record"}},
        )
        self.assertEqual(record.status_code, 201, record.text)
        self.assertEqual(record.json()["revision"], 1)

        self.assertEqual(
            self.client.get("/v1/admin/task-board", headers=self.auth).status_code,
            404,
        )


if __name__ == "__main__":
    import unittest

    unittest.main()
