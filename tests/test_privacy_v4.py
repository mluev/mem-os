"""Export and erasure once a row belongs to a scope rather than to a person.

The single-owner versions of these took everything in the database, because
everything in it was one person's. On a team the same request has three
different answers, and the line between them is the whole point: a user's
private scope is theirs, what they wrote into a shared scope is their words but
the team's record, and what a teammate wrote there is not theirs at all.

Export returns the first two. Erasure takes only the first and refuses outright
while the second exists, because deleting a colleague's citation of a decision
because its author left is not privacy, it is data loss for other people.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import mkdtemp

from memkit import entities, outbox, privacy, store, vectors
from memkit.db import transaction
from tests.fixtures import StubEmbedder, seed_team
from tests.fixtures import make_db as make_conn
from tests.test_verification_regressions import FilterAwareQdrant


class PrivacyTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = make_conn(seed=False)
        self.team = seed_team(self.conn)
        self.alice_scope = self.team.scope_of("alice")
        self.bob_scope = self.team.scope_of("bob")
        self.qdrant = FilterAwareQdrant()
        self.embedder = StubEmbedder()
        self.export_dir = Path(mkdtemp(prefix="memkit-export-test-"))

    def add_memory(self, *, text: str, scope: str, who: str = "alice", **kw) -> str:
        author = self.team.alice_id if who == "alice" else self.team.bob_id
        with transaction(self.conn):
            return store.add_memory(
                self.conn,
                scope_id=scope,
                author_id=author,
                text=text,
                kind=kw.pop("kind", "preference"),
                source_role="manual",
                **kw,
            )

    def add_message(self, *, content: str, who: str = "alice") -> int:
        user_id = self.team.alice_id if who == "alice" else self.team.bob_id
        scope = self.alice_scope if who == "alice" else self.bob_scope
        with transaction(self.conn):
            message_id, _, _ = store.add_message(
                self.conn,
                session_id=f"privacy-{who}",
                user_id=user_id,
                scope_id=scope,
                agent_id="chat",
                role="user",
                content=content,
            )
        return message_id

    def export(self, who: str = "alice") -> dict:
        result = privacy.export_user(
            self.conn,
            user_id=self.team.alice_id if who == "alice" else self.team.bob_id,
            export_dir=self.export_dir,
            private_scope_id=self.alice_scope if who == "alice" else self.bob_scope,
        )
        return json.loads(Path(result["path"]).read_text(encoding="utf-8"))


class ExportTest(PrivacyTestCase):
    def test_an_export_carries_the_users_own_history_and_no_credential(self) -> None:
        """A portability request must be answerable without handing out a key.

        Password and API-key hashes are still credentials: the archive lands in
        a downloads folder, and an offline attack on it is an attack on the
        account.
        """
        self.add_message(content="A durable evidence event long enough to index")
        memory_id = self.add_memory(text="Prefers local storage", scope=self.alice_scope)

        payload = self.export()

        self.assertEqual(payload["format"], privacy.EXPORT_FORMAT)
        self.assertEqual([row["id"] for row in payload["memories"]], [memory_id])
        self.assertEqual(payload["memory_revisions"][0]["memory_id"], memory_id)
        self.assertTrue(payload["messages"])
        self.assertTrue(payload["sessions"])
        self.assertTrue(payload["api_keys"])
        self.assertNotIn("password_hash", payload["user"])
        self.assertNotIn("key_hash", payload["api_keys"][0])

    def test_an_export_carries_what_the_user_wrote_into_a_shared_scope(self) -> None:
        """Their words in the team's record are still their contribution."""
        shared = self.add_memory(text="We always squash-merge", scope=self.team.team_id)
        self.assertIn(shared, [row["id"] for row in self.export()["memories"]])

    def test_an_export_stops_at_a_teammates_contribution(self) -> None:
        """Otherwise a portability request becomes a dump of a shared scope.

        Alice and Bob share the team scope, so an export keyed on "everything
        visible" would hand Alice everything Bob ever wrote there.
        """
        self.add_memory(text="Bob decided to ship on Fridays", scope=self.team.team_id, who="bob")
        mine = self.add_memory(text="Prefers local storage", scope=self.alice_scope)
        self.assertEqual([row["id"] for row in self.export()["memories"]], [mine])

    def test_the_export_file_is_readable_only_by_its_owner(self) -> None:
        """It holds a person's whole history and is written to a shared disk."""
        self.add_memory(text="Prefers local storage", scope=self.alice_scope)
        result = privacy.export_user(
            self.conn,
            user_id=self.team.alice_id,
            export_dir=self.export_dir,
            private_scope_id=self.alice_scope,
        )
        self.assertEqual(Path(result["path"]).stat().st_mode & 0o777, 0o600)


