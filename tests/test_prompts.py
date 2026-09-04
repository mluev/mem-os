"""Prompt registry contract: versions render what they declare, nothing lies.

judge.py's module comment cites test_production_prompt_is_the_active_registry_version
as the guard that PROMPT_VERSION and the rendered text cannot drift apart; the
test had been lost in a refactor while the comment survived. It lives here now,
beside the v8 date-anchor contract and the routing blocks of v9 and v10.

Old versions stay in the registry and stay tested. A stored fact carries the
version that produced it, so `extraction_version='v7'` has to keep meaning
something a person can read back.
"""

from __future__ import annotations

import re
import unittest

from memkit import judge, prompts


def _collapsed(version: str) -> str:
    """The template with runs of whitespace flattened.

    The prompts are hard-wrapped to fit a diff, so a clause that must survive
    an edit is matched against the text rather than against a line.
    """
    return re.sub(r"\s+", " ", prompts.REGISTRY[version])


class TestPromptRegistry(unittest.TestCase):
    def test_production_prompt_is_the_active_registry_version(self) -> None:
        self.assertEqual(judge.PROMPT_VERSION, prompts.DEFAULT_VERSION)
        self.assertIn(judge.PROMPT_VERSION, prompts.REGISTRY)
        rendered = judge.build_prompt(window=[], candidates=[], context={})
        self.assertIn("CONVERSATION WINDOW", rendered)

    def test_the_default_is_a_version_that_was_measured_into_place(self) -> None:
        """This test used to assert `DEFAULT_VERSION == "v9"`, and was red.

        v9 was written, tested, and then *not* promoted: the paid comparison
        found it regressed context accuracy and left its own routing unmeasured
        (docs/measurements.md#extractor-prompt-v8-against-v9). The assertion
        outlived the decision. Naming a specific version here means the test has
        to be edited by whoever moves the default, which is the point — so it
        asserts the promotion rule instead of a literal, and the literal lives
        in the comment above `DEFAULT_VERSION` where the reasoning is.
        """
        self.assertIn(prompts.DEFAULT_VERSION, prompts.REGISTRY)
        self.assertEqual(prompts.DEFAULT_VERSION, judge.PROMPT_VERSION)

    def test_retired_versions_stay_readable(self) -> None:
        """Facts stamped v7, v8 or v9 are still in the store."""
        self.assertEqual(sorted(prompts.REGISTRY), ["v10", "v7", "v8", "v9"])

    def test_unknown_version_raises(self) -> None:
        with self.assertRaises(ValueError):
            prompts.render("v999", today="2026-08-28", window="", candidates="")


class TestV9Routing(unittest.TestCase):
    """v9 = v8 plus the block that decides where a fact goes."""

    def _render(self, **kw) -> str:
        defaults = {
            "today": "2026-08-28",
            "window": "[1] user: Саша is on holiday",
            "candidates": "(none)",
            "context": '{"workspace": "mem-os"}',
            "entities": "1. you, the speaker: Alice Ivanova",
            "session_date": "2026-03-10",
        }
        return prompts.render("v9", **{**defaults, **kw})

    def test_the_entities_block_is_rendered(self) -> None:
        rendered = self._render()
        self.assertIn("ENTITIES (refer to them by number only; never invent a number)", rendered)
        self.assertIn("1. you, the speaker: Alice Ivanova", rendered)

    def test_an_absent_entity_block_renders_as_none_rather_than_a_placeholder(self) -> None:
        """A leaked `{entities}` would read to the model as a literal instruction."""
        rendered = self._render(entities=None)
        self.assertIn("(none)", rendered)
        self.assertNotIn("{entities}", rendered)

    def test_v9_keeps_everything_v8_said(self) -> None:
        """v9 adds routing; it must not have quietly dropped an extraction rule."""
        v8_body = _collapsed("v8").split("CONTEXT")[0]
        self.assertIn(v8_body.strip(), _collapsed("v9"))

    def test_v9_states_every_routing_rule_it_was_accepted_for(self) -> None:
        """Each clause is a route, and a dropped one silently changes where
        facts land -- with no test turning red, because the memory is still
        well-formed and cited. These are the load-bearing clauses."""
        v9 = _collapsed("v9")
        required = [
            # The speaker is the default, and the tie-break is explicit.
            "needs no scope and no subject",
            "when torn between the speaker and the team, choose the speaker",
            # A fact about a teammate is shared, not private.
            "set subject to their number and omit scope",
            # Projects and shared rules.
            "set scope to its number",
            "set scope to the team's number, no subject",
            # The refusal that keeps a claim off the wrong person.
            "copy their name verbatim into `subject_name`",
            "Do not guess which listed person was meant",
            # Numbers only: a uuid comes back mutated, a name comes back guessed.
            "refer to them by number only; never invent a number",
        ]
        for clause in required:
            self.assertIn(clause, v9, f"v9 lost a routing rule: {clause!r}")


