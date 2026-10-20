"""A secret must not survive a write, and must not leave the machine.

Two boundaries, one rule. Persistence is the first: whatever a caller sends is
scrubbed before it reaches a column, so a leaked dump or an exported archive
carries placeholders rather than credentials. Provider egress is the second and
is the one that actually costs money to get wrong -- a key pasted into a chat
would otherwise be sent to a third party and logged there.
"""

from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from memkit import judge, providers, security, store
from memkit.db import transaction
from memkit.limits import MIN_INDEX_CHARS
from tests.fixtures import make_db, seed_team

SECRET = "super-secret-token-value"


class SecretScrubbingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = make_db(seed=False)
        self.team = seed_team(self.conn)
        self.scope_id = self.team.scope_of("alice")

    def test_no_authoritative_write_retains_a_secret_in_any_column(self) -> None:
        """Text, context and tags all pass through redaction, not just text.

        The regression was a secret in a `context` value: the message body was
        scrubbed and the JSON blob beside it was not, so the credential was in
        the row anyway.
        """
        with transaction(self.conn):
            message_id, _, _ = store.add_message(
                self.conn,
                session_id="secure",
                user_id=self.team.alice_id,
                scope_id=self.scope_id,
                agent_id="chat",
                role="user",
                content=f"API_KEY={SECRET}",
                context={"authorization": f"Bearer {SECRET}"},
            )
            memory_id = store.add_memory(
                self.conn,
                scope_id=self.scope_id,
                author_id=self.team.alice_id,
                text=f"PASSWORD={SECRET}",
                kind="observation",
                context={"secret": SECRET},
                tags=[f"token={SECRET}"],
            )
        written = json.dumps(
            {
                "message": dict(
                    self.conn.execute(
                        "SELECT * FROM messages WHERE id=%s", (message_id,)
                    ).fetchone()
                ),
                "memory": dict(
                    self.conn.execute("SELECT * FROM memories WHERE id=%s", (memory_id,)).fetchone()
                ),
            },
            default=str,
        )
        self.assertNotIn(SECRET, written)

    def test_the_immutable_revision_is_scrubbed_as_well_as_the_row(self) -> None:
        """History is the copy nobody thinks to check, and it is append-only.

        A secret that reached `memory_revisions` could not be corrected later
        by editing the memory: the revision is deliberately never rewritten.
        """
        with transaction(self.conn):
            memory_id = store.add_memory(
                self.conn,
                scope_id=self.scope_id,
                author_id=self.team.alice_id,
                text=f"PASSWORD={SECRET}",
                kind="observation",
            )
        revisions = json.dumps(
            [
                dict(row)
                for row in self.conn.execute(
                    "SELECT * FROM memory_revisions WHERE memory_id=%s", (memory_id,)
                )
            ],
            default=str,
        )
        self.assertNotIn(SECRET, revisions)

    def test_the_provider_never_receives_a_secret_and_the_log_never_keeps_one(self) -> None:
        """The prompt is scrubbed after it is built, so nothing assembled into it leaks.

        Redacting the inputs one by one would miss whatever a future prompt
        template adds. The recorded run has to be clean for the same reason:
        `judge_runs.input` exists to be read by a human afterwards.
        """
        captured: list[str] = []

        def provider_stub(**kwargs):
            captured.append(kwargs["prompt"])
            return providers.ProviderResult(raw={"operations": []})

        with patch("memkit.providers.call", side_effect=provider_stub):
            result = judge.extract(
                self.conn,
                window=[{"id": 1, "role": "user", "content": f"API_KEY={SECRET}"}],
                candidates=[],
                monthly_limit_usd=1,
                model=judge.DEFAULT_MODEL,
                context={"authorization": f"Bearer {SECRET}"},
                user_id=self.team.alice_id,
            )

        self.assertIsNone(result.error)
        self.assertNotIn(SECRET, captured[0])
        stored_input = self.conn.execute(
            "SELECT input FROM judge_runs WHERE id=%s", (result.judge_run_id,)
        ).fetchone()["input"]
        self.assertNotIn(SECRET, json.dumps(stored_input, default=str))


