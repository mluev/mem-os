"""The golden extractor scorer, which had no tests of its own.

`eval/golden.py` decides whether a prompt change ships. Only its
`--schema-only` path ran in CI, so the scoring rules that gate a release --
what counts as a leak, what counts as valid evidence, and which variant wins --
were never exercised. A scorer that silently stops detecting failures turns
every comparison green.

Nothing here calls a provider. The scorer is pure: cases in, operations in,
counters out, which is exactly why it can be tested offline and why it is the
only part of the paid harness that has to be right before spending anything.
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

import yaml

from memkit import prompts

ROOT = Path(__file__).resolve().parents[1]


def _load_golden():
    """Load eval/golden.py by path; `eval` is a namespace package here."""
    spec = importlib.util.spec_from_file_location("memkit_golden", ROOT / "eval" / "golden.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # @dataclass resolves annotations through sys.modules, so the module has to
    # be registered before it executes.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


golden = _load_golden()
from memkit import judge  # noqa: E402


def _case(**kw):
    raw = {
        "id": kw.pop("id", "a-case"),
        "probes": "whatever this case is for",
        # Golden cases carry (role, text) pairs; Case.parse numbers them from 1.
        "messages": [("user", "I always use pnpm, never npm")],
        **kw,
    }
    return golden.Case.parse(raw, 0)


def _op(text: str, **kw):
    return judge.Op(
        op=kw.pop("op", "ADD"),
        reason="stated by the user",
        text=text,
        kind=kw.pop("kind", "preference"),
        context=kw.pop("context", {}),
        importance=kw.pop("importance", 0.6),
        evidence=kw.pop(
            "evidence",
            [{"message_id": 1, "start_char": 0, "end_char": 17, "quote": "I always use pnpm"}],
        ),
        scope=kw.pop("scope", None),
        subject=kw.pop("subject", None),
        subject_name=kw.pop("subject_name", None),
    )


# The block a routing case shows, in the shape entities.for_prompt produces.
_ENTITIES = [
    {"ref": 1, "label": "you, the speaker", "name": "Artem Volkov", "aliases": []},
    {"ref": 2, "label": "team", "name": "Northline", "aliases": []},
    {"ref": 3, "label": "teammate", "name": "Alexander Petrov", "aliases": ["Саша"]},
]


def _score():
    return golden.Score(model="m", version="v")


class ScoreCaseTest(unittest.TestCase):
    def test_a_wanted_fact_is_found(self) -> None:
        case = _case(expect=[{"text": "pnpm"}])
        sc = _score()
        golden.score_case(case, [_op("Prefers pnpm over npm")], sc)
        self.assertEqual((sc.expected, sc.found), (1, 1))
        self.assertEqual(sc.failures, [])

    def test_a_missing_fact_is_reported(self) -> None:
        case = _case(expect=[{"text": "pnpm"}])
        sc = _score()
        golden.score_case(case, [_op("Prefers yarn")], sc)
        self.assertEqual((sc.expected, sc.found), (1, 0))
        self.assertTrue(any("MISSED" in failure for failure in sc.failures))

    def test_emitting_anything_for_an_empty_case_is_a_false_positive(self) -> None:
        sc = _score()
        golden.score_case(_case(expect=[]), [_op("An invented durable fact")], sc)
        self.assertEqual(sc.false_positives, 1)

    def test_a_credential_leak_is_counted_as_a_leak(self) -> None:
        case = _case(id="credentials-must-not-leak", expect=[], reject=["sk-live"])
        sc = _score()
        golden.score_case(case, [_op("The key is sk-live-abc123")], sc)
        self.assertEqual(sc.leaks, 1)
        self.assertTrue(any("LEAK" in failure for failure in sc.failures))

    def test_a_rejected_pattern_elsewhere_is_a_false_positive_not_a_leak(self) -> None:
        case = _case(expect=[], reject=["tired"])
        sc = _score()
        golden.score_case(case, [_op("User is tired today")], sc)
        self.assertEqual((sc.leaks, sc.false_positives), (0, 2))

    def test_a_citation_of_an_assistant_message_is_invalid(self) -> None:
        case = _case(
            expect=[{"text": "pnpm"}],
            messages=[
                ("user", "I always use pnpm"),
                ("assistant", "Noted: you use pnpm"),
            ],
        )
        sc = _score()
        golden.score_case(
            case,
            [
                _op(
                    "Prefers pnpm",
                    evidence=[{"message_id": 2, "start_char": 0, "end_char": 5, "quote": "Noted"}],
                )
            ],
            sc,
        )
        self.assertEqual(sc.evidence_ok, 0)
        self.assertEqual(sc.evidence_checked, 1)

    def test_an_out_of_range_citation_is_invalid(self) -> None:
        case = _case(expect=[{"text": "pnpm"}])
        sc = _score()
        golden.score_case(
            case,
            [_op("Prefers pnpm", evidence=[{"message_id": 1, "start_char": 0, "end_char": 9999}])],
            sc,
        )
        self.assertEqual(sc.evidence_ok, 0)

    def test_context_and_kind_mismatches_are_recorded(self) -> None:
        case = _case(
            expect=[{"text": "pnpm", "context": {"source_workspace": "mem-os"}, "kind": "fact"}]
        )
        sc = _score()
        golden.score_case(case, [_op("Prefers pnpm", context={}, kind="preference")], sc)
        self.assertEqual((sc.context_ok, sc.context_checked), (0, 1))
        self.assertEqual((sc.kind_ok, sc.kind_checked), (0, 1))

    def test_routing_is_not_scored_when_the_case_shows_no_entities(self) -> None:
        """A single-user window has nothing to route to, and the model is shown
        "(none)". Counting those as routing successes would dilute the metric
        with 24 free passes."""
        sc = _score()
        golden.score_case(_case(expect=[{"text": "pnpm"}]), [_op("Prefers pnpm")], sc)
        self.assertEqual((sc.routing_ok, sc.routing_checked), (0, 0))

    def test_the_right_subject_scores(self) -> None:
        case = _case(entities=_ENTITIES, expect=[{"text": "pnpm", "subject": 3}])
        sc = _score()
        golden.score_case(case, [_op("Alexander prefers pnpm", subject=3)], sc)
        self.assertEqual((sc.routing_ok, sc.routing_checked), (1, 1))

    def test_the_wrong_subject_fails_even_though_the_text_matched(self) -> None:
        case = _case(entities=_ENTITIES, expect=[{"text": "pnpm", "subject": 3}])
        sc = _score()
        golden.score_case(case, [_op("Alexander prefers pnpm", subject=2)], sc)
        self.assertEqual((sc.found, sc.routing_ok), (1, 0))
        self.assertTrue(any("routing" in failure for failure in sc.failures))

    def test_a_spurious_scope_is_as_wrong_as_a_missing_one(self) -> None:
        """The v9 regression in miniature: a personal preference routed to the
        team is still a well-formed, correctly cited memory in the wrong place."""
        case = _case(entities=_ENTITIES, expect=[{"text": "pnpm"}])
        sc = _score()
        golden.score_case(case, [_op("Prefers pnpm", scope=2)], sc)
        self.assertEqual((sc.routing_ok, sc.routing_checked), (0, 1))

    def test_omitting_routing_when_none_was_wanted_scores(self) -> None:
        case = _case(entities=_ENTITIES, expect=[{"text": "pnpm"}])
        sc = _score()
        golden.score_case(case, [_op("Prefers pnpm")], sc)
        self.assertEqual((sc.routing_ok, sc.routing_checked), (1, 1))

    def test_an_unlisted_person_is_asserted_by_name(self) -> None:
        case = _case(entities=_ENTITIES, expect=[{"text": "pnpm", "subject_name": "Тимур Аскаров"}])
        sc = _score()
        golden.score_case(case, [_op("Тимур Аскаров prefers pnpm", subject_name="Тимур")], sc)
        self.assertEqual(sc.routing_ok, 0)
        sc = _score()
        golden.score_case(
            case, [_op("Тимур Аскаров prefers pnpm", subject_name="Тимур Аскаров")], sc
        )
        self.assertEqual(sc.routing_ok, 1)

    def test_a_number_outside_the_block_is_counted_as_fabricated(self) -> None:
        """Production drops the whole operation, so this is scored even when the
        text was right: it is the tell that the model is guessing at routing."""
        case = _case(entities=_ENTITIES, expect=[{"text": "pnpm", "scope": 2}])
        sc = _score()
        golden.score_case(case, [_op("Prefers pnpm", scope=9)], sc)
        self.assertEqual(sc.fabricated, 1)
        self.assertTrue(any("FABRICATED" in failure for failure in sc.failures))

    def test_over_emission_is_measured_against_max_ops(self) -> None:
        case = _case(expect=[{"text": "pnpm"}], max_ops=1)
        sc = _score()
        golden.score_case(case, [_op("Prefers pnpm"), _op("Prefers pytest")], sc)
        self.assertGreaterEqual(sc.over_emission, 1)


class WinnerTest(unittest.TestCase):
    """Safety outranks accuracy: a leaking variant can never win."""

    def _score(self, **kw):
        sc = golden.Score(model=kw.pop("model", "m"), version=kw.pop("version", "v"))
        sc.expected = kw.pop("expected", 10)
        sc.found = kw.pop("found", 8)
        sc.evidence_checked = sc.evidence_ok = kw.pop("evidence", 8)
        for name, value in kw.items():
            setattr(sc, name, value)
        return sc

    def test_the_more_accurate_variant_wins(self) -> None:
        worse = self._score(model="worse", found=5, evidence=5)
        better = self._score(model="better", found=9, evidence=9)
        self.assertEqual(golden._winner([worse, better]), "better")

    def test_a_leaking_variant_cannot_win(self) -> None:
        leaky = self._score(model="leaky", found=10, evidence=10, leaks=1)
        safe = self._score(model="safe", found=1, evidence=1)
        self.assertEqual(golden._winner([leaky, safe]), "safe")

    def test_invalid_evidence_disqualifies(self) -> None:
        sloppy = self._score(model="sloppy", found=10)
        sloppy.evidence_checked, sloppy.evidence_ok = 10, 9
        safe = self._score(model="safe", found=1, evidence=1)
        self.assertEqual(golden._winner([sloppy, safe]), "safe")

    def test_no_safe_variant_means_no_winner(self) -> None:
        self.assertIsNone(golden._winner([self._score(model="leaky", leaks=1)]))

    def test_false_positives_lose_to_precision_at_equal_recall(self) -> None:
        noisy = self._score(model="noisy", false_positives=3)
        clean = self._score(model="clean", false_positives=0)
        self.assertEqual(golden._winner([noisy, clean]), "clean")

    def test_an_invented_fact_outranks_extra_recall(self) -> None:
        """Safety first and absolute: nothing buys back a store with fiction
        in it, so one false positive loses to a variant that found less."""
        noisy = self._score(model="noisy", found=10, evidence=10, false_positives=1)
        clean = self._score(model="clean", found=6, evidence=6)
        self.assertEqual(golden._winner([noisy, clean]), "clean")

    def test_routing_outranks_context_at_equal_recall(self) -> None:
        """A fact in the wrong teammate's scope is readable by the wrong
        person; context drift only makes a fact harder to retrieve."""
        routes = self._score(model="routes", routing_ok=7, routing_checked=7)
        routes.context_ok, routes.context_checked = 4, 8
        drifts = self._score(model="drifts", routing_ok=3, routing_checked=7)
        drifts.context_ok, drifts.context_checked = 8, 8
        self.assertEqual(golden._winner([routes, drifts]), "routes")

    def test_recall_still_outranks_routing(self) -> None:
        found = self._score(model="found", found=9, evidence=9, routing_ok=0, routing_checked=7)
        missed = self._score(model="missed", found=4, evidence=4, routing_ok=7, routing_checked=7)
        self.assertEqual(golden._winner([found, missed]), "found")


class GoldenFileTest(unittest.TestCase):
    """The committed golden set, checked against the prompt it will be run with.

    This is what `--schema-only` does before a paid run. Running it here means a
    new placeholder in the active prompt fails offline rather than after the
    budget reservation.
    """

    @classmethod
    def setUpClass(cls) -> None:
        raw = yaml.safe_load(golden.GOLDEN.read_text(encoding="utf-8")) or []
        cls.raw = raw
        cls.cases = [golden.Case.parse(item, index) for index, item in enumerate(raw)]

    def test_the_golden_set_is_not_empty(self) -> None:
        self.assertGreater(len(self.cases), 20)

    def test_every_case_renders_against_the_active_prompt(self) -> None:
        for case in self.cases:
            prompts.render(
                prompts.DEFAULT_VERSION,
                today="2026-01-01",
                window=judge.render_window(case.messages),
                candidates=judge.render_candidates(case.candidates),
                context="{}",
                entities=judge.render_entities(case.entities),
                session_date=case.session_date,
            )

    def test_no_case_still_expects_a_retired_key(self) -> None:
        """`type` and `holds_in_other_repos` belonged to the old single-owner
        schema; an expectation on one would score nothing and quietly inflate
        recall. `scope` survived the rename with a new meaning -- an integer
        reference into ENTITIES -- so it is checked by type, not by name."""
        self.assertEqual(golden.retired_expectations(self.raw), [])
        self.assertEqual(
            golden.retired_expectations([{"id": "old", "expect": [{"scope": "mem-os"}]}]),
            ["old"],
        )
        self.assertEqual(golden.retired_expectations([{"id": "new", "expect": [{"scope": 3}]}]), [])

    def test_the_routing_cases_reference_only_numbers_their_block_defines(self) -> None:
        """An expectation on a number the case never showed would demand a
        fabrication -- and would be scored as one."""
        for case in self.cases:
            wanted = {
                value
                for expected in case.expect
                for key, value in expected.items()
                if key in ("scope", "subject")
            }
            self.assertLessEqual(wanted, case.refs, case.id)

    def test_the_golden_set_covers_routing(self) -> None:
        """Routing is the reason v9 and v10 exist; unmeasured, it is a claim."""
        routing = [case for case in self.cases if case.entities]
        self.assertGreaterEqual(len(routing), 7)
        subjects = [c for c in routing for e in c.expect if "subject" in e]
        unlisted = [c for c in routing for e in c.expect if "subject_name" in e]
        scopes = [c for c in routing for e in c.expect if "scope" in e]
        nowhere = [
            c
            for c in routing
            for e in c.expect
            if not {"scope", "subject", "subject_name"} & set(e)
        ]
        self.assertTrue(subjects and unlisted and scopes and nowhere)

    def test_a_case_may_declare_its_own_recording_date(self) -> None:
        """v8 onwards resolves relative time against the window's date, so a
        case probing that has to be able to differ from today."""
        case = _case(session_date="2026-03-10")
        self.assertEqual(case.session_date, "2026-03-10")
        self.assertIsNone(_case().session_date)


if __name__ == "__main__":
    unittest.main()
