"""Session identity cannot preserve a permission that has been revoked."""

from memkit import entities
from tests.fixtures import add_messages
from tests.httpharness import ApiTestCase
from tests.test_extraction_pipeline import PipelineCase, _add, _result


class SessionCaptureAuthorizationTest(ApiTestCase):
    def event(self, **extra):
        return self.client.post(
            "/v1/evidence/events",
            headers=self.as_bob,
            json={
                "session_id": "project-session",
                "agent_id": "chat",
                "role": "user",
                "content": "A project statement with enough content",
                **extra,
            },
        )

    def start_project_session(self):
        response = self.event(scope=self.team.project_id)
        self.assertEqual(response.status_code, 201, response.text)

    def test_omitted_scope_keeps_authorized_existing_session(self):
        self.start_project_session()
        response = self.event()
        self.assertEqual(response.status_code, 201, response.text)
        row = self.db.execute("SELECT scope_id FROM sessions WHERE id='project-session'").fetchone()
        self.assertEqual(str(row["scope_id"]), self.team.project_id)

    def test_explicit_scope_cannot_be_silently_replaced_by_existing_session_scope(self):
        self.start_project_session()
        response = self.event(scope="private")
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(self.scalar("SELECT count(*) FROM messages"), 1)

    def test_revoked_member_cannot_capture_through_existing_session(self):
        self.start_project_session()
        entities.remove_member(self.db, entity_id=self.team.project_id, user_id=self.team.bob_id)
        for extra in ({}, {"scope": "private"}):
            response = self.event(**extra)
            self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(self.scalar("SELECT count(*) FROM messages"), 1)

    def test_revoked_member_cannot_close_existing_session(self):
        self.start_project_session()
        entities.remove_member(self.db, entity_id=self.team.project_id, user_id=self.team.bob_id)
        response = self.client.post("/v1/sessions/project-session/close", headers=self.as_bob)
        self.assertEqual(response.status_code, 403, response.text)
        self.assertIsNone(self.scalar("SELECT ended_at FROM sessions WHERE id='project-session'"))


class SessionExtractionAuthorizationTest(PipelineCase):
    def project_window(self):
        self.conn.execute("UPDATE sessions SET scope_id=%s WHERE id='s-1'", (self.team.project_id,))
        return add_messages(self.conn, n=10, content="I always use pnpm, never npm")

    def test_revoked_scope_is_refused_before_provider_egress(self):
        self.project_window()
        entities.remove_member(
            self.conn, entity_id=self.team.project_id, user_id=self.team.alice_id
        )
        outcome = self.run_extraction(
            lambda **_: self.fail("provider must not be called"), force=True
        )
        self.assertEqual(outcome.error, "scope_not_allowed")
        self.assertEqual(self.unprocessed(), 10)

    def test_membership_revoked_during_provider_call_cannot_apply(self):
        ids = self.project_window()

        def provider(**_):
            entities.remove_member(
                self.conn, entity_id=self.team.project_id, user_id=self.team.alice_id
            )
            return _result([_add("Prefers pnpm", message_id=ids[0], quote="I always use pnpm")])

        outcome = self.run_extraction(provider, force=True)
        self.assertEqual(outcome.error, "scope_not_allowed")
        self.assertEqual(self.conn.execute("SELECT count(*) AS n FROM memories").fetchone()["n"], 0)
        self.assertEqual(self.unprocessed(), 10)
        self.assertEqual(
            self.conn.execute(
                "SELECT count(*) AS n FROM messages WHERE claim_token IS NOT NULL"
            ).fetchone()["n"],
            0,
        )
