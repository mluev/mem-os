from __future__ import annotations

import os

import pytest

from memkit import outbox, reindex, store, vectors
from memkit.db import transaction
from tests.fixtures import OWNER, StubEmbedder, make_db

pytestmark = pytest.mark.skipif(
    os.environ.get("MEMKIT_QDRANT_INTEGRATION") != "1",
    reason="set MEMKIT_QDRANT_INTEGRATION=1 with Qdrant on 127.0.0.1:6333",
)


def test_real_qdrant_outbox_and_generation_switch() -> None:
    conn = make_db()
    client = vectors.get_client(os.environ.get("MEMKIT_QDRANT_TEST_URL", "http://127.0.0.1:6333"))
    for collection in list(client.get_collections().collections):
        if collection.name.startswith((vectors.MEMORIES, vectors.RAW)):
            client.delete_collection(collection_name=collection.name)
    vectors.ensure_collections(client)
    with transaction(conn):
        memory_id = store.add_memory(
            conn,
            owner_id=OWNER,
            text="Integration memory",
            kind="observation",
            source_role="user",
        )
    delivered = outbox.drain(conn, client, StubEmbedder(), limit=10)
    assert delivered.applied == 1
    assert vectors.count(client, vectors.MEMORIES) == 1
    rebuilt = reindex.rebuild(conn, client, StubEmbedder())
    assert rebuilt["memories"] == 1
    active = vectors.resolve_collection(client, vectors.MEMORIES)
    assert vectors.exact_ids(client, active) == {memory_id}
    client.close()
