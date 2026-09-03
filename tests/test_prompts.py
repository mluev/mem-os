"""Prompt registry contract: versions render what they declare, nothing lies.

judge.py's module comment cites test_production_prompt_is_the_active_registry_version
as the guard that PROMPT_VERSION and the rendered text cannot drift apart; the
test had been lost in a refactor while the comment survived. It lives here now,
next to the v8 date-anchor contract.
"""

from __future__ import annotations

import unittest

from memkit import judge, prompts


class TestPromptRegistry(unittest.TestCase):
    def test_production_prompt_is_the_active_registry_version(self) -> None:
        self.assertIn(judge.PROMPT_VERSION, prompts.REGISTRY)
        rendered = judge.build_prompt(window=[], candidates=[], context={})
        self.assertIn("CONVERSATION WINDOW", rendered)

    def test_unknown_version_raises(self) -> None:
        with self.assertRaises(ValueError):
            prompts.render("v999", today="2026-08-28", window="", candidates="")

    def test_v8_renders_both_dates(self) -> None:
        rendered = prompts.render(
            "v8",
            today="2026-08-28",
            window="[1] user: hi",
            candidates="(none)",
            context='{"workspace": "mem-os"}',
            session_date="2026-03-10",
        )
        self.assertIn("Today is 2026-08-28.", rendered)
        self.assertIn("recorded on 2026-03-10", rendered)
        self.assertIn('{"workspace": "mem-os"}', rendered)
        self.assertIn("[1] user: hi", rendered)

    def test_v8_anchors_to_today_when_session_date_is_missing(self) -> None:
        rendered = prompts.render(
            "v8",
            today="2026-08-28",
            window="",
            candidates="(none)",
            session_date=None,
        )
        self.assertIn("recorded on 2026-08-28", rendered)

    def test_v7_still_renders_without_date_placeholders(self) -> None:
        rendered = prompts.render(
            "v7",
            today="2026-08-28",
            window="[1] user: hi",
            candidates="(none)",
            session_date="2026-03-10",
        )
        self.assertNotIn("2026-08-28", rendered)
        self.assertNotIn("2026-03-10", rendered)


if __name__ == "__main__":
    unittest.main()
