"""What `apply_ops` will and will not write, given a window and a set of ops.

Two guarantees live here. The older one is evidence: a stored fact cites spans
of real messages in the window it came from, and a citation that cannot be
verified kills the operation rather than the citation. The newer one is routing:
on a team instance a fact has somewhere to go besides the speaker's own space,
and the wrong choice is either a leak or a loss, so every route is asserted --
including the refusals.
"""

from __future__ import annotations

import unittest
import uuid

from memkit import entities, extract, judge, store
from memkit.db import iso
from tests.fixtures import apply, make_db, make_session, seed_team


class ExtractionCase(unittest.TestCase):
    """A seeded team, one session, and one cited user turn to build ops against."""

    def setUp(self) -> None:
        self.conn = make_db(seed=False)
        self.team = seed_team(self.conn)
        make_session(self.conn, self.team)
        with self.conn.transaction():
            message_id, _, _ = store.add_message(
                self.conn,
                session_id="s-1",
                user_id=self.team.alice_id,
                scope_id=self.team.scope_of("alice"),
                agent_id="chat",
                role="user",
                content="I prefer pnpm",
                context={"workspace": "mem-os"},
            )
        self.message_id = message_id
        self.block = entities.for_prompt(self.conn, user_id=self.team.alice_id)
        self.entity_map = {str(index + 1): item["id"] for index, item in enumerate(self.block)}

    def tearDown(self) -> None:
        self.conn.close()

    def ref(self, name: str) -> int:
        """The number the prompt would have shown for this entity."""
        return next(index + 1 for index, item in enumerate(self.block) if item["name"] == name)

    def op(self, **changes) -> judge.Op:
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
        parsed = judge.Op.parse(raw)
        assert parsed is not None
        return parsed

    def run_ops(self, *ops: judge.Op, **kw):
        kw.setdefault("context", {"workspace": "mem-os"})
        kw.setdefault("source_message_ids", [self.message_id])
        kw.setdefault("entity_map", self.entity_map)
        with self.conn.transaction():
            return apply(self.conn, self.team, list(ops), **kw)

    def memories(self):
        return self.conn.execute("SELECT * FROM memories ORDER BY created_at").fetchall()


