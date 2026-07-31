"""The write-time provenance guard, and what it does and does not protect.

The second test in `TestAssistantOnlySource` is the important one. It documents
in executable form that whole-window source linking makes the guard inert on the
live extraction path, so nobody reads the first test, sees it pass, and believes
the system is defended. A guard whose limits are not written down gets mistaken
for a guarantee.

See src/memkit/provenance.py for the reasoning and decisions/0006 for the call.
"""

from __future__ import annotations

import sqlite3
import unittest

from memkit import extract, judge, provenance, store
from memkit.db import SCHEMA_VERSION, connect, init_db, transaction
from tests.fixtures import (
    OWNER,
    StubEmbedder,
    StubQdrant,
    add_messages,
    apply,
    make_db,
)

ASSISTANT_TEXT = "Тебе подойдёт Pinia, она проще Vuex"


def _add_op(text=ASSISTANT_TEXT, type="preference"):
    return [judge.Op.parse({
        "op": "ADD", "text": text, "type": type, "scope": "user",
        "importance": 0.8, "confidence": 0.9, "id": None,
        "valid_until": None, "task_status": None,
        "holds_in_other_repos": True, "reason": "the assistant said so",
    })]


class TestPredicate(unittest.TestCase):
    """`may_write` on its own, with no database in the way."""

    def test_assistant_only_evidence_is_refused(self):
        self.assertFalse(provenance.may_write(op="ADD", roles={"assistant"}))
        self.assertFalse(provenance.may_write(op="UPDATE", roles={"assistant"}))

    def test_one_user_turn_is_enough(self):
        self.assertTrue(provenance.may_write(op="ADD", roles={"user", "assistant"}))
        self.assertTrue(provenance.may_write(op="ADD", roles={"user"}))

    def test_tool_output_counts_as_evidence(self):
        self.assertTrue(provenance.may_write(op="ADD", roles={"tool", "assistant"}))

    def test_empty_evidence_is_allowed(self):
        """The archived predicate `roles <= {"assistant"}` is True for set().

        Restored verbatim it refuses every write that cites nothing, which is
        most of this repo's own test suite and every manual API write. The
        authority there is the caller, and `source_role_for` labels it 'manual'.
        """
        self.assertTrue(provenance.may_write(op="ADD", roles=set()))
        self.assertTrue(set() <= {"assistant"}, "the archived predicate's bug")

    def test_delete_is_exempt(self):
        """Removing a fact injects nothing; refusing it keeps bad facts alive."""
        self.assertTrue(provenance.may_write(op="DELETE", roles={"assistant"}))


class TestLabelling(unittest.TestCase):
    def test_authority_order(self):
        self.assertEqual(provenance.source_role_for({"user", "assistant"}), "user")
        self.assertEqual(provenance.source_role_for({"tool", "assistant"}), "tool")
        self.assertEqual(provenance.source_role_for({"assistant"}), "assistant")
        self.assertEqual(provenance.source_role_for(set()), "manual")

    def test_weakest_is_not_the_reverse_of_authority(self):
        """'manual' outranks 'assistant' but not 'user', in both directions."""
        self.assertEqual(provenance.weakest({"user", "assistant"}), "assistant")
        self.assertEqual(provenance.weakest({"user", "manual"}), "manual")
        self.assertEqual(provenance.weakest({"manual", "assistant"}), "assistant")
        self.assertEqual(provenance.weakest({"user"}), "user")
        self.assertEqual(provenance.weakest(set()), "manual")

    def test_every_role_is_orderable_by_both_functions(self):
        """A role missing from either ladder would silently become 'manual'."""
        for role in provenance.ROLES:
            with self.subTest(role=role):
                self.assertEqual(provenance.source_role_for({role}), role)
                self.assertEqual(provenance.weakest({role}), role)

    def test_validate_rejects_out_of_vocabulary(self):
        self.assertEqual(provenance.validate("user"), "user")
        with self.assertRaises(ValueError):
            provenance.validate("assistnat")

    def test_the_sql_ladder_matches_the_python_one(self):
        """db.py inlines the authority order as SQL and cannot import this."""
        from memkit.db import _SOURCE_ROLE_FROM_SOURCES

        order = [
            role for role in ("user", "tool", "assistant")
            if f"'{role}'" in _SOURCE_ROLE_FROM_SOURCES
        ]
        self.assertEqual(order, list(provenance._AUTHORITY))


