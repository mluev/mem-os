"""A secret must not survive a write, and must not leave the machine.

Two boundaries, one rule. Persistence is the first: whatever a caller sends is
scrubbed before it reaches a column, so a leaked dump or an exported archive
carries placeholders rather than credentials. Provider egress is the second and
is the one that actually costs money to get wrong -- a key pasted into a chat
would otherwise be sent to a third party and logged there.
"""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from memkit import judge, providers, store
from memkit.db import transaction
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


if __name__ == "__main__":
    unittest.main()
