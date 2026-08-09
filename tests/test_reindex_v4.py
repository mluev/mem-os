from __future__ import annotations

import unittest
from types import SimpleNamespace

from memkit import reindex, store, vectors
from memkit.db import transaction
from tests.fixtures import OWNER, StubEmbedder, StubQdrant, make_db


class AliasQdrant(StubQdrant):
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


class TestGenerationReindex(unittest.TestCase):
    def test_validates_and_switches_without_deleting_old_collection(self) -> None:
        conn = make_db()
        client = AliasQdrant()
        embedder = StubEmbedder()
        client.points["stale"] = {"text": "stale"}
        with transaction(conn):
            memory_id = store.add_memory(
                conn,
                owner_id=OWNER,
                text="Prefers pnpm",
                kind="preference",
                source_role="user",
            )
        result = reindex.rebuild(conn, client, embedder)
        active = client.aliases[vectors.live_alias(vectors.MEMORIES)]
        self.assertEqual(set(client._store[active]), {memory_id})
        self.assertIn("stale", client.points)
        self.assertEqual(result["memories"], 1)

    def test_validation_failure_keeps_the_old_alias_active(self) -> None:
        conn = make_db()

        class DroppingQdrant(AliasQdrant):
            def upsert(self, collection_name, points, wait=True):
                if "__g" not in collection_name:
                    super().upsert(collection_name, points, wait=wait)

        client = DroppingQdrant()
        client.aliases[vectors.live_alias(vectors.MEMORIES)] = vectors.MEMORIES
        client.points["old"] = {"text": "old generation"}
        with transaction(conn):
            store.add_memory(
                conn,
                owner_id=OWNER,
                text="New authoritative memory",
                kind="observation",
                source_role="user",
            )
        with self.assertRaises(reindex.ReindexError):
            reindex.rebuild(conn, client, StubEmbedder())
        self.assertEqual(client.aliases[vectors.live_alias(vectors.MEMORIES)], vectors.MEMORIES)
        self.assertIn("old", client.points)

    def test_cancellation_before_activation_keeps_old_alias(self) -> None:
        conn = make_db()
        client = AliasQdrant()
        client.aliases[vectors.live_alias(vectors.MEMORIES)] = vectors.MEMORIES
        with self.assertRaises(reindex.ReindexCancelled):
            reindex.rebuild(conn, client, StubEmbedder(), cancelled=lambda: True)
        self.assertEqual(client.aliases[vectors.live_alias(vectors.MEMORIES)], vectors.MEMORIES)


if __name__ == "__main__":
    unittest.main()