class TestAssistantOnlySource(unittest.TestCase):
    def setUp(self):
        self.conn = make_db()
        self.q = StubQdrant()

    def test_assistant_only_window_cannot_write(self):
        ids = add_messages(self.conn, n=3, role="assistant", content=ASSISTANT_TEXT)
        out = apply(self.conn, self.q, _add_op(), source_message_ids=ids)

        self.assertEqual((out.added, out.rejected), (0, 1))
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) n FROM memories").fetchone()["n"], 0
        )
        self.assertEqual(self.q.points, {}, "nothing may reach the index either")
        self.assertEqual(out.as_dict()["rejected"], 1, "must be reportable over HTTP")

    def test_one_user_turn_in_the_window_is_enough(self):
        """The honest limit of the guard on the live path.

        `apply_ops` links the entire window to every fact, and
        `fast_forward_to_user_turn` guarantees a user turn is present, so the
        roles are always {user, assistant} in production and the guard above
        cannot fire. This test exists so that fact is written down where someone
        reading the previous test will see it.
        """
        ids = add_messages(self.conn, n=3, role="assistant", content=ASSISTANT_TEXT)
        ids += add_messages(self.conn, n=1, role="user", content="а что для стейта?")
        out = apply(self.conn, self.q, _add_op(), source_message_ids=ids)

        self.assertEqual((out.added, out.rejected), (1, 0))
        self.assertEqual(
            self.conn.execute("SELECT source_role FROM memories").fetchone()[0],
            "user",
            "one user turn among many assistant turns still labels the fact 'user'",
        )

    def test_update_from_assistant_only_evidence_is_refused(self):
        """Confirmation is the loop, not just creation.

        Left open, the model agrees with its own stored claim, the judge emits
        UPDATE, `updated_at` moves forward, and retrieval treats the fact as
        freshly confirmed. That is the feedback path, arriving through the edit
        rather than the insert.
        """
        seeded = store.add_memory(
            self.conn, self.q, StubEmbedder(), owner_id=OWNER,
            text="Prefers Vuex for state", type="preference", source_role="user",
        )
        self.conn.commit()
        before = self.conn.execute(
            "SELECT updated_at, text FROM memories WHERE id=?", (seeded,)
        ).fetchone()

        ids = add_messages(self.conn, n=2, role="assistant", content=ASSISTANT_TEXT)
        op = judge.Op.parse({
            "op": "UPDATE", "id": seeded, "text": "Prefers Pinia for state",
            "type": "preference", "scope": "user", "importance": 0.8,
            "confidence": 0.9, "valid_until": None, "task_status": None,
            "holds_in_other_repos": True, "reason": "assistant recommended it",
        })
        out = apply(self.conn, self.q, [op], source_message_ids=ids)

        self.assertEqual((out.updated, out.rejected), (0, 1))
        after = self.conn.execute(
            "SELECT updated_at, text FROM memories WHERE id=?", (seeded,)
        ).fetchone()
        self.assertEqual(after["text"], before["text"])
        self.assertEqual(
            after["updated_at"], before["updated_at"],
            "a refused update must not refresh recency either",
        )

    def test_delete_from_assistant_only_evidence_is_allowed(self):
        seeded = store.add_memory(
            self.conn, self.q, StubEmbedder(), owner_id=OWNER,
            text="Prefers Vuex for state", type="preference", source_role="user",
        )
        self.conn.commit()
        ids = add_messages(self.conn, n=2, role="assistant", content=ASSISTANT_TEXT)
        op = judge.Op.parse({
            "op": "DELETE", "id": seeded, "text": None, "type": None,
            "scope": None, "importance": None, "confidence": None,
            "valid_until": None, "task_status": None,
            "holds_in_other_repos": None, "reason": "no longer true",
        })
        out = apply(self.conn, self.q, [op], source_message_ids=ids)

        self.assertEqual((out.deleted, out.rejected), (1, 0))
        self.assertEqual(
            self.conn.execute("SELECT status FROM memories WHERE id=?",
                              (seeded,)).fetchone()[0],
            "expired",
        )

    def test_evidence_free_write_is_labelled_manual_not_refused(self):
        """The path most of the existing suite uses: apply() with no sources."""
        out = apply(self.conn, self.q, _add_op(text="Prefers pnpm over npm"))
        self.assertEqual((out.added, out.rejected), (1, 0))
        self.assertEqual(
            self.conn.execute("SELECT source_role FROM memories").fetchone()[0],
            "manual",
        )

    def test_a_good_op_survives_a_refused_one_in_the_same_batch(self):
        """Refusal is per-operation: one bad op must not discard the others.

        And it must not abort the window, which would leave the messages
        unprocessed and re-paid for on the next message.
        """
        ids = add_messages(self.conn, n=2, role="assistant", content=ASSISTANT_TEXT)
        ops = _add_op(text="First claim from the assistant alone")
        ops += _add_op(text="Second claim from the assistant alone")
        out = apply(self.conn, self.q, ops, source_message_ids=ids)
        self.assertEqual((out.added, out.rejected), (0, 2))


