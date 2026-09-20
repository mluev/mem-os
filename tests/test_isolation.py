"""One person's memory must never reach another. This is that suite.

Everything else in this project is a convenience; this is the property the
whole port exists to establish, and it is the one a passing single-user suite
could never see. Two rules run through all of it:

* A scope named **explicitly** in a request the caller does not hold is a 403.
  Filtering it away would make "you may not read this" indistinguishable from
  "there is nothing here", and neither a user nor a test could tell a
  permissions bug from an empty result.
* Another user's row addressed **by id** is a 404, never a 403. A 403 confirms
  the row exists, which turns every endpoint that takes an id into an oracle
  for the existence of other people's facts.

A scope that does not exist at all is a 404 as well, so probing for scope names
learns nothing that probing for random ids would not.
"""

from __future__ import annotations

import hashlib
import unittest

from tests.httpharness import ApiTestCase

UNKNOWN_SCOPE = "no-such-scope-anywhere"


class IsolationTestCase(ApiTestCase):
    def scope_id(self, who: str) -> str:
        return self.scalar(
            "SELECT id::text FROM entities WHERE user_id=%s",
            self.team.alice_id if who == "alice" else self.team.bob_id,
        )

    def memory_as(self, headers: dict[str, str], *, text: str, **body) -> str:
        response = self.client.post(
            "/v1/memories",
            headers=headers,
            json={"text": text, "kind": "preference", "source_role": "manual", **body},
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["id"]


class PrivateMemoryByIdTest(IsolationTestCase):
    def test_shared_fact_does_not_publish_its_private_source(self) -> None:
        text = "Private discussion behind the shared decision"
        mid = self.seed_message(content=text)
        memory_id = self.seed_memory(text="Shared decision", scope=self.team.team_id)
        self.db.execute(
            """INSERT INTO memory_evidence
               (memory_id,message_id,start_char,end_char,excerpt_sha256)
               VALUES (%s,%s,0,%s,%s)""",
            (memory_id, mid, len(text), hashlib.sha256(text.encode()).hexdigest()),
        )
        self.db.execute(
            "INSERT INTO memory_sources(memory_id,message_id) VALUES (%s,%s)", (memory_id, mid)
        )
        own = self.client.get(f"/v1/memories/{memory_id}/sources", headers=self.auth)
        other = self.client.get(f"/v1/memories/{memory_id}/sources", headers=self.as_bob)
        self.assertTrue(own.json()["evidence"][0]["verified"])
        self.assertEqual(other.status_code, 200, other.text)
        self.assertEqual(other.json()["evidence"], [])
        detail = self.client.get(f"/v1/memories/{memory_id}", headers=self.as_bob).json()
        self.assertEqual(detail["memory"]["sessions"], [])

    def test_sharing_current_wording_does_not_publish_private_revisions_or_links(self) -> None:
        memory_id = self.seed_memory(text="PRIVATE ORIGINAL WORDING")
        moved = self.client.patch(
            f"/v1/memories/{memory_id}",
            headers=self.auth,
            json={
                "expected_revision": 1,
                "text": "Shared wording",
                "scope": self.team.team_id,
                "move_scope": True,
            },
        )
        self.assertEqual(moved.status_code, 200, moved.text)
        private_before = self.seed_memory(text="PRIVATE PREDECESSOR")
        private_after = self.seed_memory(text="PRIVATE SUCCESSOR")
        self.db.execute(
            "UPDATE memories SET superseded_by=%s WHERE id=%s", (memory_id, private_before)
        )
        self.db.execute(
            "UPDATE memories SET superseded_by=%s WHERE id=%s", (private_after, memory_id)
        )
        own = self.client.get(f"/v1/memories/{memory_id}/history", headers=self.auth)
        other = self.client.get(f"/v1/memories/{memory_id}/history", headers=self.as_bob)
        self.assertIn("PRIVATE", own.text)
        self.assertEqual(other.status_code, 200, other.text)
        self.assertNotIn("PRIVATE", other.text)
        self.assertEqual(other.json()["predecessors"], [])
        self.assertIsNone(other.json()["successor"])
        queue = self.client.get("/v1/review?kind=memory", headers=self.as_bob)
        self.assertEqual(queue.status_code, 200, queue.text)
        self.assertNotIn("PRIVATE", queue.text)

    def test_every_route_that_takes_an_id_hides_a_teammates_private_memory(self) -> None:
        """404 on all of them, including the read-only ones.

        `history` and `sources` are the two that look harmless and are not:
        they return the previous wording of a fact and the verbatim transcript
        it was drawn from, which is more revealing than the memory itself.
        """
        memory_id = self.seed_memory(text="Alice is interviewing at another company")

        for method, path in (
            ("GET", f"/v1/memories/{memory_id}"),
            ("GET", f"/v1/memories/{memory_id}/history"),
            ("GET", f"/v1/memories/{memory_id}/sources"),
            ("DELETE", f"/v1/memories/{memory_id}"),
        ):
            response = self.client.request(method, path, headers=self.as_bob)
            self.assertEqual(response.status_code, 404, f"{method} {path}: {response.text}")

        patched = self.client.patch(
            f"/v1/memories/{memory_id}",
            headers=self.as_bob,
            json={"expected_revision": 1, "text": "rewritten by a stranger"},
        )
        self.assertEqual(patched.status_code, 404, patched.text)

        reviewed = self.client.post(
            f"/v1/memories/{memory_id}/review", headers=self.as_bob, json={"decision": "decline"}
        )
        self.assertEqual(reviewed.status_code, 404, reviewed.text)

        restored = self.client.post(f"/v1/memories/{memory_id}/restore", headers=self.as_bob)
        self.assertEqual(restored.status_code, 404, restored.text)

        self.assertEqual(
            self.scalar("SELECT text FROM memories WHERE id=%s", memory_id),
            "Alice is interviewing at another company",
        )


class NamedScopeTest(IsolationTestCase):
    def test_naming_a_teammates_scope_in_a_write_is_forbidden(self) -> None:
        """Not silently redirected to the caller's own scope, which is worse."""
        refused = self.client.post(
            "/v1/memories",
            headers=self.as_bob,
            json={
                "text": "planted in someone else's space",
                "kind": "fact",
                "source_role": "manual",
                "scope": self.scope_id("alice"),
            },
        )
        self.assertEqual(refused.status_code, 403, refused.text)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM memories"), 0)

    def test_naming_a_teammates_scope_in_a_search_is_forbidden(self) -> None:
        """An empty result would read as "Alice has nothing", which is a leak."""
        self.seed_memory(text="Alice prefers pnpm over npm")
        refused = self.client.post(
            "/v1/memories/search",
            headers=self.as_bob,
            json={"query": "pnpm", "scopes": [self.scope_id("alice")]},
        )
        self.assertEqual(refused.status_code, 403, refused.text)

    def test_naming_a_teammates_scope_in_a_listing_is_forbidden(self) -> None:
        refused = self.client.get(
            f"/v1/memories?scope={self.scope_id('alice')}", headers=self.as_bob
        )
        self.assertEqual(refused.status_code, 403, refused.text)

    def test_a_scope_that_does_not_exist_is_not_found(self) -> None:
        """Distinct from 403, so the two answers cannot be used to enumerate scopes.

        A caller learns only "this name resolves to nothing" -- the same thing
        an unauthenticated stranger could learn by guessing.
        """
        written = self.client.post(
            "/v1/memories",
            headers=self.as_bob,
            json={
                "text": "somewhere unknown",
                "kind": "fact",
                "source_role": "manual",
                "scope": UNKNOWN_SCOPE,
            },
        )
        self.assertEqual(written.status_code, 404, written.text)
        searched = self.client.post(
            "/v1/memories/search",
            headers=self.as_bob,
            json={"query": "anything", "scopes": [UNKNOWN_SCOPE]},
        )
        self.assertEqual(searched.status_code, 404, searched.text)


class DefaultVisibilityTest(IsolationTestCase):
    def test_the_unqualified_views_are_disjoint_between_two_users(self) -> None:
        """The default answer, with no scope named, is the one that matters most.

        A hook and a dashboard both call these with nothing but a credential,
        so an over-broad default would leak on every single request rather than
        only when somebody went looking.
        """
        alice_id = self.memory_as(self.auth, text="Alice prefers pnpm over npm")
        bob_id = self.memory_as(self.as_bob, text="Bob prefers yarn over npm")

        alice_listed = self.client.get("/v1/memories", headers=self.auth).json()
        bob_listed = self.client.get("/v1/memories", headers=self.as_bob).json()
        self.assertEqual([item["id"] for item in alice_listed["items"]], [alice_id])
        self.assertEqual([item["id"] for item in bob_listed["items"]], [bob_id])
        self.assertEqual(alice_listed["total"], 1)

        alice_found = self.client.post(
            "/v1/memories/search", headers=self.auth, json={"query": "npm"}
        ).json()
        bob_found = self.client.post(
            "/v1/memories/search", headers=self.as_bob, json={"query": "npm"}
        ).json()
        self.assertEqual([item["id"] for item in alice_found["memories"]], [alice_id])
        self.assertEqual([item["id"] for item in bob_found["memories"]], [bob_id])

        self.assertEqual(self.profile_ids(self.auth), {alice_id})
        self.assertEqual(self.profile_ids(self.as_bob), {bob_id})

    def profile_ids(self, headers: dict[str, str]) -> set[str]:
        response = self.client.post("/v1/profiles/render", headers=headers, json={})
        self.assertEqual(response.status_code, 200, response.text)
        return {item["id"] for block in response.json()["blocks"].values() for item in block}

    def test_the_team_scope_is_shared_and_reports_who_wrote_each_fact(self) -> None:
        """A shared scope is only useful if attribution survives the sharing.

        "The team decided" and "Bob decided" are different claims, so the
        author travels with the memory rather than being inferred from who is
        reading it.
        """
        shared_id = self.memory_as(self.as_bob, text="We always squash-merge", scope="team")

        listed = self.client.get("/v1/memories?scope=team", headers=self.auth)
        self.assertEqual(listed.status_code, 200, listed.text)
        items = listed.json()["items"]
        self.assertEqual([item["id"] for item in items], [shared_id])
        self.assertEqual(items[0]["author"], "bob")
        self.assertEqual(items[0]["scope_slug"], "test-team")

        read = self.client.get(f"/v1/memories/{shared_id}", headers=self.auth)
        self.assertEqual(read.status_code, 200, read.text)
        self.assertEqual(read.json()["memory"]["author"], "bob")


class ProjectRoleTest(IsolationTestCase):
    def demote_bob_to_viewer(self) -> None:
        response = self.client.put(
            f"/v1/entities/mem-os/members/{self.team.bob_id}",
            headers=self.auth,
            json={"role": "viewer"},
        )
        self.assertEqual(response.status_code, 200, response.text)

    def test_a_viewer_reads_the_project_but_cannot_write_to_it(self) -> None:
        """Read and write are separate sets, not one membership flag.

        A contractor or a stakeholder needs the project's decisions without
        being able to add to the record everyone else relies on.
        """
        shared_id = self.memory_as(
            self.auth, text="Mem OS stores memories in Postgres", scope="mem-os"
        )
        self.demote_bob_to_viewer()

        entity = self.client.get("/v1/entities/mem-os", headers=self.as_bob)
        self.assertEqual(entity.status_code, 200, entity.text)
        self.assertFalse(entity.json()["writable"])

        listed = self.client.get("/v1/memories?scope=mem-os", headers=self.as_bob)
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual([item["id"] for item in listed.json()["items"]], [shared_id])

        written = self.client.post(
            "/v1/memories",
            headers=self.as_bob,
            json={
                "text": "a viewer should not be able to say this",
                "kind": "fact",
                "source_role": "manual",
                "scope": "mem-os",
            },
        )
        self.assertEqual(written.status_code, 403, written.text)

        patched = self.client.patch(
            f"/v1/memories/{shared_id}",
            headers=self.as_bob,
            json={"expected_revision": 1, "text": "a viewer should not rewrite this"},
        )
        self.assertEqual(patched.status_code, 403, patched.text)


class SessionOwnershipTest(IsolationTestCase):
    def test_a_teammate_cannot_write_into_or_close_someone_elses_session(self) -> None:
        """A session fixes its user on creation and never moves.

        Accepting the event would attach a stranger's words to Alice's
        transcript, and every fact later extracted from that window would be
        recorded as hers.

        Both routes answer 404 rather than naming the reason: a distinct answer
        for a session that exists would let anyone enumerate other people's
        conversation ids.
        """
        self.seed_message(session_id="alice-session", content="Alice says something durable here")

        intruded = self.client.post(
            "/v1/evidence/events",
            headers=self.as_bob,
            json={
                "session_id": "alice-session",
                "role": "user",
                "content": "an event that does not belong to this transcript",
            },
        )
        self.assertEqual(intruded.status_code, 404, intruded.text)
        self.assertEqual(
            self.scalar("SELECT COUNT(*) FROM messages WHERE session_id=%s", "alice-session"), 1
        )

        closed = self.client.post("/v1/sessions/alice-session/close", headers=self.as_bob)
        self.assertEqual(closed.status_code, 404, closed.text)
        self.assertIsNone(self.scalar("SELECT ended_at FROM sessions WHERE id=%s", "alice-session"))

    def test_a_teammates_transcript_is_not_readable(self) -> None:
        self.seed_message(session_id="alice-session", content="Alice says something durable here")
        for path in (
            "/v1/admin/sessions/alice-session/messages",
            "/v1/admin/sessions/alice-session/memories",
        ):
            self.assertEqual(self.client.get(path, headers=self.as_bob).status_code, 404, path)
        self.assertEqual(
            self.client.get("/v1/admin/sessions", headers=self.as_bob).json()["items"], []
        )


class CredentialTest(IsolationTestCase):
    def test_a_revoked_key_stops_working_immediately(self) -> None:
        """Revocation is checked on every request, not cached with the key."""
        minted = self.client.post("/v1/api-keys", headers=self.as_bob, json={"name": "laptop"})
        self.assertEqual(minted.status_code, 201, minted.text)
        header = {"X-API-Key": minted.json()["secret"]}
        self.assertEqual(self.client.get("/v1/auth/me", headers=header).status_code, 200)

        revoked = self.client.delete(f"/v1/api-keys/{minted.json()['id']}", headers=self.as_bob)
        self.assertEqual(revoked.status_code, 200, revoked.text)
        self.assertEqual(self.client.get("/v1/auth/me", headers=header).status_code, 401)

    def test_a_disabled_users_key_stops_working_without_being_revoked(self) -> None:
        """Offboarding is one action, not one action per credential.

        Users are disabled rather than deleted, because their memories cite
        their messages and carry them as author -- so the check has to live in
        the key lookup itself.
        """
        self.assertEqual(self.client.get("/v1/auth/me", headers=self.as_bob).status_code, 200)
        disabled = self.client.patch(
            f"/v1/users/{self.team.bob_id}", headers=self.auth, json={"disabled": True}
        )
        self.assertEqual(disabled.status_code, 200, disabled.text)
        self.assertEqual(self.client.get("/v1/auth/me", headers=self.as_bob).status_code, 401)

    def test_a_member_cannot_revoke_a_teammates_key(self) -> None:
        minted = self.client.post("/v1/api-keys", headers=self.auth, json={"name": "alice-laptop"})
        self.assertEqual(
            self.client.delete(
                f"/v1/api-keys/{minted.json()['id']}", headers=self.as_bob
            ).status_code,
            404,
        )


class AdminRouteTest(IsolationTestCase):
    def test_a_member_cannot_reach_an_administrative_route(self) -> None:
        """403 rather than 404 here: the route's existence is not a secret.

        These are instance-wide operations, not somebody's data, so telling a
        member that the route exists and they may not use it is the honest
        answer and the one that makes a misconfiguration diagnosable.
        """
        created = self.client.post(
            "/v1/users",
            headers=self.as_bob,
            json={
                "handle": "carol",
                "display_name": "Carol",
                "password": "a-long-enough-test-password",
            },
        )
        self.assertEqual(created.status_code, 403, created.text)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM users WHERE handle='carol'"), 0)

        self.assertEqual(
            self.client.post("/v1/admin/reindex", headers=self.as_bob).status_code, 403
        )
        self.assertEqual(self.client.get("/v1/admin/health", headers=self.as_bob).status_code, 403)

    def test_an_administrator_can_reach_the_same_routes(self) -> None:
        """The refusal has to be about the role, not a broken dependency."""
        self.assertEqual(self.client.post("/v1/admin/reindex", headers=self.auth).status_code, 202)
        self.assertEqual(self.client.get("/v1/admin/health", headers=self.auth).status_code, 200)


if __name__ == "__main__":
    unittest.main()
