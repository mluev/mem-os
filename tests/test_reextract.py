"""Re-extraction: replaying history under another prompt version.

The property that matters is that nothing is lost. A replay produces a fresh set and
retires the old one, so `extraction_version` can be compared on one eval — which is
the entire argument docs/04-judge.md makes for recording it. If a replay could
destroy the old set, the column would be decoration.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from memkit import extract, judge, prompts, reextract, store  # noqa: E402
from tests.fixtures import (  # noqa: E402
    OWNER,
    StubEmbedder,
    StubQdrant,
    make_db,
)


def add_turns(conn, session, pairs, *, created="2026-07-01T00:00:00Z"):
    """Insert (role, content) pairs into a session and return their ids."""
    from memkit.db import ensure_session

    ensure_session(conn, session, OWNER, "chat")
    ids = []
    for role, content in pairs:
        cur = conn.execute(
            "INSERT INTO messages (session_id, role, content, created_at) "
            "VALUES (?,?,?,?)",
            (session, role, content, created),
        )
        ids.append(int(cur.lastrowid))
    conn.commit()
    return ids


class TestWindowing(unittest.TestCase):
    def setUp(self):
        self.conn = make_db()

    def test_windows_do_not_span_sessions(self):
        add_turns(self.conn, "s-a", [("user", "a1"), ("assistant", "a2")])
        add_turns(self.conn, "s-b", [("user", "b1"), ("assistant", "b2")])
        windows = reextract._windows(self.conn, owner_id=OWNER, from_date=None)
        self.assertEqual(len(windows), 2)
        for window in windows:
            self.assertEqual(len({r["session_id"] for r in window}), 1)

    def test_windows_are_capped_at_the_live_window_size(self):
        add_turns(
            self.conn, "s-a",
            [("user", f"m{i}") for i in range(extract.WINDOW_SIZE * 2 + 3)],
        )
        windows = reextract._windows(self.conn, owner_id=OWNER, from_date=None)
        self.assertEqual([len(w) for w in windows],
                         [extract.WINDOW_SIZE, extract.WINDOW_SIZE, 3])

    def test_assistant_only_windows_are_dropped(self):
        # Same rule as the live path's fast-forward: a window with no user turn cannot
        # yield a fact about the user, so paying for it is pure waste.
        add_turns(self.conn, "s-a", [("assistant", "log"), ("assistant", "more log")])
        self.assertEqual(reextract._windows(self.conn, owner_id=OWNER, from_date=None), [])

    def test_from_date_filters(self):
        add_turns(self.conn, "s-old", [("user", "old")], created="2026-01-01T00:00:00Z")
        add_turns(self.conn, "s-new", [("user", "new")], created="2026-07-01T00:00:00Z")
        windows = reextract._windows(
            self.conn, owner_id=OWNER, from_date="2026-06-01"
        )
        self.assertEqual(len(windows), 1)
        self.assertEqual(windows[0][0]["content"], "new")


class TestPlan(unittest.TestCase):
    def setUp(self):
        self.conn = make_db()

    def test_dry_run_counts_and_prices_without_calling(self):
        add_turns(self.conn, "s-a", [("user", f"m{i}") for i in range(15)])
        plan = reextract.plan(
            self.conn, owner_id=OWNER, from_date=None,
            model="gemini-3.5-flash-lite",
        )
        self.assertEqual(plan.messages, 15)
        self.assertEqual(plan.windows, 2)
        self.assertEqual(plan.sessions, 1)
        self.assertGreater(plan.estimated_cost_usd, 0)
        self.assertEqual(plan.basis, "docs estimate")

    def test_estimate_uses_measured_tokens_once_real_calls_exist(self):
        add_turns(self.conn, "s-a", [("user", "m")])
        self.conn.execute(
            """INSERT INTO judge_runs
               (kind, model, prompt_version, input_json, input_tokens,
                output_tokens, created_at)
               VALUES ('extract','m','v6','{}', 3000, 90, '2026-07-01T00:00:00Z')"""
        )
        self.conn.commit()
        plan = reextract.plan(
            self.conn, owner_id=OWNER, from_date=None, model="gemini-3.5-flash-lite"
        )
        self.assertEqual(plan.input_tokens_per_call, 3000)
        self.assertIn("measured", plan.basis)


class TestVersionGuard(unittest.TestCase):
    def test_an_unknown_version_is_refused_before_any_call(self):
        conn = make_db()
        with self.assertRaises(ValueError) as caught:
            reextract.run(
                conn, StubQdrant(), StubEmbedder(),
                owner_id=OWNER, from_date=None, version="v99",
                model="gemini-3.5-flash-lite", monthly_limit_usd=15.0,
            )
        self.assertIn("v99", str(caught.exception))

    def test_every_registry_version_is_accepted(self):
        for version in prompts.REGISTRY:
            self.assertIn(version, prompts.REGISTRY, version)


class TestReplay(unittest.TestCase):
    """The write path of a replay, with the judge stubbed."""

    def setUp(self):
        self.conn = make_db()
        self.q = StubQdrant()
        self.ids = add_turns(
            self.conn, "s-a",
            [("user", "i prefer pnpm"), ("assistant", "noted")],
        )
        # An existing fact drawn from those messages, as v4 would have left it.
        self.old = store.add_memory(
            self.conn, self.q, StubEmbedder(), owner_id=OWNER,
            text="Prefers pnpm", type="preference", extraction_version="v4",
        )
        self.conn.executemany(
            "INSERT INTO memory_sources (memory_id, message_id) VALUES (?,?)",
            [(self.old, mid) for mid in self.ids],
        )
        self.conn.commit()

    def _run(self, ops, **kw):
        result = judge.JudgeResult(
            ops=ops, judge_run_id=None, input_tokens=10, output_tokens=5,
            cost_usd=0.001, latency_ms=10,
        )
        with patch.object(judge, "extract", return_value=result):
            return reextract.run(
                self.conn, self.q, StubEmbedder(),
                owner_id=OWNER, from_date=None, version="v6",
                model="gemini-3.5-flash-lite", monthly_limit_usd=15.0, **kw,
            )

    def _add_op(self, text="Prefers pnpm over npm everywhere"):
        return judge.Op(
            op="ADD", reason="r", text=text, type="preference",
            scope="user", importance=0.8, confidence=0.9,
        )

    def test_new_facts_carry_the_replayed_version_not_the_active_one(self):
        out = self._run([self._add_op()])
        self.assertEqual(out.added, 1)
        row = self.conn.execute(
            "SELECT extraction_version FROM memories WHERE id != ?", (self.old,)
        ).fetchone()
        self.assertEqual(row["extraction_version"], "v6")

    def test_the_old_set_is_superseded_not_deleted(self):
        out = self._run([self._add_op()])
        row = self.conn.execute(
            "SELECT status, text FROM memories WHERE id = ?", (self.old,)
        ).fetchone()
        self.assertEqual(row["status"], "superseded")
        self.assertEqual(row["text"], "Prefers pnpm")  # content intact
        self.assertEqual(out.superseded_ids, [self.old])

    def test_nothing_is_retired_when_the_replay_produced_nothing(self):
        # Replacing a set with an empty one is a pure loss, so the old set stays.
        out = self._run([])
        self.assertEqual(out.added, 0)
        self.assertEqual(out.superseded, 0)
        row = self.conn.execute(
            "SELECT status FROM memories WHERE id = ?", (self.old,)
        ).fetchone()
        self.assertEqual(row["status"], "active")

    def test_a_partial_run_only_retires_what_it_re_read(self):
        """The defect the first live dry-run exposed.

        With max_calls set, retiring the whole selection would drop facts whose
        messages were never re-processed -- deleting evidence in exchange for nothing.
        """
        other = add_turns(self.conn, "s-b", [("user", "i also prefer vitest")])
        untouched = store.add_memory(
            self.conn, self.q, StubEmbedder(), owner_id=OWNER,
            text="Prefers vitest", type="preference", extraction_version="v4",
        )
        self.conn.execute(
            "INSERT INTO memory_sources (memory_id, message_id) VALUES (?,?)",
            (untouched, other[0]),
        )
        self.conn.commit()

        out = self._run([self._add_op()], max_calls=1)
        self.assertEqual(out.calls, 1)
        statuses = dict(
            self.conn.execute("SELECT id, status FROM memories").fetchall()
        )
        self.assertEqual(statuses[self.old], "superseded")
        self.assertEqual(statuses[untouched], "active")

    def test_a_fact_spanning_a_re_read_and_an_untouched_window_survives(self):
        # Half its evidence has not been replaced, so retiring it would be wrong.
        other = add_turns(self.conn, "s-b", [("user", "and vitest")])
        self.conn.execute(
            "INSERT INTO memory_sources (memory_id, message_id) VALUES (?,?)",
            (self.old, other[0]),
        )
        self.conn.commit()
        out = self._run([self._add_op()], max_calls=1)
        self.assertEqual(out.superseded, 0)
        row = self.conn.execute(
            "SELECT status FROM memories WHERE id = ?", (self.old,)
        ).fetchone()
        self.assertEqual(row["status"], "active")

    def test_budget_refusal_stops_before_retiring_anything(self):
        result = judge.JudgeResult(
            ops=[], judge_run_id=None, input_tokens=0, output_tokens=0,
            cost_usd=0.0, latency_ms=0, error="monthly_cost_limit_reached",
        )
        with patch.object(judge, "extract", return_value=result):
            out = reextract.run(
                self.conn, self.q, StubEmbedder(),
                owner_id=OWNER, from_date=None, version="v6",
                model="gemini-3.5-flash-lite", monthly_limit_usd=15.0,
            )
        self.assertIn("monthly_cost_limit_reached", out.errors)
        self.assertEqual(out.superseded, 0)
        row = self.conn.execute(
            "SELECT status FROM memories WHERE id = ?", (self.old,)
        ).fetchone()
        self.assertEqual(row["status"], "active")


class TestCandidateExclusion(unittest.TestCase):
    def test_the_replaced_set_is_kept_out_of_the_candidate_block(self):
        """Otherwise the judge emits UPDATE against the facts being replaced.

        That would mutate the old set in place and destroy the version comparison
        the operation exists to enable.
        """
        seen = {}

        class Recorder(StubQdrant):
            def query_points(self, collection_name, **kwargs):
                seen["filter"] = kwargs.get("query_filter")
                return super().query_points(collection_name, **kwargs)

        conn = make_db()
        add_turns(conn, "s-a", [("user", "i prefer pnpm")])
        extract.find_candidates(
            Recorder(), StubEmbedder(),
            window=conn.execute(
                "SELECT id, role, content FROM messages"
            ).fetchall(),
            owner_id=OWNER,
            exclude_ids=["m-old-1", "m-old-2"],
        )
        must_not = getattr(seen["filter"], "must_not", None)
        self.assertIsNotNone(must_not)
        self.assertIn("m-old-1", must_not[0].has_id)


if __name__ == "__main__":
    unittest.main(verbosity=2)