class TestManualWriteLabelling(unittest.TestCase):
    def setUp(self):
        self.conn = make_db()
        self.q = StubQdrant()
        self.emb = StubEmbedder()

    def test_default_is_manual(self):
        mem_id = store.add_memory(
            self.conn, self.q, self.emb, owner_id=OWNER,
            text="Lives in Tashkent", type="fact",
        )
        self.assertEqual(
            self.conn.execute("SELECT source_role FROM memories WHERE id=?",
                              (mem_id,)).fetchone()[0],
            "manual",
        )

    def test_an_agent_can_declare_itself(self):
        """What Hermes' on_memory_write and memkit_remember now send."""
        mem_id = store.add_memory(
            self.conn, self.q, self.emb, owner_id=OWNER,
            text="Vibe OS is an open-source library of vibe-coding skills",
            type="project", importance=0.9, source_role="assistant",
        )
        self.assertEqual(
            self.conn.execute("SELECT source_role FROM memories WHERE id=?",
                              (mem_id,)).fetchone()[0],
            "assistant",
        )

    def test_an_invalid_label_is_refused_at_the_call_site(self):
        with self.assertRaises(ValueError):
            store.add_memory(
                self.conn, self.q, self.emb, owner_id=OWNER,
                text="x", type="fact", source_role="robot",
            )

    def test_the_column_is_immutable(self):
        """Provenance is not editable metadata; that is what makes it evidence."""
        from memkit import mutate

        mem_id = store.add_memory(
            self.conn, self.q, self.emb, owner_id=OWNER,
            text="Prefers pnpm", type="preference", source_role="assistant",
        )
        self.conn.commit()
        with self.assertRaises(mutate.MutationError):
            with transaction(self.conn):
                mutate.update_memory(
                    self.conn, self.q, self.emb,
                    memory_id=mem_id, changes={"source_role": "user"},
                )


