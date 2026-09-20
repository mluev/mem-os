"""The promises the HTTP surface makes to an agent that has to act on them.

Each case here stands for a way the contract was broken once: a filter typo
that returned a 500, a correction that could not be attempted because nothing
handed back a revision, a caller that could name whose memory it was writing,
a secret that reached the message table, and a source span that kept being
served verbatim after the message under it had changed.
"""

from __future__ import annotations

import hashlib
import unittest

from memkit.db import transaction
from tests.httpharness import ApiTestCase

UNKNOWN_ID = "00000000-0000-0000-0000-000000000000"


class TestMemoryContract(ApiTestCase):
    def test_an_unknown_filter_operator_is_a_client_error(self) -> None:
        """A malformed filter is the caller's mistake and must say so."""
        response = self.client.post(
            "/v1/memories/search",
            headers=self.auth,
            json={"query": "anything", "filter": {"field": "kind", "op": "bogus"}},
        )
        self.assertEqual(response.status_code, 422, response.text)

    def test_a_correction_can_be_driven_from_a_read_or_a_search(self) -> None:
        """An agent needs the current revision before it can PATCH.

        Both routes to it are contract: reading one memory, and finding it by
        search. Without either, `expected_revision` is unobtainable and every
        correction fails the precondition it was meant to protect.
        """
        memory_id = self.seed_memory(text="Prefers npm over pnpm", kind="preference")

        read = self.client.get(f"/v1/memories/{memory_id}", headers=self.auth)
        self.assertEqual(read.status_code, 200, read.text)
        self.assertEqual(read.json()["memory"]["id"], memory_id)
        self.assertEqual(read.json()["memory"]["revision"], 1)
        self.assertIsInstance(read.json()["memory"]["context"], dict)

        found = self.client.post("/v1/memories/search", headers=self.auth, json={"query": "npm"})
        self.assertEqual(found.status_code, 200, found.text)
        hit = next(m for m in found.json()["memories"] if m["id"] == memory_id)
        self.assertEqual(hit["revision"], 1)

        corrected = self.client.patch(
            f"/v1/memories/{memory_id}",
            headers=self.auth,
            json={"expected_revision": hit["revision"], "text": "Prefers pnpm over npm"},
        )
        self.assertEqual(corrected.status_code, 200, corrected.text)
        self.assertEqual(corrected.json()["revision"], 2)

        stale = self.client.patch(
            f"/v1/memories/{memory_id}",
            headers=self.auth,
            json={"expected_revision": 1, "text": "something else"},
        )
        self.assertEqual(stale.status_code, 409, stale.text)

        self.assertEqual(
            self.client.get(f"/v1/memories/{UNKNOWN_ID}", headers=self.auth).status_code, 404
        )

    def test_a_caller_cannot_choose_whose_memory_it_writes(self) -> None:
        """Ownership follows the credential, never a field in the body.

        The service this replaced took an `owner_id` from the request. Naming
        one now is a rejected field, and the memory lands in the caller's own
        scope, which is the only place an unqualified write may go.
        """
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
        self.assertEqual(rejected.status_code, 422, rejected.text)

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
        hit = found.json()["memories"][0]
        self.assertEqual(hit["text"], "Prefers pnpm")
        self.assertEqual(hit["scope_slug"], "alice-ivanova")

    def test_evidence_is_redacted_and_session_identity_is_immutable(self) -> None:
        """A secret must not reach the message table, and a session cannot move.

        Both halves protect the same row. Redaction is applied before the
        insert, not on the way out, so a leaked transcript is a leaked
        transcript of scrubbed text. Re-pointing an existing session at another
        agent would silently re-attribute every fact extracted from it.
        """
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
        stored = self.scalar("SELECT content FROM messages WHERE id=%s", first.json()["message_id"])
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
        self.assertEqual(mismatch.status_code, 422, mismatch.text)

    def test_include_sources_returns_hash_verified_spans_only(self) -> None:
        """A cited span is verbatim or it is withheld.

        The excerpt hash is written so that this moment can be checked. Once
        the message under a span changes, returning the new slice would present
        altered text as if it were the evidence the claim was drawn from.
        """
        message_id = self.seed_message(content="I always use pnpm, never npm, on every project")
        memory_id = self.seed_memory(text="Prefers pnpm over npm on every project")
        span = "I always use pnpm"
        digest = hashlib.sha256(span.encode()).hexdigest()
        with transaction(self.db):
            self.db.execute(
                "INSERT INTO memory_sources(memory_id,message_id) VALUES (%s,%s)",
                (memory_id, message_id),
            )
            self.db.execute(
                """INSERT INTO memory_evidence
                   (memory_id,message_id,start_char,end_char,excerpt_sha256)
                   VALUES (%s,%s,0,%s,%s)""",
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
                    "revision": None,
                    "evidence_status": "legacy_unversioned",
                }
            ],
        )

        with transaction(self.db):
            self.db.execute(
                "UPDATE messages SET content=%s WHERE id=%s",
                ("tampered content that no longer matches", message_id),
            )
        tampered = self.client.post(
            "/v1/memories/search",
            headers=self.auth,
            json={"query": "pnpm", "include_sources": True},
        )
        self.assertEqual(tampered.json()["memories"][0]["sources"], [])


class TestRetiredSurface(ApiTestCase):
    def test_the_records_platform_and_the_task_board_are_gone(self) -> None:
        """Deleted routes must 404, not linger behind an unreachable handler.

        The records platform and the task board were removed with their tests.
        A stale mount would still answer, and nothing else in the suite would
        notice, so their absence is asserted here rather than assumed.
        """
        for method, path in (
            ("POST", "/v1/namespaces"),
            ("GET", "/v1/namespaces"),
            ("POST", "/v1/collections/life/items/records"),
            ("GET", "/v1/admin/task-board"),
            ("POST", "/v1/admin/replay"),
        ):
            response = self.client.request(method, path, headers=self.auth, json={})
            self.assertEqual(response.status_code, 404, f"{method} {path}: {response.text}")


if __name__ == "__main__":
    unittest.main()
