"""Generation rebuild: build beside the live index, validate, then swap.

The index is derived, so rebuilding it must never be able to make search worse
than it was a moment ago. Three things enforce that. Each generation is written
to a fresh collection while the old one keeps serving; the id set of the finished
generation is compared against the id set Postgres says should be there, and a
mismatch aborts; and only then does one advisory-locked alias swap make it live.
A failure or a cancellation therefore leaves the previous alias exactly where it
was, pointing at a collection nothing deleted.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from memkit import reindex, store, vectors
from tests.fixtures import StubEmbedder, StubQdrant, make_db, make_session, seed_team


class AliasQdrant(StubQdrant):
    """StubQdrant that resolves aliases, so the swap is observable."""

    def __init__(self) -> None:
        super().__init__()
        self.aliases: dict[str, str] = {}

    def get_aliases(self):
        return SimpleNamespace(
            aliases=[
                SimpleNamespace(alias_name=alias, collection_name=collection)
                for alias, collection in self.aliases.items()
            ]
        )

    def _col(self, name: str):
        return super()._col(self.aliases.get(name, name))

    def update_collection_aliases(self, change_aliases_operations):
        for operation in change_aliases_operations:
            if getattr(operation, "delete_alias", None):
                self.aliases.pop(operation.delete_alias.alias_name, None)
            if getattr(operation, "create_alias", None):
                self.aliases[operation.create_alias.alias_name] = (
                    operation.create_alias.collection_name
                )


class GenerationReindexTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = make_db(seed=False)
        self.team = seed_team(self.conn)
        make_session(self.conn, self.team)
        self.caller = self.team.principal("alice")
        self.embedder = StubEmbedder()

    def tearDown(self) -> None:
        self.conn.close()

    def _add(self, text: str, **kw) -> str:
        with self.conn.transaction():
            return store.add_memory(
                self.conn,
                scope_id=kw.pop("scope_id", self.caller.own_entity_id),
                author_id=kw.pop("author_id", self.team.alice_id),
                text=text,
                kind=kw.pop("kind", "preference"),
                source_role=kw.pop("source_role", "user"),
                **kw,
            )

    def _live(self, client: AliasQdrant, collection: str = vectors.MEMORIES) -> dict:
        return client._store[client.aliases[vectors.live_alias(collection)]]

    def test_a_validated_generation_goes_live_without_deleting_the_old_one(self) -> None:
        """Rollback is only free while the previous collection still exists."""
        client = AliasQdrant()
        client.points["stale"] = {"text": "stale"}
        memory_id = self._add("Prefers pnpm")

        result = reindex.rebuild(self.conn, client, self.embedder)

        self.assertEqual(set(self._live(client)), {memory_id})
        self.assertIn("stale", client.points)
        self.assertEqual(result["memories"], 1)
        self.assertTrue(result["activated"])

    def test_the_rebuilt_payload_carries_the_authorization_columns(self) -> None:
        """The dense arm filters on `scope_id`, so a payload without it is blind.

        `subject_id`, `author_id` and `review_status` are the fields that let a
        search answer "about Bob" or "written by Bob" without a second trip
        through Postgres; a rebuild that dropped them would degrade silently.
        """
        client = AliasQdrant()
        memory_id = self._add(
            "Bob owns the deploy pipeline",
            scope_id=self.team.team_id,
            subject_id=self.team.scope_of("bob"),
            review_status="confirmed",
        )
        reindex.rebuild(self.conn, client, self.embedder)

        payload = self._live(client)[memory_id]
        self.assertEqual(payload["scope_id"], self.team.team_id)
        self.assertEqual(payload["subject_id"], self.team.scope_of("bob"))
        self.assertEqual(payload["author_id"], self.team.alice_id)
        self.assertEqual(payload["review_status"], "confirmed")
        self.assertEqual(payload["status"], "active")

    def test_raw_turns_are_rebuilt_into_their_own_collection(self) -> None:
        """Facts and raw turns share an index only if the invariant is dropped."""
        client = AliasQdrant()
        self._add("Prefers pnpm")
        with self.conn.transaction():
            message_id, _, _ = store.add_message(
                self.conn,
                session_id="s-1",
                user_id=self.team.alice_id,
                scope_id=self.caller.own_entity_id,
                agent_id="chat",
                role="user",
                content="I would rather we kept using pnpm on this project",
            )

        result = reindex.rebuild(self.conn, client, self.embedder)

        self.assertEqual(result["raw"], 1)
        self.assertEqual(set(self._live(client, vectors.RAW)), {str(message_id)})

    def test_an_inactive_memory_is_left_out_of_the_generation(self) -> None:
        """One point per retrievable fact is the invariant a rebuild restores."""
        client = AliasQdrant()
        live = self._add("Prefers pnpm")
        archived = self._add("Used to prefer yarn")
        with self.conn.transaction():
            store.set_memory_status(
                self.conn,
                memory_id=archived,
                scopes=self.caller.scopes(),
                status="archived",
            )
        reindex.rebuild(self.conn, client, self.embedder)
        self.assertEqual(set(self._live(client)), {live})

    def test_a_generation_that_fails_validation_never_becomes_live(self) -> None:
        class DroppingQdrant(AliasQdrant):
            def upsert(self, collection_name, points, wait=True):
                if "__g" not in collection_name:
                    super().upsert(collection_name, points, wait=wait)

        client = DroppingQdrant()
        client.aliases[vectors.live_alias(vectors.MEMORIES)] = vectors.MEMORIES
        client.points["old"] = {"text": "old generation"}
        self._add("New authoritative memory", kind="observation")

        with self.assertRaises(reindex.ReindexError):
            reindex.rebuild(self.conn, client, self.embedder)

        self.assertEqual(client.aliases[vectors.live_alias(vectors.MEMORIES)], vectors.MEMORIES)
        self.assertIn("old", client.points)

    def test_cancellation_before_activation_keeps_the_old_alias(self) -> None:
        client = AliasQdrant()
        client.aliases[vectors.live_alias(vectors.MEMORIES)] = vectors.MEMORIES
        with self.assertRaises(reindex.ReindexCancelled):
            reindex.rebuild(self.conn, client, self.embedder, cancelled=lambda: True)
        self.assertEqual(client.aliases[vectors.live_alias(vectors.MEMORIES)], vectors.MEMORIES)

    def test_a_dry_build_reports_its_generation_without_swapping(self) -> None:
        """`activate=False` is how an operator inspects a generation first."""
        client = AliasQdrant()
        client.aliases[vectors.live_alias(vectors.MEMORIES)] = vectors.MEMORIES
        self._add("Prefers pnpm")

        result = reindex.rebuild(self.conn, client, self.embedder, activate=False)

        self.assertFalse(result["activated"])
        self.assertEqual(result["memories"], 1)
        self.assertEqual(client.aliases[vectors.live_alias(vectors.MEMORIES)], vectors.MEMORIES)


if __name__ == "__main__":
    unittest.main()