class TestMigration(unittest.TestCase):
    """The rebuild, against a v2 file it did not create."""

    def _v2_database(self):
        import tempfile
        from pathlib import Path

        path = Path(tempfile.mkdtemp()) / "v2.db"
        init_db(path)
        conn = connect(path)
        # Rewind to v2 by dropping the column, which is the only honest way to
        # get a pre-migration file from the current schema script.
        conn.execute("ALTER TABLE memories DROP COLUMN source_role")
        conn.execute("PRAGMA user_version=2")
        conn.commit()
        return path, conn

    def test_backfill_derives_the_label_from_linked_messages(self):
        path, conn = self._v2_database()
        conn.execute(
            "INSERT INTO owners VALUES (?,?, '2026-01-01T00:00:00Z')", (OWNER, "t")
        )
        conn.execute(
            "INSERT INTO sessions VALUES ('s-1',?,'chat','2026-01-01T00:00:00Z',"
            "NULL,NULL)", (OWNER,)
        )
        rows = [("user", "u"), ("assistant", "a")]
        msg_ids = {}
        for role, key in rows:
            cur = conn.execute(
                "INSERT INTO messages (session_id, role, content, created_at) "
                "VALUES ('s-1',?,?, '2026-01-01T00:00:00Z')", (role, f"text {role}")
            )
            msg_ids[key] = cur.lastrowid
        for mem_id in ("from-user", "from-assistant", "no-sources"):
            conn.execute(
                """INSERT INTO memories
                   (id,owner_id,scope,type,text,importance,confidence,status,
                    valid_from,created_at,updated_at,extraction_version)
                   VALUES(?,?,'user','fact',?,.5,.9,'active',
                          '2026-01-01T00:00:00Z','2026-01-01T00:00:00Z',
                          '2026-01-01T00:00:00Z','v4')""",
                (mem_id, OWNER, mem_id),
            )
        conn.executemany(
            "INSERT INTO memory_sources VALUES (?,?)",
            [("from-user", msg_ids["u"]), ("from-user", msg_ids["a"]),
             ("from-assistant", msg_ids["a"])],
        )
        conn.commit()
        conn.close()

        init_db(path)

        migrated = connect(path)
        labels = {
            row["id"]: row["source_role"]
            for row in migrated.execute("SELECT id, source_role FROM memories")
        }
        self.assertEqual(labels, {
            "from-user": "user",
            "from-assistant": "assistant",
            "no-sources": "manual",
        })
        self.assertEqual(
            migrated.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION
        )

    def test_the_rebuild_preserves_the_task_board(self):
        """task_board cascades on memories(id): the DROP must not take it out."""
        path, conn = self._v2_database()
        conn.execute(
            "INSERT INTO owners VALUES (?,?, '2026-01-01T00:00:00Z')", (OWNER, "t")
        )
        conn.execute(
            """INSERT INTO memories
               (id,owner_id,scope,type,text,importance,confidence,status,
                valid_from,created_at,updated_at,extraction_version)
               VALUES('t1',?,'user','task','A task',.5,.9,'active',
                      '2026-01-01T00:00:00Z','2026-01-01T00:00:00Z',
                      '2026-01-01T00:00:00Z','v4')""",
            (OWNER,),
        )
        conn.execute(
            """INSERT INTO task_board
               (memory_id,workflow_status,project_key,position,version,
                created_at,updated_at)
               VALUES('t1','doing','memkit',1024.0,3,
                      '2026-01-01T00:00:00Z','2026-01-01T00:00:00Z')"""
        )
        conn.commit()
        conn.close()

        init_db(path)

        migrated = connect(path)
        board = migrated.execute("SELECT * FROM task_board").fetchall()
        self.assertEqual(len(board), 1, "the kanban board was cascade-deleted")
        self.assertEqual(board[0]["workflow_status"], "doing")
        self.assertEqual(board[0]["version"], 3, "board version must not reset")
        self.assertEqual(
            migrated.execute("PRAGMA foreign_key_check").fetchall(), []
        )

    def test_the_rebuild_preserves_the_supersession_chain(self):
        path, conn = self._v2_database()
        conn.execute(
            "INSERT INTO owners VALUES (?,?, '2026-01-01T00:00:00Z')", (OWNER, "t")
        )
        for mem_id, status, successor in (
            ("new", "active", None), ("old", "superseded", "new")
        ):
            conn.execute(
                """INSERT INTO memories
                   (id,owner_id,scope,type,text,importance,confidence,status,
                    superseded_by,valid_from,created_at,updated_at,
                    extraction_version)
                   VALUES(?,?,'user','fact',?,.5,.9,?,?,
                          '2026-01-01T00:00:00Z','2026-01-01T00:00:00Z',
                          '2026-01-01T00:00:00Z','v4')""",
                (mem_id, OWNER, mem_id, status, successor),
            )
        conn.commit()
        conn.close()

        init_db(path)

        migrated = connect(path)
        self.assertEqual(
            migrated.execute(
                "SELECT superseded_by FROM memories WHERE id='old'"
            ).fetchone()[0],
            "new",
        )
        self.assertEqual(
            migrated.execute("PRAGMA foreign_key_check").fetchall(), []
        )

    def test_running_init_db_twice_is_a_no_op(self):
        path, conn = self._v2_database()
        conn.close()
        init_db(path)
        first = connect(path).execute("PRAGMA table_info(memories)").fetchall()
        init_db(path)
        second = connect(path).execute("PRAGMA table_info(memories)").fetchall()
        self.assertEqual([r["name"] for r in first], [r["name"] for r in second])

    def test_a_newer_database_is_refused(self):
        import tempfile
        from pathlib import Path

        path = Path(tempfile.mkdtemp()) / "future.db"
        init_db(path)
        conn = connect(path)
        conn.execute(f"PRAGMA user_version={SCHEMA_VERSION + 1}")
        conn.commit()
        conn.close()
        with self.assertRaises(RuntimeError):
            init_db(path)


