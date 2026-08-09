from __future__ import annotations

import unittest

from memkit import platform
from memkit.db import transaction
from tests.fixtures import OWNER, make_db


class TestGenericPlatform(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = make_db()
        with transaction(self.conn):
            platform.create_namespace(
                self.conn, owner_id=OWNER, name="life", description="caller-owned"
            )
            platform.create_collection(
                self.conn,
                owner_id=OWNER,
                namespace="life",
                name="items",
                schema={
                    "type": "object",
                    "properties": {"title": {"type": "string"}},
                    "required": ["title"],
                    "additionalProperties": False,
                },
            )

    def test_schema_validation_idempotency_revision_and_filter(self) -> None:
        with transaction(self.conn):
            created, duplicate = platform.create_record(
                self.conn,
                owner_id=OWNER,
                namespace="life",
                collection_name="items",
                value={"title": "Call Alice"},
                context={"area": "personal"},
                idempotency_key="source-1",
            )
        self.assertFalse(duplicate)
        with transaction(self.conn):
            same, duplicate = platform.create_record(
                self.conn,
                owner_id=OWNER,
                namespace="life",
                collection_name="items",
                value={"title": "ignored retry"},
                idempotency_key="source-1",
            )
        self.assertTrue(duplicate)
        self.assertEqual(same["id"], created["id"])

        with transaction(self.conn):
            updated = platform.update_record(
                self.conn,
                owner_id=OWNER,
                namespace="life",
                collection_name="items",
                record_id=created["id"],
                expected_revision=1,
                value={"title": "Call Bob"},
            )
        self.assertEqual(updated["revision"], 2)
        rows = platform.search_records(
            self.conn,
            owner_id=OWNER,
            namespace="life",
            collection_name="items",
            expression={"field": "value.title", "op": "eq", "value": "Call Bob"},
            limit=10,
        )
        self.assertEqual([row["id"] for row in rows], [created["id"]])

    def test_invalid_record_is_rejected(self) -> None:
        with self.assertRaises(platform.PlatformError), transaction(self.conn):
            platform.create_record(
                self.conn,
                owner_id=OWNER,
                namespace="life",
                collection_name="items",
                value={"title": 42},
            )


if __name__ == "__main__":
    unittest.main()
