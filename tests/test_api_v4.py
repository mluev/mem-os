from __future__ import annotations

from tests.httpharness import ApiTestCase


class TestV4Contract(ApiTestCase):
    def test_invalid_memory_filter_is_a_client_error(self) -> None:
        response = self.client.post(
            "/v1/memories/search",
            headers=self.auth,
            json={"query": "anything", "filter": {"field": "kind", "op": "bogus"}},
        )
        self.assertEqual(response.status_code, 422, response.text)

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

    def test_include_sources_returns_hash_verified_spans_only(self) -> None:
        import hashlib

        message_id = self.seed_message(content="I always use pnpm, never npm, on every project")
        memory_id = self.seed_memory(text="Prefers pnpm over npm on every project")
        span = "I always use pnpm"
        digest = hashlib.sha256(span.encode()).hexdigest()
        from memkit.db import transaction

        with transaction(self.db):
            self.db.execute(
                "INSERT INTO memory_sources(memory_id,message_id) VALUES (?,?)",
                (memory_id, message_id),
            )
            self.db.execute(
                """INSERT INTO memory_evidence
                   (memory_id,message_id,start_char,end_char,excerpt_sha256)
                   VALUES (?,?,0,?,?)""",
                (memory_id, message_id, len(span), digest),
            )

        plain = self.client.post("/v1/memories/search", headers=self.auth, json={"query": "pnpm"})
        self.assertEqual(plain.status_code, 200, plain.text)
        self.assertNotIn("sources", plain.json()["memories"][0])

        sourced = self.client.post(
            "/v1/memories/search",
            headers=self.auth,
            json={"query": "pnpm", "include_sources": True},
        )
        self.assertEqual(sourced.status_code, 200, sourced.text)
        memory = sourced.json()["memories"][0]
        self.assertEqual(
            memory["sources"],
            [
                {
                    "message_id": message_id,
                    "excerpt": span,
                    "role": "user",
                    "created_at": memory["sources"][0]["created_at"],
                }
            ],
        )

        # Corrupt the retained message: the hash check must drop the span
        # rather than return altered text as if it were verbatim evidence.
        with transaction(self.db):
            self.db.execute(
                "UPDATE messages SET content=? WHERE id=?",
                ("tampered content that no longer matches", message_id),
            )
        tampered = self.client.post(
            "/v1/memories/search",
            headers=self.auth,
            json={"query": "pnpm", "include_sources": True},
        )
        self.assertEqual(tampered.json()["memories"][0]["sources"], [])


if __name__ == "__main__":
    import unittest

    unittest.main()