class ErasureTest(PrivacyTestCase):
    def test_erasure_removes_private_memory_evidence_and_credentials(self) -> None:
        """Raw evidence is retained against prompt rewrites, not against erasure.

        The derived index goes with it in the same call: a memory deleted from
        Postgres and left in Qdrant is still retrievable, which is the failure
        that makes an erasure claim untrue.
        """
        message_id = self.add_message(content="A durable evidence event long enough to index")
        memory_id = self.add_memory(text="Prefers local storage", scope=self.alice_scope)
        outbox.drain(self.conn, self.qdrant, self.embedder, limit=100)
        self.assertIn(memory_id, self.qdrant.points)
        self.assertIn(str(message_id), self.qdrant.raw_points)

        counts = privacy.erase_user(
            self.conn,
            self.qdrant,
            user_id=self.team.alice_id,
            private_scope_id=self.alice_scope,
        )

        self.assertEqual(counts["memories"], 1)
        self.assertEqual(counts["messages"], 1)
        self.assertNotIn(memory_id, self.qdrant.points)
        self.assertNotIn(str(message_id), self.qdrant.raw_points)
        for table in ("messages", "sessions", "api_keys", "auth_sessions", "judge_runs"):
            self.assertEqual(
                self.conn.execute(
                    f"SELECT COUNT(*) AS n FROM {table} WHERE user_id=%s", (self.team.alice_id,)
                ).fetchone()["n"],
                0,
                table,
            )
        self.assertEqual(self.conn.execute("SELECT COUNT(*) AS n FROM memories").fetchone()["n"], 0)
        # Bob is untouched: erasure is per user, not per instance.
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) AS n FROM api_keys WHERE user_id=%s", (self.team.bob_id,)
            ).fetchone()["n"],
            1,
        )
        self.assertIsNone(entities.own_entity(self.conn, self.team.alice_id))
        self.assertIsNone(
            self.conn.execute("SELECT id FROM users WHERE id=%s", (self.team.alice_id,)).fetchone()
        )

    def test_erasure_leaves_no_undelivered_work_for_the_rows_it_removed(self) -> None:
        """A queued upsert outliving its memory is a vector that comes back."""
        self.add_message(content="A durable evidence event long enough to index")
        self.add_memory(text="Prefers local storage", scope=self.alice_scope)

        privacy.erase_user(
            self.conn,
            self.qdrant,
            user_id=self.team.alice_id,
            private_scope_id=self.alice_scope,
        )

        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) AS n FROM index_outbox").fetchone()["n"], 0
        )

    def test_erasure_refuses_while_the_user_authored_the_teams_record(self) -> None:
        """The refusal names the count and the scopes rather than cascading.

        `memories.author_id` has no cascade, so the delete would fail on the
        constraint anyway -- but the point is the decision, not the constraint.
        Reassigning or deleting those facts is somebody's call to make.
        """
        self.add_memory(text="We always squash-merge", scope=self.team.team_id)
        with self.assertRaises(ValueError) as raised:
            privacy.erase_user(
                self.conn,
                self.qdrant,
                user_id=self.team.alice_id,
                private_scope_id=self.alice_scope,
            )
        self.assertIn("test-team", str(raised.exception))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) AS n FROM memories").fetchone()["n"], 1)

    def test_a_teammates_note_survives_with_its_reference_to_the_person_dropped(self) -> None:
        """Bob's record of Alice is Bob's, but it stops naming a person who left."""
        note = self.add_memory(
            text="Alice owns the retrieval policy",
            scope=self.team.team_id,
            who="bob",
            subject_id=self.alice_scope,
        )

        privacy.erase_user(
            self.conn,
            self.qdrant,
            user_id=self.team.alice_id,
            private_scope_id=self.alice_scope,
        )

        row = self.conn.execute("SELECT * FROM memories WHERE id=%s", (note,)).fetchone()
        self.assertIsNotNone(row)
        self.assertIsNone(row["subject_id"])

    def test_erasure_drops_a_citation_whose_message_is_gone(self) -> None:
        """A surviving memory must not point into an excerpt that no longer exists."""
        message_id = self.add_message(content="A durable evidence event long enough to index")
        note = self.add_memory(
            text="Alice prefers squash merges", scope=self.team.team_id, who="bob"
        )
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO memory_sources(memory_id,message_id) VALUES (%s,%s)",
                (note, message_id),
            )

        counts = privacy.erase_user(
            self.conn,
            self.qdrant,
            user_id=self.team.alice_id,
            private_scope_id=self.alice_scope,
        )

        self.assertEqual(counts["orphaned_citations"], 1)
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) AS n FROM memory_sources").fetchone()["n"], 0
        )
        self.assertIsNotNone(
            self.conn.execute("SELECT id FROM memories WHERE id=%s", (note,)).fetchone()
        )


class VectorCollectionsTest(PrivacyTestCase):
    def test_erasure_clears_both_derived_collections(self) -> None:
        """Memories and retained turns are separate indexes and both are the user's."""
        self.add_message(content="A durable evidence event long enough to index")
        self.add_memory(text="Prefers local storage", scope=self.alice_scope)
        outbox.drain(self.conn, self.qdrant, self.embedder, limit=100)
        self.assertTrue(self.qdrant._store[vectors.MEMORIES])
        self.assertTrue(self.qdrant._store[vectors.RAW])

        privacy.erase_user(
            self.conn,
            self.qdrant,
            user_id=self.team.alice_id,
            private_scope_id=self.alice_scope,
        )

        self.assertFalse(self.qdrant._store[vectors.MEMORIES])
        self.assertFalse(self.qdrant._store[vectors.RAW])


if __name__ == "__main__":
    unittest.main()
