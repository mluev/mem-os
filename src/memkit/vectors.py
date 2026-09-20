"""Qdrant access. A derived index -- everything here is rebuildable from Postgres.

Two collections, not one:

``memories``
    Extracted facts. Exactly one point per active ``memories`` row, which is the
    invariant ``POST /v1/admin/reindex`` restores.

``raw``
    Indexed raw user turns. This exists only so stage 1 has a working semantic
    search, and a baseline number to judge whether the stage-2 extractor helps
    at all. Putting raw turns in the same collection as facts would break the
    one-point-per-fact invariant the read path depends on; keeping them apart
    costs one collection and preserves it. See decisions/0019.

Both declare a ``bm25`` sparse slot up front. Qdrant cannot add a named vector
to an existing collection, so a slot left undeclared means a full reindex later
just to try hybrid search.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any

from qdrant_client import QdrantClient, models

from .embed import DIM

logger = logging.getLogger(__name__)

MEMORIES = "memories"
RAW = "raw"

# Filterable payload fields. Without an index Qdrant filters by full scan.
# `scope_id` is the authorization boundary, so it is the one field every search
# filters on; `subject_id` and `author_id` support "facts about X" and "written
# by X" without a second round trip through Postgres.
_INDEXES: dict[str, list[str]] = {
    MEMORIES: [
        "scope_id",
        "subject_id",
        "author_id",
        "agent_id",
        "kind",
        "status",
        "source_role",
        "review_status",
        "valid_until",
    ],
    RAW: ["user_id", "scope_id", "agent_id", "role", "session_id"],
}


def get_client(url: str) -> QdrantClient:
    return QdrantClient(url=url, timeout=30)


def ensure_collections(client: QdrantClient) -> None:
    """Create both collections and their payload indexes, idempotently."""
    existing = {c.name for c in client.get_collections().collections}
    for name in (MEMORIES, RAW):
        if name not in existing and not _alias_exists(client, live_alias(name)):
            client.create_collection(
                collection_name=name,
                vectors_config={
                    "dense": models.VectorParams(size=DIM, distance=models.Distance.COSINE)
                },
                sparse_vectors_config={"bm25": models.SparseVectorParams()},
            )
            logger.info("created collection %s", name)
        target = resolve_collection(client, name)
        for field in _INDEXES[name]:
            client.create_payload_index(
                collection_name=target,
                field_name=field,
                field_schema=models.PayloadSchemaType.KEYWORD,
            )


def upsert(
    client: QdrantClient,
    collection: str,
    points: list[tuple[str | int, list[float], dict[str, Any]]],
) -> None:
    if not points:
        return
    client.upsert(
        collection_name=resolve_collection(client, collection),
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
        collection_name=resolve_collection(client, collection),
        points=point_ids,
        payload=payload,
        wait=True,
    )


def delete_points(client: QdrantClient, collection: str, point_ids: list[str | int]) -> None:
    if not point_ids:
        return
    client.delete(
        collection_name=resolve_collection(client, collection),
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
    exclude_ids: list[str] | None = None,
) -> list[models.ScoredPoint]:
    """Dense search.

    ``with_vectors`` matters for the stage-3 read path: docs/05-retrieval.md
    assumes result vectors are already in hand for the dedup pass, but Qdrant
    omits them unless they are explicitly requested.

    ``exclude_ids`` is for re-extraction: the candidate block must not offer the
    judge the very facts being replaced, or it emits UPDATE against them instead
    of producing the fresh set the operation exists to create.
    """
    flt = None
    if must or exclude_ids:
        flt = models.Filter(
            must=must or None,
            must_not=[models.HasIdCondition(has_id=list(exclude_ids))] if exclude_ids else None,
        )
    return client.query_points(
        collection_name=resolve_collection(client, collection),
        query=vector,
        using="dense",
        limit=limit,
        query_filter=flt,
        with_payload=True,
        with_vectors=with_vectors,
    ).points


def keyword(field: str, value: str | list[str]) -> models.FieldCondition:
    if isinstance(value, list):
        return models.FieldCondition(key=field, match=models.MatchAny(any=value))
    return models.FieldCondition(key=field, match=models.MatchValue(value=value))


def drop_collection(client: QdrantClient, collection: str) -> None:
    client.delete_collection(collection_name=collection)


def drop_generations(client: QdrantClient, generations: dict[str, str]) -> list[str]:
    """Delete unactivated candidate generations after deterministic validation."""
    removed: list[str] = []
    for generation in generations.values():
        client.delete_collection(collection_name=generation)
        removed.append(generation)
    return removed


def prune_retired_generations(
    client: QdrantClient, *, retention_days: int = 7, now_ns: int | None = None
) -> list[str]:
    """Remove retired generations only after the rollback-retention window."""
    active = set(_aliases(client).values())
    cutoff = (now_ns or time.time_ns()) - retention_days * 86_400 * 1_000_000_000
    removed: list[str] = []
    for item in client.get_collections().collections:
        name = str(item.name)
        match = re.fullmatch(r"(?:memories|raw)__g(\d+)", name)
        if name in active or match is None or int(match.group(1)) >= cutoff:
            continue
        client.delete_collection(collection_name=name)
        removed.append(name)
    return removed


def erase_all_indices(client: QdrantClient) -> None:
    """Remove every active and retired memkit generation for the sole owner."""
    names = [item.name for item in client.get_collections().collections]
    for name in names:
        if (
            name in {MEMORIES, RAW}
            or name.startswith(f"{MEMORIES}__g")
            or name.startswith(f"{RAW}__g")
        ):
            client.delete_collection(collection_name=name)


def count(client: QdrantClient, collection: str) -> int:
    return client.count(collection_name=resolve_collection(client, collection), exact=True).count


def live_alias(collection: str) -> str:
    return f"{collection}__live"


def _aliases(client: QdrantClient) -> dict[str, str]:
    getter = getattr(client, "get_aliases", None)
    if getter is None:
        return {}
    result = getter()
    return {item.alias_name: item.collection_name for item in getattr(result, "aliases", [])}


def _alias_exists(client: QdrantClient, alias: str) -> bool:
    return alias in _aliases(client)


def resolve_collection(client: QdrantClient, collection: str) -> str:
    """Use a live alias when generation-based rebuild has been activated."""
    if "__g" in collection:
        return collection
    alias = live_alias(collection)
    return alias if _alias_exists(client, alias) else collection


def create_empty_collection(client: QdrantClient, collection: str) -> None:
    client.create_collection(
        collection_name=collection,
        vectors_config={"dense": models.VectorParams(size=DIM, distance=models.Distance.COSINE)},
        sparse_vectors_config={"bm25": models.SparseVectorParams()},
    )
    logical = MEMORIES if collection.startswith(f"{MEMORIES}__g") else RAW
    for field in _INDEXES[logical]:
        client.create_payload_index(
            collection_name=collection,
            field_name=field,
            field_schema=models.PayloadSchemaType.KEYWORD,
        )


def scroll_vectors(
    client: QdrantClient,
    collection: str,
    *,
    must: list[models.FieldCondition] | None = None,
    page: int = 512,
) -> dict[str, list[float]]:
    """Every stored vector matching a filter, keyed by point id.

    Consolidation needs the vectors of an entire scope. They already exist here,
    so re-embedding the store to get them costs a model pass over every row for
    data the index is holding.
    """
    flt = models.Filter(must=must) if must else None
    found: dict[str, list[float]] = {}
    offset: Any = None
    resolved = resolve_collection(client, collection)
    while True:
        records, offset = client.scroll(
            collection_name=resolved,
            limit=page,
            offset=offset,
            with_payload=False,
            with_vectors=True,
            scroll_filter=flt,
        )
        for record in records:
            vector = record.vector
            dense = vector.get("dense") if isinstance(vector, dict) else vector
            if dense:
                found[str(record.id)] = list(dense)
        if offset is None or not records:
            return found


def delete_by_filter(
    client: QdrantClient, collection: str, *, must: list[models.FieldCondition]
) -> None:
    """Delete every point matching a filter, in one request.

    Erasure needs this: enumerating a user's point ids first would race with
    concurrent delivery, and the ids are exactly what is being removed.
    """
    client.delete(
        collection_name=resolve_collection(client, collection),
        points_selector=models.FilterSelector(filter=models.Filter(must=must)),
        wait=True,
    )


def exact_ids(client: QdrantClient, collection: str) -> set[str]:
    """Read every point ID for post-build validation."""
    if hasattr(client, "_store"):
        return {str(value) for value in client._store.get(collection, {})}
    ids: set[str] = set()
    offset = None
    while True:
        points, offset = client.scroll(
            collection_name=collection,
            limit=256,
            offset=offset,
            with_payload=False,
            with_vectors=False,
        )
        ids.update(str(point.id) for point in points)
        if offset is None:
            break
    return ids


def exact_payloads(client: QdrantClient, collection: str) -> dict[str, dict[str, Any]]:
    """Read the content as well as IDs when validating a rebuilt generation."""
    if hasattr(client, "_store"):
        return {str(key): dict(value) for key, value in client._store.get(collection, {}).items()}
    payloads: dict[str, dict[str, Any]] = {}
    offset = None
    while True:
        points, offset = client.scroll(
            collection_name=collection,
            limit=256,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        payloads.update((str(point.id), dict(point.payload or {})) for point in points)
        if offset is None:
            return payloads


def swap_aliases(client: QdrantClient, generations: dict[str, str]) -> None:
    aliases = _aliases(client)
    operations: list[Any] = []
    for logical, generation in generations.items():
        alias = live_alias(logical)
        if alias in aliases:
            operations.append(
                models.DeleteAliasOperation(delete_alias=models.DeleteAlias(alias_name=alias))
            )
        operations.append(
            models.CreateAliasOperation(
                create_alias=models.CreateAlias(collection_name=generation, alias_name=alias)
            )
        )
    client.update_collection_aliases(change_aliases_operations=operations)


def erase_user_indices(client: QdrantClient, *, user_id: str, private_scope_id: str) -> None:
    """Erase actual collections, including retired generations hidden by aliases."""
    for item in client.get_collections().collections:
        name = str(item.name)
        if re.fullmatch(r"memories(?:__g\d+)?", name):
            condition = keyword("scope_id", private_scope_id)
        elif re.fullmatch(r"raw(?:__g\d+)?", name):
            condition = keyword("user_id", user_id)
        else:
            continue
        client.delete(
            collection_name=name,
            points_selector=models.FilterSelector(filter=models.Filter(must=[condition])),
            wait=True,
        )