class TestSchemaGuards(unittest.TestCase):
    def setUp(self):
        self.conn = make_db()

    def test_the_column_has_no_default(self):
        """A default would label a forgotten insert as something a human typed."""
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                """INSERT INTO memories
                   (id,owner_id,scope,type,text,importance,confidence,status,
                    valid_from,created_at,updated_at,extraction_version)
                   VALUES('x',?,'user','fact','t',.5,.9,'active',
                          '2026-01-01T00:00:00Z','2026-01-01T00:00:00Z',
                          '2026-01-01T00:00:00Z','v6')""",
                (OWNER,),
            )

    def test_the_check_constraint_rejects_an_unknown_role(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                """INSERT INTO memories
                   (id,owner_id,scope,type,text,importance,confidence,status,
                    valid_from,created_at,updated_at,extraction_version,
                    source_role)
                   VALUES('x',?,'user','fact','t',.5,.9,'active',
                          '2026-01-01T00:00:00Z','2026-01-01T00:00:00Z',
                          '2026-01-01T00:00:00Z','v6','robot')""",
                (OWNER,),
            )

    def test_every_vocabulary_value_is_accepted(self):
        for index, role in enumerate(provenance.ROLES):
            with self.subTest(role=role):
                self.conn.execute(
                    """INSERT INTO memories
                       (id,owner_id,scope,type,text,importance,confidence,status,
                        valid_from,created_at,updated_at,extraction_version,
                        source_role)
                       VALUES(?,?,'user','fact','t',.5,.9,'active',
                              '2026-01-01T00:00:00Z','2026-01-01T00:00:00Z',
                              '2026-01-01T00:00:00Z','v6',?)""",
                    (f"m{index}", OWNER, role),
                )


class TestConsolidationInheritance(unittest.TestCase):
    """A merge must not launder assistant text into a user-sourced fact."""

    def test_the_survivor_takes_the_weakest_label(self):
        from memkit import consolidate

        conn = make_db()
        q, emb = StubQdrant(), StubEmbedder()
        ids = [
            store.add_memory(conn, q, emb, owner_id=OWNER, type="fact",
                             text=f"Claim {i}", source_role=role)
            for i, role in enumerate(("user", "assistant"))
        ]
        conn.commit()
        cluster = conn.execute(
            f"""SELECT id, type, text, importance, updated_at, source_role
                  FROM memories WHERE id IN ({",".join("?" * len(ids))})
                 ORDER BY updated_at DESC""",
            ids,
        ).fetchall()

        merge = consolidate.Merge(
            ids=[r["id"] for r in cluster],
            type="fact",
            texts=[r["text"] for r in cluster],
            text="Merged claim",
            importance=0.7,
        )
        with transaction(conn):
            survivor = consolidate._apply_merge(
                conn, q, emb, cluster=cluster, merge=merge, owner_id=OWNER
            )
        self.assertEqual(
            conn.execute("SELECT source_role FROM memories WHERE id=?",
                         (survivor,)).fetchone()[0],
            "assistant",
        )


class TestExtractionOutcomeReporting(unittest.TestCase):
    def test_rejected_is_reported_and_not_counted_as_applied(self):
        out = extract.ExtractionOutcome(added=1, rejected=2)
        self.assertEqual(out.applied, 1)
        self.assertEqual(out.as_dict()["rejected"], 2)


if __name__ == "__main__":
    unittest.main()
