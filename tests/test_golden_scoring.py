"""The golden extractor scorer, which had no tests of its own.

`eval/golden.py` decides whether a prompt change ships. Only its
`--schema-only` path ran in CI, so the scoring rules that gate a release --
what counts as a leak, what counts as valid evidence, and which variant wins --
were never exercised. A scorer that silently stops detecting failures turns
every comparison green.
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

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
    )


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


if __name__ == "__main__":
    unittest.main()
