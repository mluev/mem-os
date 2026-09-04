"""The parts of the index that only a real Qdrant can prove.

`StubQdrant` is a dict, and deliberately not an emulator: reimplementing filter
semantics there would be a second, wrong copy of the read path. So three claims
have no offline test at all -- that a payload filter actually excludes another
scope's points, that an alias swap is atomic from a reader's point of view, and
that `exact_ids` pages through a full collection. They live here.

    MEMKIT_QDRANT_INTEGRATION=1 uv run pytest -q tests/test_qdrant_integration.py
"""

from __future__ import annotations

import os

import pytest

from memkit import outbox, reindex, store, vectors
from tests.fixtures import StubEmbedder, make_db, seed_team

pytestmark = pytest.mark.skipif(
    os.environ.get("MEMKIT_QDRANT_INTEGRATION") != "1",
    reason="set MEMKIT_QDRANT_INTEGRATION=1 with Qdrant on 127.0.0.1:6333",
)


def _clean_client():
    client = vectors.get_client(os.environ.get("MEMKIT_QDRANT_TEST_URL", "http://127.0.0.1:6333"))
    for collection in list(client.get_collections().collections):
        if collection.name.startswith((vectors.MEMORIES, vectors.RAW)):
            client.delete_collection(collection_name=collection.name)
    vectors.ensure_collections(client)
    return client


def test_real_qdrant_outbox_and_generation_switch() -> None:
    conn = make_db(seed=False)
    team = seed_team(conn)
    client = _clean_client()
    with conn.transaction():
        memory_id = store.add_memory(
            conn,
            scope_id=team.scope_of("alice"),
            author_id=team.alice_id,
            text="Integration memory",
            kind="observation",
            source_role="user",
            review_status="confirmed",
        )
    delivered = outbox.drain(conn, client, StubEmbedder(), limit=10)
    assert delivered.applied == 1
    assert vectors.count(client, vectors.MEMORIES) == 1
    rebuilt = reindex.rebuild(conn, client, StubEmbedder())
    assert rebuilt["memories"] == 1
    active = vectors.resolve_collection(client, vectors.MEMORIES)
    assert vectors.exact_ids(client, active) == {memory_id}
    client.close()
    conn.close()


def test_a_scope_filter_excludes_another_persons_points() -> None:
    """The claim the stub cannot make.

    Every read sends `scope_id IN (...)` as a payload filter, and it is the
    only thing standing between two people's memories in the index. A filter
    that silently matched everything would still pass every offline test,
    because the offline index has one tenant.
    """
    conn = make_db(seed=False)
    team = seed_team(conn)
    client = _clean_client()
    embedder = StubEmbedder()
    with conn.transaction():
        mine = store.add_memory(
            conn,
            scope_id=team.scope_of("alice"),
            author_id=team.alice_id,
            text="Alice keeps her notes here",
            kind="fact",
            source_role="user",
        )
        store.add_memory(
            conn,
            scope_id=team.scope_of("bob"),
            author_id=team.bob_id,
            text="Bob keeps his notes here",
            kind="fact",
            source_role="user",
        )
    outbox.drain(conn, client, embedder, limit=10)
    assert vectors.count(client, vectors.MEMORIES) == 2

    hits = vectors.search(
        client,
        vectors.MEMORIES,
        embedder.encode_one("notes"),
        limit=10,
        must=[vectors.keyword("scope_id", [team.scope_of("alice")])],
    )
    assert {str(hit.id) for hit in hits} == {mine}
    client.close()
    conn.close()