class TestV10Routing(unittest.TestCase):
    """v10 = v9's routing, reordered so rule 5 is read before it.

    The regression v10 exists to undo was invisible to every prompt test: v9
    was well-formed, said everything it was meant to say, and still scoped
    facts that belonged globally. What can be tested offline is that the three
    changes which the measurement pointed at are actually present.
    """

    def test_routing_comes_after_context_not_before_it(self) -> None:
        v10 = prompts.REGISTRY["v10"]
        self.assertLess(v10.index("CONTEXT"), v10.index("ROUTING"))
        self.assertLess(v10.index("Context defaults to empty"), v10.index("ROUTING"))
        # v9 is the counterexample, and the reason this test exists.
        v9 = prompts.REGISTRY["v9"]
        self.assertLess(v9.index("ROUTING"), v9.index("CONTEXT\n"))

    def test_scope_and_context_are_named_as_different_fields(self) -> None:
        v10 = _collapsed("v10")
        self.assertIn("Scope is not context", v10)
        self.assertIn("a scoped memory usually still has empty context", v10)

    def test_rule_five_asks_the_counterfactual_rather_than_listing_examples(self) -> None:
        v10 = _collapsed("v10")
        self.assertIn("said again tomorrow in another repo, would this sentence still hold", v10)
        self.assertIn("character for character", v10)

    def test_v10_keeps_every_routing_rule_v9_was_accepted_for(self) -> None:
        v10 = _collapsed("v10")
        for clause in [
            "no scope and no subject",
            "set subject to their number and omit scope",
            "set scope to its number",
            "set scope to the team's number, no subject",
            "Do not guess which listed person was meant",
            "refer to them by number only; never invent a number",
            # v10 tightens two of v9's clauses, each because a measured run
            # showed the looser wording being read past: the unresolved name
            # came back transliterated, and an unlisted project came back
            # routed to the nearest listed one.
            "in the user's own spelling and script",
            "Never route to a number whose name is not the thing the sentence is about",
        ]:
            self.assertIn(clause, v10, f"v10 lost a routing rule: {clause!r}")

    def test_v10_keeps_v8s_extraction_rules(self) -> None:
        """Rule 5 was rewritten on purpose; nothing else was."""
        v10 = _collapsed("v10")
        for clause in [
            "the recording date is the ONLY anchor",
            "Only a user's own words can support a memory",
            "exact spans from USER messages only",
            "only a supplied candidate in the same context",
            "under 200 characters",
            "Keep proper nouns verbatim",
            "capture the transition",
            "Echo extraction",
            "Meta-extraction",
            "Detail contamination",
            "First-topic dominance",
        ]:
            self.assertIn(clause, v10, f"v10 lost a v8 rule: {clause!r}")

    def test_v10_renders_entities_and_both_dates(self) -> None:
        rendered = prompts.render(
            "v10",
            today="2026-09-04",
            window="[1] user: Саша требует настоящую базу",
            candidates="(none)",
            context='{"workspace": "mem-os"}',
            entities="1. you, the speaker: Artem Volkov\n5. teammate: Alexander Petrov",
            session_date="2026-03-10",
        )
        self.assertIn("Today is 2026-09-04.", rendered)
        self.assertIn("recorded on 2026-03-10", rendered)
        self.assertIn("5. teammate: Alexander Petrov", rendered)
        self.assertNotIn("{entities}", rendered)


class TestV8Contract(unittest.TestCase):
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
        v8 = _collapsed("v8")
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

    def test_an_older_version_ignores_inputs_it_never_declared(self) -> None:
        """New inputs must not break an old prompt; that is why str.format is
        given every field and each template takes only what it names."""
        rendered = prompts.render(
            "v7",
            today="2026-08-28",
            window="",
            candidates="(none)",
            entities="1. you, the speaker: Alice Ivanova",
        )
        self.assertNotIn("ENTITIES", rendered)


class TestConsolidatePrompt(unittest.TestCase):
    def test_the_consolidator_prompt_states_its_two_hard_limits(self) -> None:
        consolidate = re.sub(r"\s+", " ", prompts.CONSOLIDATE_V2)
        self.assertIn("Return null when they differ", consolidate)
        self.assertIn("under 200 characters", consolidate)

    def test_the_consolidator_prompt_lists_the_cluster_it_is_judging(self) -> None:
        rendered = prompts.render_consolidate(
            [
                {"id": "a", "kind": "preference", "context": {}, "text": "Prefers pnpm"},
                {"id": "b", "kind": "preference", "context": {}, "text": "Uses pnpm always"},
            ]
        )
        self.assertIn("id=a", rendered)
        self.assertIn("Uses pnpm always", rendered)


if __name__ == "__main__":
    unittest.main()