class PrivateSpanTest(unittest.TestCase):
    """What a person wraps in <private> never reaches a column or a provider."""

    def setUp(self) -> None:
        self.conn = make_db(seed=False)
        self.team = seed_team(self.conn)
        self.scope_id = self.team.scope_of("alice")

    def add(self, content: str, role: str = "user") -> dict:
        with transaction(self.conn):
            message_id, _, _ = store.add_message(
                self.conn,
                session_id="private",
                user_id=self.team.alice_id,
                scope_id=self.scope_id,
                agent_id="chat",
                role=role,
                content=content,
            )
        return dict(
            self.conn.execute("SELECT * FROM messages WHERE id=%s", (message_id,)).fetchone()
        )

    def test_a_private_span_is_removed_whole_with_any_secret_inside(self) -> None:
        row = self.add(f"My plan <private>salary 90k, API_KEY={SECRET}</private> stays mine")
        self.assertEqual(row["content"], "My plan [PRIVATE] stays mine")
        self.assertTrue(row["redacted"])

    def test_a_private_span_never_reaches_the_judge(self) -> None:
        captured: list[str] = []

        def provider_stub(**kwargs):
            captured.append(kwargs["prompt"])
            return providers.ProviderResult(raw={"operations": []})

        with patch("memkit.providers.call", side_effect=provider_stub):
            judge.extract(
                self.conn,
                window=[{"id": 1, "role": "user", "content": "<private>divorce</private> ok"}],
                candidates=[],
                monthly_limit_usd=1,
                model=judge.DEFAULT_MODEL,
                user_id=self.team.alice_id,
            )
        self.assertNotIn("divorce", captured[0])

    def test_injected_memory_blocks_are_never_stored_as_evidence(self) -> None:
        """Retrieved memory captured back as a turn would become evidence for itself."""
        row = self.add(
            "<mem-os-context>\n- Alice prefers pnpm\n</mem-os-context>\nWhat should I use?"
        )
        self.assertNotIn("pnpm", row["content"])
        self.assertIn("What should I use?", row["content"])
        recall = self.add("<mem-os-recall>\n- Alice prefers pnpm\n</mem-os-recall>")
        self.assertEqual(recall["content"], security.INJECTED_MARKER)
        self.assertLess(len(security.INJECTED_MARKER), MIN_INDEX_CHARS)
        queued = self.conn.execute(
            "SELECT COUNT(*) AS n FROM index_outbox WHERE collection='raw' AND entity_id=%s",
            (str(recall["id"]),),
        ).fetchone()["n"]
        self.assertEqual(queued, 0)

    def test_an_all_injected_turn_is_not_reported_as_pending_indexing(self) -> None:
        from memkit import api, config
        from tests.httpharness import test_settings

        settings = test_settings()
        with patch.object(config, "_settings", settings):
            from fastapi.testclient import TestClient

            from tests.httpharness import stub_lifespan

            with (
                patch.object(api.app.router, "lifespan_context", stub_lifespan),
                TestClient(api.app) as client,
            ):
                response = client.post(
                    "/v1/evidence/events",
                    headers={"X-API-Key": self.team.alice_key},
                    json={
                        "session_id": "injected",
                        "role": "user",
                        "content": "<mem-os-recall>\n- Alice prefers pnpm and uv\n</mem-os-recall>",
                    },
                )
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["index_status"], "not_applicable")

    def test_the_client_scrub_removes_private_spans_like_the_server(self) -> None:
        path = Path(__file__).resolve().parents[1] / "integrations/hermes/memkit/scrub.py"
        spec = importlib.util.spec_from_file_location("hermes_scrub_under_test", path)
        scrub = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(scrub)

        text = f"keep <private>drop TOKEN={SECRET}</private> keep"
        self.assertEqual(scrub.scrub(text), security.redact(text).text)


if __name__ == "__main__":
    unittest.main()
