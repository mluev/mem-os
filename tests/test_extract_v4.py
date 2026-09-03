from __future__ import annotations

import unittest

from memkit import extract, judge, store
from memkit.db import ensure_owner, transaction
from tests.fixtures import OWNER, make_db, make_judge_run


class TestEvidencePreciseExtraction(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = make_db()
        with transaction(self.conn):
            message_id, _, _ = store.add_message(
                self.conn,
                session_id="s-1",
                owner_id=OWNER,
                agent_id="chat",
                role="user",
                content="I prefer pnpm",
                context={"workspace": "mem-os"},
            )
        self.message_id = message_id

    def op(self, **changes):
        raw = {
            "op": "ADD",
            "id": None,
            "text": "Prefers pnpm",
            "kind": "preference",
            "context_entries": [{"key": "workspace", "value": "mem-os"}],
            "tags": [],
            "importance": 0.8,
            "confidence": 0.9,
            "valid_until": None,
            "evidence": [{"message_id": self.message_id, "start_char": 0, "end_char": 13}],
            "reason": "direct statement",
        }
        raw.update(changes)
        return judge.Op.parse(raw)

    def test_exact_span_is_persisted(self) -> None:
        operation = self.op()
        self.assertIsNotNone(operation)
        run_id = make_judge_run(self.conn)
        with transaction(self.conn):
            outcome = extract.apply_ops(
                self.conn,
                ops=[operation],
                owner_id=OWNER,
                agent_id="chat",
                context={"workspace": "mem-os"},
                judge_run_id=run_id,
                source_message_ids=[self.message_id],
            )
        self.assertEqual(outcome.added, 1)
        evidence = self.conn.execute("SELECT * FROM memory_evidence").fetchone()
        self.assertEqual((evidence["start_char"], evidence["end_char"]), (0, 13))

    def test_out_of_window_or_cross_context_evidence_is_rejected(self) -> None:
        run_id = make_judge_run(self.conn)
        with transaction(self.conn):
            outcome = extract.apply_ops(
                self.conn,
                ops=[self.op(context_entries=[{"key": "workspace", "value": "other"}])],
                owner_id=OWNER,
                agent_id="chat",
                context={"workspace": "mem-os"},
                judge_run_id=run_id,
                source_message_ids=[self.message_id],
            )
        self.assertEqual(outcome.rejected, 1)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0], 0)

    def test_unique_verbatim_quote_repairs_model_offsets(self) -> None:
        op = self.op(
            evidence=[
                {
                    "message_id": self.message_id,
                    "start_char": 99,
                    "end_char": 100,
                    "quote": "I prefer pnpm",
                }
            ]
        )
        with transaction(self.conn):
            outcome = extract.apply_ops(
                self.conn,
                ops=[op],
                owner_id=OWNER,
                agent_id="chat",
                context={"workspace": "mem-os"},
                judge_run_id=make_judge_run(self.conn),
                source_message_ids=[self.message_id],
            )
        self.assertEqual(outcome.added, 1)
        evidence = self.conn.execute("SELECT start_char,end_char FROM memory_evidence").fetchone()
        self.assertEqual((evidence["start_char"], evidence["end_char"]), (0, 13))

    def test_update_cannot_cross_owner(self) -> None:
        ensure_owner(self.conn, "other", "other")
        with transaction(self.conn):
            foreign = store.add_memory(
                self.conn,
                owner_id="other",
                text="Uses npm",
                kind="preference",
                context={"workspace": "mem-os"},
                source_role="user",
            )
        operation = self.op(op="UPDATE", id=foreign, text="Uses pnpm")
        run_id = make_judge_run(self.conn)
        with transaction(self.conn):
            outcome = extract.apply_ops(
                self.conn,
                ops=[operation],
                owner_id=OWNER,
                agent_id="chat",
                context={"workspace": "mem-os"},
                judge_run_id=run_id,
                source_message_ids=[self.message_id],
            )
        self.assertEqual(outcome.skipped, 1)
        self.assertEqual(
            self.conn.execute("SELECT text FROM memories WHERE id=?", (foreign,)).fetchone()[0],
            "Uses npm",
        )

    def test_renamed_context_key_is_reconciled_not_dropped(self) -> None:
        """The judge renames keys it was shown verbatim; that is not scope invention.

        Measured on a mixed session: shown {"source_workspace": "shop"} the model
        answered {"workspace": "shop"} and two correct project facts were
        silently rejected.
        """
        operation = self.op(context_entries=[{"key": "workspace", "value": "mem-os"}])
        with transaction(self.conn):
            outcome = extract.apply_ops(
                self.conn,
                ops=[operation],
                owner_id=OWNER,
                agent_id="chat",
                context={"source_workspace": "mem-os"},
                judge_run_id=make_judge_run(self.conn),
                source_message_ids=[self.message_id],
            )
        self.assertEqual((outcome.added, outcome.rejected), (1, 0))
        stored = self.conn.execute("SELECT context_json FROM memories").fetchone()[0]
        self.assertEqual(stored, '{"source_workspace": "mem-os"}')

    def test_reconciliation_cannot_invent_or_guess_a_scope(self) -> None:
        session = {"source_workspace": "mem-os", "source_branch": "mem-os"}
        # Value the session does not hold: no scope to resolve to.
        self.assertIsNone(extract.reconcile_context({"workspace": "other"}, session))
        # Ambiguous: two session keys hold this value, so the intent is unknown.
        self.assertIsNone(extract.reconcile_context({"workspace": "mem-os"}, session))
        # Exact keys always pass straight through.
        self.assertEqual(
            extract.reconcile_context({"source_branch": "mem-os"}, session),
            {"source_branch": "mem-os"},
        )

    def test_update_preserves_valid_until_when_op_omits_it(self) -> None:
        with transaction(self.conn):
            memory_id = store.add_memory(
                self.conn,
                owner_id=OWNER,
                text="Uses npm",
                kind="preference",
                context={"workspace": "mem-os"},
                source_role="user",
                valid_until="2027-01-01T00:00:00Z",
            )
        operation = self.op(op="UPDATE", id=memory_id, text="Uses pnpm", valid_until=None)
        with transaction(self.conn):
            outcome = extract.apply_ops(
                self.conn,
                ops=[operation],
                owner_id=OWNER,
                agent_id="chat",
                context={"workspace": "mem-os"},
                judge_run_id=make_judge_run(self.conn),
                source_message_ids=[self.message_id],
            )
        self.assertEqual(outcome.updated, 1)
        row = self.conn.execute(
            "SELECT text,valid_until FROM memories WHERE id=?", (memory_id,)
        ).fetchone()
        self.assertEqual(row["text"], "Uses pnpm")
        self.assertEqual(row["valid_until"], "2027-01-01T00:00:00Z")

    def test_rejections_carry_op_and_reason(self) -> None:
        bad_evidence = self.op(evidence=[{"message_id": 999_999, "start_char": 0, "end_char": 5}])
        cross_context = self.op(context_entries=[{"key": "workspace", "value": "other"}])
        with transaction(self.conn):
            outcome = extract.apply_ops(
                self.conn,
                ops=[bad_evidence, cross_context],
                owner_id=OWNER,
                agent_id="chat",
                context={"workspace": "mem-os"},
                judge_run_id=make_judge_run(self.conn),
                source_message_ids=[self.message_id],
            )
        self.assertEqual(outcome.rejected, 2)
        reasons = [entry["reason"] for entry in outcome.rejections]
        self.assertEqual(reasons, ["evidence_invalid", "context_mismatch"])
        self.assertEqual(outcome.as_dict()["rejections"], outcome.rejections)

    def test_update_cannot_cross_context_without_explicit_move(self) -> None:
        with transaction(self.conn):
            other_context = store.add_memory(
                self.conn,
                owner_id=OWNER,
                text="Uses npm",
                kind="preference",
                context={"workspace": "other"},
                source_role="user",
            )
        operation = self.op(op="UPDATE", id=other_context, text="Uses pnpm")
        run_id = make_judge_run(self.conn)
        with transaction(self.conn):
            outcome = extract.apply_ops(
                self.conn,
                ops=[operation],
                owner_id=OWNER,
                agent_id="chat",
                context={"workspace": "mem-os"},
                judge_run_id=run_id,
                source_message_ids=[self.message_id],
            )
        self.assertEqual(outcome.rejected, 1)
        self.assertEqual(
            self.conn.execute("SELECT text FROM memories WHERE id=?", (other_context,)).fetchone()[
                0
            ],
            "Uses npm",
        )


if __name__ == "__main__":
    unittest.main()