class EvidencePreciseExtractionTest(ExtractionCase):
    def test_exact_span_is_persisted(self) -> None:
        outcome = self.run_ops(self.op())
        self.assertEqual(outcome.added, 1)
        evidence = self.conn.execute("SELECT * FROM memory_evidence").fetchone()
        self.assertEqual((evidence["start_char"], evidence["end_char"]), (0, 13))

    def test_out_of_window_or_cross_context_evidence_is_rejected(self) -> None:
        outcome = self.run_ops(self.op(context_entries=[{"key": "workspace", "value": "other"}]))
        self.assertEqual(outcome.rejected, 1)
        self.assertEqual(self.memories(), [])

    def test_unique_verbatim_quote_repairs_model_offsets(self) -> None:
        """The model's offsets drift; its quotes do not, so the server re-derives.

        A unique verbatim span is the only case that can be repaired locally --
        an ambiguous quote stays an invalid citation.
        """
        outcome = self.run_ops(
            self.op(
                evidence=[
                    {
                        "message_id": self.message_id,
                        "start_char": 99,
                        "end_char": 100,
                        "quote": "I prefer pnpm",
                    }
                ]
            )
        )
        self.assertEqual(outcome.added, 1)
        evidence = self.conn.execute("SELECT start_char,end_char FROM memory_evidence").fetchone()
        self.assertEqual((evidence["start_char"], evidence["end_char"]), (0, 13))

    def test_update_cannot_reach_into_another_persons_scope(self) -> None:
        """Bob's private memory is not merely unwritable; it is invisible.

        Skipped rather than rejected on purpose: telling the caller their target
        exists but belongs to somebody else would make extraction an existence
        oracle for other people's facts.
        """
        with self.conn.transaction():
            foreign = store.add_memory(
                self.conn,
                scope_id=self.team.scope_of("bob"),
                author_id=self.team.bob_id,
                text="Uses npm",
                kind="preference",
                context={"workspace": "mem-os"},
                source_role="user",
            )
        outcome = self.run_ops(self.op(op="UPDATE", id=foreign, text="Uses pnpm"))
        self.assertEqual(outcome.skipped, 1)
        row = self.conn.execute("SELECT text FROM memories WHERE id=%s", (foreign,)).fetchone()
        self.assertEqual(row["text"], "Uses npm")

    def test_renamed_context_key_is_reconciled_not_dropped(self) -> None:
        """The judge renames keys it was shown verbatim; that is not scope invention.

        Measured on a mixed session: shown {"source_workspace": "shop"} the model
        answered {"workspace": "shop"} and two correct project facts were
        silently rejected.
        """
        outcome = self.run_ops(
            self.op(context_entries=[{"key": "workspace", "value": "mem-os"}]),
            context={"source_workspace": "mem-os"},
        )
        self.assertEqual((outcome.added, outcome.rejected), (1, 0))
        self.assertEqual(self.memories()[0]["context"], {"source_workspace": "mem-os"})

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
        with self.conn.transaction():
            memory_id = store.add_memory(
                self.conn,
                scope_id=self.team.scope_of("alice"),
                author_id=self.team.alice_id,
                text="Uses npm",
                kind="preference",
                context={"workspace": "mem-os"},
                source_role="user",
                valid_until="2027-01-01T00:00:00Z",
            )
        outcome = self.run_ops(
            self.op(op="UPDATE", id=memory_id, text="Uses pnpm", valid_until=None)
        )
        self.assertEqual(outcome.updated, 1)
        row = self.conn.execute(
            "SELECT text,valid_until FROM memories WHERE id=%s", (memory_id,)
        ).fetchone()
        self.assertEqual(row["text"], "Uses pnpm")
        self.assertEqual(iso(row["valid_until"]), "2027-01-01T00:00:00Z")

    def test_rejections_carry_op_and_reason(self) -> None:
        bad_evidence = self.op(evidence=[{"message_id": 999_999, "start_char": 0, "end_char": 5}])
        cross_context = self.op(context_entries=[{"key": "workspace", "value": "other"}])
        outcome = self.run_ops(bad_evidence, cross_context)
        self.assertEqual(outcome.rejected, 2)
        reasons = [entry["reason"] for entry in outcome.rejections]
        self.assertEqual(reasons, ["evidence_invalid", "context_mismatch"])
        self.assertEqual(outcome.as_dict()["rejections"], outcome.rejections)

    def test_update_cannot_cross_context_without_explicit_move(self) -> None:
        with self.conn.transaction():
            other_context = store.add_memory(
                self.conn,
                scope_id=self.team.scope_of("alice"),
                author_id=self.team.alice_id,
                text="Uses npm",
                kind="preference",
                context={"workspace": "other"},
                source_role="user",
            )
        outcome = self.run_ops(self.op(op="UPDATE", id=other_context, text="Uses pnpm"))
        self.assertEqual(outcome.rejected, 1)
        self.assertEqual(outcome.rejections[0]["reason"], "target_context_mismatch")
        row = self.conn.execute(
            "SELECT text FROM memories WHERE id=%s", (other_context,)
        ).fetchone()
        self.assertEqual(row["text"], "Uses npm")


class ReviewStatusTest(ExtractionCase):
    """Automatic writes are live but unconfirmed, and stay auditable.

    The dashboard's queue is `review_status`, not a separate table, so a bug
    that writes `confirmed` from the extractor does not surface as a crash --
    it surfaces as a queue that is silently empty.
    """

    def test_an_extraction_add_lands_pending(self) -> None:
        self.run_ops(self.op())
        self.assertEqual(self.memories()[0]["review_status"], "pending")

    def test_updating_a_confirmed_memory_returns_it_for_review(self) -> None:
        with self.conn.transaction():
            memory_id = store.add_memory(
                self.conn,
                scope_id=self.team.scope_of("alice"),
                author_id=self.team.alice_id,
                text="Uses npm",
                kind="preference",
                context={"workspace": "mem-os"},
                source_role="user",
                review_status="confirmed",
            )
        outcome = self.run_ops(self.op(op="UPDATE", id=memory_id, text="Uses pnpm"))
        self.assertEqual(outcome.updated, 1)
        row = self.conn.execute("SELECT * FROM memories WHERE id=%s", (memory_id,)).fetchone()
        self.assertEqual((row["review_status"], row["text"]), ("pending", "Uses pnpm"))
        previous = self.conn.execute(
            "SELECT text FROM memory_revisions WHERE memory_id=%s AND revision=%s",
            (memory_id, int(row["revision"]) - 1),
        ).fetchone()
        self.assertEqual(previous["text"], "Uses npm")


