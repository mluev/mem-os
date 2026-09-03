"""Profile rendering: stable kinds match what the extractor writes.

The stable block used to default to `identity`, a kind the v8 prompt forbids,
so extracted identity facts (kind `fact`) fell into the dynamic block and
disappeared from injected context once they were older than `dynamic_days`.
"""

from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from memkit import api, profiles, prompts, store
from tests.fixtures import OWNER, make_db


def _backdate(conn, memory_id: str, days: int) -> None:
    stamp = (datetime.now(UTC) - timedelta(days=days)).isoformat(timespec="seconds")
    stamp = stamp.replace("+00:00", "Z")
    conn.execute(
        "UPDATE memories SET created_at=?, updated_at=? WHERE id=?", (stamp, stamp, memory_id)
    )
    conn.commit()


class ProfileBlocksTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = make_db()
        self.defaults = api.ProfileIn()

    def _add(self, text: str, kind: str, *, days_old: int = 0) -> str:
        memory_id = store.add_memory(
            self.conn, owner_id=OWNER, text=text, kind=kind, source_role="user"
        )
        self.conn.commit()
        if days_old:
            _backdate(self.conn, memory_id, days_old)
        return memory_id

    def _render(self) -> dict:
        return profiles.render(
            self.conn,
            owner_id=OWNER,
            stable_kinds=list(self.defaults.stable_kinds),
            dynamic_days=self.defaults.dynamic_days,
            budget_tokens=self.defaults.budget_tokens,
        )

    def test_old_identity_fact_stays_in_the_stable_block(self) -> None:
        fact = self._add("User's GitHub handle is mluev", "fact", days_old=60)
        result = self._render()
        self.assertEqual([item["id"] for item in result["stable"]], [fact])
        self.assertEqual(result["dynamic"], [])

    def test_dynamic_block_keeps_only_recent_non_stable_kinds(self) -> None:
        recent = self._add("mem-os moves to Postgres", "project", days_old=3)
        self._add("portfolio uses Vue 3", "project", days_old=60)
        result = self._render()
        self.assertEqual([item["id"] for item in result["dynamic"]], [recent])
        self.assertEqual(result["stable"], [])

    def test_default_stable_kinds_are_the_kinds_the_prompt_writes(self) -> None:
        for kind in self.defaults.stable_kinds:
            self.assertIn(f'`kind="{kind}"`', prompts.REGISTRY[prompts.DEFAULT_VERSION])


if __name__ == "__main__":
    unittest.main()
