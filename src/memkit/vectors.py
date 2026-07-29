"""Qdrant access. A derived index -- everything here is rebuildable from SQLite.

Two collections, not one:

``memories``
    Extracted facts. Exactly one point per active ``memories`` row, which is the
    invariant ``POST /v1/admin/reindex`` restores.

``raw``
    Indexed raw user turns. This exists only so stage 1 has a working semantic
    search, and a baseline number to judge whether the stage-2 extractor helps
    at all. docs/06-roadmap.md puts raw messages in the same collection as
    facts, which would break the one-point-per-fact invariant the data model
    depends on; keeping them apart costs one collection and preserves it.

Both declare a ``bm25`` sparse slot up front. Qdrant cannot add a named vector
to an existing collection, so a slot left undeclared means a full reindex later
just to try hybrid search.
"""

from __future__ import annotations

import logging
from typing import Any

from qdrant_client import QdrantClient, models

from .embed import DIM

logger = logging.getLogger(__name__)

MEMORIES = "memories"
RAW = "raw"

# Filterable payload fields. Without an index Qdrant filters by full scan.
_INDEXES: dict[str, list[str]] = {
    MEMORIES: [
        "owner_id", "agent_id", "scope", "scope_key", "type", "status",
        "task_status",
    ],
    RAW: ["owner_id", "agent_id", "project", "role", "session_id"],
}


def get_client(url: str) -> QdrantClient:
    return QdrantClient(url=url, timeout=30)


def ensure_collections(client: QdrantClient) -> None:
    """Create both collections and their payload indexes, idempotently."""
    existing = {c.name for c in client.get_collections().collections}
    for name in (MEMORIES, RAW):
        if name not in existing:
            client.create_collection(
                collection_name=name,
                vectors_config={
                    "dense": models.VectorParams(
                        size=DIM, distance=models.Distance.COSINE
                    )
                },
                sparse_vectors_config={"bm25": models.SparseVectorParams()},
            )
            logger.info("created collection %s", name)
        for field in _INDEXES[name]:
            try:
                client.create_payload_index(
                    collection_name=name,
                    field_name=field,
                    field_schema=models.PayloadSchemaType.KEYWORD,
                )
            except Exception:
                # Already indexed. Qdrant has no create-if-missing for indexes.
                pass


def upsert(
    client: QdrantClient,
    collection: str,
    points: list[tuple[str | int, list[float], dict[str, Any]]],
) -> None:
    if not points:
        return
    client.upsert(
        collection_name=collection,
        points=[
            models.PointStruct(id=pid, vector={"dense": vec}, payload=payload)
            for pid, vec, payload in points
        ],
        wait=True,
    )


def set_payload(
    client: QdrantClient,
    collection: str,
    point_ids: list[str | int],
    payload: dict[str, Any],
) -> None:
    """Update metadata without re-embedding unchanged text."""
    if not point_ids or not payload:
        return
    client.set_payload(
        collection_name=collection,
        points=point_ids,
        payload=payload,
        wait=True,
    )


def delete_points(
    client: QdrantClient, collection: str, point_ids: list[str | int]
) -> None:
    if not point_ids:
        return
    client.delete(
        collection_name=collection,
        points_selector=point_ids,
        wait=True,
    )


def search(
    client: QdrantClient,
    collection: str,
    vector: list[float],
    limit: int,
    must: list[models.FieldCondition] | None = None,
    with_vectors: bool = False,
) -> list[models.ScoredPoint]:
    """Dense search.

    ``with_vectors`` matters for the stage-3 read path: docs/05-retrieval.md
    assumes result vectors are already in hand for the dedup pass, but Qdrant
    omits them unless they are explicitly requested.
    """
    return client.query_points(
        collection_name=collection,
        query=vector,
        using="dense",
        limit=limit,
        query_filter=models.Filter(must=must) if must else None,
        with_payload=True,
        with_vectors=with_vectors,
    ).points


def keyword(field: str, value: str | list[str]) -> models.FieldCondition:
    if isinstance(value, list):
        return models.FieldCondition(key=field, match=models.MatchAny(any=value))
    return models.FieldCondition(key=field, match=models.MatchValue(value=value))


def drop_collection(client: QdrantClient, collection: str) -> None:
    try:
        client.delete_collection(collection_name=collection)
    except Exception:
        pass


def count(client: QdrantClient, collection: str) -> int:
    try:
        return client.count(collection_name=collection, exact=True).count
    except Exception:
        return 0
