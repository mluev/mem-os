"""Profile rendering: the right facts, in the right block, within budget.

The stable half of the profile used to be selected by a kind the extractor
never writes, so identity facts fell into the recent block and disappeared from
injected context once they aged past its window. The blocks exist so that
cannot recur silently: each one has a defined source, and a fact in the wrong
place is a failing test rather than an absence nobody notices.
"""

from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from memkit import profiles, prompts, store
from tests.fixtures import make_db, seed_team


def _backdate(conn, memory_id: str, days: int) -> None:
    stamp = datetime.now(UTC) - timedelta(days=days)
    with conn.transaction():
        conn.execute(
            "UPDATE memories SET created_at=%s, updated_at=%s WHERE id=%s",
            (stamp, stamp, memory_id),
        )


class ProfileBlocksTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = make_db(seed=False)
        self.team = seed_team(self.conn)
        self.caller = self.team.principal("alice")

    def _add(self, text, kind, *, days_old=0, scope=None, subject=None, who="alice"):
        with self.conn.transaction():
            memory_id = store.add_memory(
                self.conn,
                scope_id=scope or self.team.scope_of(who),
                subject_id=subject,
                author_id=self.team.alice_id,
                text=text,
                kind=kind,
                source_role="user",
                review_status="confirmed",
            )
        if days_old:
            _backdate(self.conn, memory_id, days_old)
        return memory_id

    def _render(self, **kw):
        return profiles.render(
            self.conn,
            own_scope_id=self.caller.own_entity_id,
            team_scope_id=self.caller.team_entity_id,
            allowed_scope_ids=self.caller.scopes(),
            **kw,
        )

    def test_an_old_identity_fact_stays_in_the_profile(self) -> None:
        fact = self._add("Alice's GitHub handle is aivanova", "fact", days_old=90)
        blocks = self._render()["blocks"]
        self.assertEqual([item["id"] for item in blocks["about"]], [fact])

    def test_preferences_are_how_you_work_not_who_you_are(self) -> None:
        style = self._add("Prefers pnpm over npm", "preference")
        blocks = self._render()["blocks"]
        self.assertEqual([item["id"] for item in blocks["style"]], [style])
        self.assertEqual(blocks["about"], [])

    def test_team_rules_come_from_the_team_scope(self) -> None:
        rule = self._add("We always squash-merge", "preference", scope=self.team.team_id)
        blocks = self._render()["blocks"]
        self.assertEqual([item["id"] for item in blocks["team"]], [rule])

    def test_a_fact_about_a_person_is_not_a_team_rule(self) -> None:
        """Facts about people belong on their page, not in everyone's preamble."""
        bob_entity = self.team.scope_of("bob")
        self._add(
            "Bob prefers dark mode", "preference", scope=self.team.team_id, subject=bob_entity
        )
        blocks = self._render()["blocks"]
        self.assertEqual(blocks["team"], [])

    def test_the_project_block_follows_the_workspace(self) -> None:
        fact = self._add(
            "Mem OS stores memories in Postgres", "project", scope=self.team.project_id
        )
        blocks = self._render(project_scope_id=self.team.project_id)["blocks"]
        self.assertEqual([item["id"] for item in blocks["project"]], [fact])
        # Without the workspace the same fact must not leak into the preamble.
        self.assertEqual(self._render()["blocks"]["project"], [])

    def test_recent_holds_what_changed_lately(self) -> None:
        fresh = self._add("Deploys moved to Coolify", "decision", days_old=3)
        self._add("An old decision nobody revisits", "decision", days_old=200)
        blocks = self._render()["blocks"]
        self.assertEqual([item["id"] for item in blocks["recent"]], [fresh])

    def test_a_memory_appears_in_one_block_only(self) -> None:
        self._add("Prefers pnpm over npm", "preference")
        self._add("Alice is a backend engineer", "fact")
        blocks = self._render()["blocks"]
        seen = [item["id"] for block in blocks.values() for item in block]
        self.assertEqual(len(seen), len(set(seen)))

    def test_the_token_budget_is_respected(self) -> None:
        for index in range(40):
            self._add(f"Prefers tool number {index} for a great many daily tasks", "preference")
        rendered = self._render(budget_tokens=60)
        self.assertLessEqual(rendered["used_tokens"], 60)
        self.assertTrue(rendered["blocks"]["style"])

    def test_another_users_memory_never_appears(self) -> None:
        self._add("Bob's private note", "preference", scope=self.team.scope_of("bob"), who="bob")
        blocks = self._render()["blocks"]
        texts = [item["text"] for block in blocks.values() for item in block]
        self.assertNotIn("Bob's private note", texts)

    def test_the_blocks_match_the_kinds_the_prompt_writes(self) -> None:
        """A drift guard: the taxonomy lives in the prompt, the split lives here."""
        active = prompts.REGISTRY[prompts.DEFAULT_VERSION]
        for kind in profiles.IDENTITY_KINDS + profiles.STYLE_KINDS:
            self.assertIn(f'`kind="{kind}"`', active)


if __name__ == "__main__":
    unittest.main()