class RoutingTest(ExtractionCase):
    """Where a fact lands, now that the speaker's own space is not the only option.

    The model chooses by number out of the block it was shown, and every choice
    is checked here rather than trusted: a fact in the wrong scope is either
    visible to people who should not see it, or invisible to the team it was
    stated for.
    """

    def test_a_fact_about_a_teammate_becomes_a_team_fact_about_them(self) -> None:
        outcome = self.run_ops(
            self.op(text="Bob prefers dark mode", subject=self.ref("Bob Petrov"))
        )
        self.assertEqual(outcome.added, 1)
        row = self.memories()[0]
        self.assertEqual(str(row["scope_id"]), self.team.team_id)
        self.assertEqual(str(row["subject_id"]), self.team.scope_of("bob"))

    def test_a_fact_about_a_project_lands_in_that_projects_scope(self) -> None:
        outcome = self.run_ops(
            self.op(text="Mem OS stores memories in Postgres", scope=self.ref("Mem OS"))
        )
        self.assertEqual(outcome.added, 1)
        row = self.memories()[0]
        self.assertEqual(str(row["scope_id"]), self.team.project_id)
        self.assertIsNone(row["subject_id"])

    def test_a_speaker_fact_stays_private_while_a_project_is_on_the_table(self) -> None:
        """The speaker is the default, and a listed project is not gravity.

        A session working inside a project shows that project in the block every
        call. If merely being listed were enough to attract facts, everything
        anyone said at work would become team-readable.
        """
        outcome = self.run_ops(self.op(), context={"source_workspace": "mem-os"})
        self.assertEqual(outcome.added, 1)
        row = self.memories()[0]
        self.assertEqual(str(row["scope_id"]), self.team.scope_of("alice"))
        self.assertIsNone(row["subject_id"])

    def test_an_unplaceable_name_keeps_the_fact_private_and_asks_a_human(self) -> None:
        """Guessing which teammate was meant puts a claim on the wrong profile.

        So the fact is kept -- it was stated -- but unattributed and private
        until somebody says who "Дмитрий" is.
        """
        outcome = self.run_ops(self.op(text="Дмитрий ушёл в отпуск", subject_name="Дмитрий"))
        self.assertEqual((outcome.added, outcome.unresolved_mentions), (1, 1))
        row = self.memories()[0]
        self.assertEqual(str(row["scope_id"]), self.team.scope_of("alice"))
        self.assertIsNone(row["subject_id"])
        attention = self.conn.execute("SELECT * FROM needs_attention").fetchone()
        self.assertEqual(attention["kind"], "unresolved_mention")
        self.assertEqual(attention["payload"], {"name": "Дмитрий"})
        self.assertEqual(str(attention["ref_memory_id"]), str(row["id"]))

    def test_a_fabricated_entity_number_is_dropped(self) -> None:
        outcome = self.run_ops(self.op(scope=99))
        self.assertEqual(outcome.rejected, 1)
        self.assertEqual(outcome.rejections[0]["reason"], "unknown_entity")
        self.assertEqual(self.memories(), [])

    def test_a_scope_the_speaker_cannot_write_to_is_refused(self) -> None:
        """Refused, never redirected: a silently moved fact is a leak or a loss."""
        outcome = self.run_ops(self.op(scope=self.ref("Bob Petrov")))
        self.assertEqual(outcome.rejected, 1)
        self.assertEqual(outcome.rejections[0]["reason"], "scope_not_allowed")
        self.assertEqual(self.memories(), [])

    def test_a_target_in_another_scope_than_the_route_is_refused(self) -> None:
        """An UPDATE must name the scope its target actually lives in."""
        with self.conn.transaction():
            private = store.add_memory(
                self.conn,
                scope_id=self.team.scope_of("alice"),
                author_id=self.team.alice_id,
                text="Uses npm",
                kind="preference",
                context={"workspace": "mem-os"},
                source_role="user",
            )
        outcome = self.run_ops(
            self.op(op="UPDATE", id=private, text="Uses pnpm", scope=self.ref("Test Team"))
        )
        self.assertEqual(outcome.rejections[0]["reason"], "target_scope_mismatch")
        row = self.conn.execute("SELECT text FROM memories WHERE id=%s", (private,)).fetchone()
        self.assertEqual(row["text"], "Uses npm")

    def test_an_operation_against_a_vanished_target_is_skipped(self) -> None:
        """The judge only ever cites candidates, but a candidate can be deleted.

        Fabricated integers never get this far -- `judge.extract` drops any that
        fall outside the map it built -- so what reaches here is a target that
        was real when the window was assembled.
        """
        outcome = self.run_ops(self.op(op="DELETE", id=str(uuid.uuid4()), text=None, evidence=[]))
        self.assertEqual((outcome.applied, outcome.skipped), (0, 1))


if __name__ == "__main__":
    unittest.main()
