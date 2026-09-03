"""Prompt registry contract: versions render what they declare, nothing lies.

judge.py's module comment cites test_production_prompt_is_the_active_registry_version
as the guard that PROMPT_VERSION and the rendered text cannot drift apart; the
test had been lost in a refactor while the comment survived. It lives here now,
next to the v8 date-anchor contract.
"""

from __future__ import annotations

import re
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

    def test_v8_still_carries_every_rule_it_was_accepted_for(self) -> None:
        """A deleted rule would otherwise pass every test in this suite.

        v8's rules are each a measured failure it prevents (decisions/0053), and
        an edit that drops one changes extraction behaviour with no test
        turning red. These are the load-bearing clauses, not the whole text.
        """
        # The template is hard-wrapped, so clauses are matched against the text
        # with runs of whitespace collapsed.
        v8 = re.sub(r"\s+", " ", prompts.REGISTRY["v8"])
        required = [
            # Date anchoring.
            "the recording date is the ONLY anchor",
            # Source fidelity.
            "Only a user's own words can support a memory",
            "exact spans from USER messages only",
            # Taxonomy: the profile's stable block depends on these two kinds.
            '`kind="preference"`',
            '`kind="fact"`',
            # Context discipline.
            "character for character",
            # Targets.
            "only a supplied candidate in the same context",
            # Length, which Op.parse enforces at 200 characters.
            "under 200 characters",
            # Findability and change capture.
            "Keep proper nouns verbatim",
            "capture the transition",
            # The four named failure modes.
            "Echo extraction",
            "Meta-extraction",
            "Detail contamination",
            "First-topic dominance",
        ]
        for clause in required:
            self.assertIn(clause, v8, f"v8 lost a rule it was accepted for: {clause!r}")

    def test_the_consolidator_prompt_states_its_two_hard_limits(self) -> None:
        consolidate = re.sub(r"\s+", " ", prompts.CONSOLIDATE_V2)
        self.assertIn("Return null when they differ", consolidate)
        self.assertIn("under 200 characters", consolidate)

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
