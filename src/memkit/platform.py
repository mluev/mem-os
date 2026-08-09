"""Generic namespaces, schema-validated records, links, and policies."""

from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

from . import filters, security
from .db import utcnow


class PlatformError(ValueError):
    pass


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def create_namespace(
    conn: sqlite3.Connection,
    *,
    owner_id: str,
    name: str,
    description: str = "",
) -> dict[str, Any]:
    name = name.strip()
    if not name or len(name) > 128:
        raise PlatformError("namespace name must contain 1–128 characters")
    namespace_id = str(uuid.uuid4())
    now = utcnow()
    try:
        conn.execute(
            """INSERT INTO namespaces(id,owner_id,name,description,created_at,updated_at)
               VALUES (?,?,?,?,?,?)""",
            (namespace_id, owner_id, name, description.strip(), now, now),
        )
    except sqlite3.IntegrityError as exc:
        raise PlatformError(f"namespace {name!r} already exists") from exc
    return dict(conn.execute("SELECT * FROM namespaces WHERE id=?", (namespace_id,)).fetchone())


def create_collection(
    conn: sqlite3.Connection,
    *,
    owner_id: str,
    namespace: str,
    name: str,
    schema: dict[str, Any],
    indexed_fields: list[str] | None = None,
    embedding_fields: list[str] | None = None,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ns = conn.execute(
        "SELECT * FROM namespaces WHERE owner_id=? AND name=?", (owner_id, namespace)
    ).fetchone()
    if ns is None:
        raise PlatformError("unknown namespace")
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise PlatformError(f"invalid JSON Schema: {exc.message}") from exc
    name = name.strip()
    if not name or len(name) > 128:
        raise PlatformError("collection name must contain 1–128 characters")
    collection_id = str(uuid.uuid4())
    now = utcnow()
    try:
        conn.execute(
            """INSERT INTO collections
               (id,namespace_id,name,schema_json,indexed_fields_json,
                embedding_fields_json,policy_json,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                collection_id,
                ns["id"],
                name,
                _json(schema),
                _json(indexed_fields or []),
                _json(embedding_fields or []),
                _json(policy or {}),
                now,
                now,
            ),
        )
    except sqlite3.IntegrityError as exc:
        raise PlatformError(f"collection {name!r} already exists") from exc
    return collection_definition(conn, owner_id=owner_id, namespace=namespace, name=name)


def _collection(
    conn: sqlite3.Connection, *, owner_id: str, namespace: str, name: str
) -> sqlite3.Row:
    row = conn.execute(
        """SELECT c.*,n.name AS namespace_name FROM collections c
             JOIN namespaces n ON n.id=c.namespace_id
            WHERE n.owner_id=? AND n.name=? AND c.name=?""",
        (owner_id, namespace, name),
    ).fetchone()
    if row is None:
        raise PlatformError("unknown collection")
    return row


def collection_definition(
    conn: sqlite3.Connection, *, owner_id: str, namespace: str, name: str
) -> dict[str, Any]:
    row = _collection(conn, owner_id=owner_id, namespace=namespace, name=name)
    return {
        "id": row["id"],
        "namespace": row["namespace_name"],
        "name": row["name"],
        "schema_version": row["schema_version"],
        "schema": json.loads(row["schema_json"]),
        "indexed_fields": json.loads(row["indexed_fields_json"]),
        "embedding_fields": json.loads(row["embedding_fields_json"]),
        "policy": json.loads(row["policy_json"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def list_namespaces(conn: sqlite3.Connection, *, owner_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT n.*,COUNT(c.id) AS collection_count FROM namespaces n
             LEFT JOIN collections c ON c.namespace_id=n.id
            WHERE n.owner_id=? GROUP BY n.id ORDER BY n.name""",
        (owner_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def list_collections(
    conn: sqlite3.Connection, *, owner_id: str, namespace: str
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT c.name FROM collections c JOIN namespaces n ON n.id=c.namespace_id
            WHERE n.owner_id=? AND n.name=? ORDER BY c.name""",
        (owner_id, namespace),
    ).fetchall()
    return [
        collection_definition(conn, owner_id=owner_id, namespace=namespace, name=row["name"])
        for row in rows
    ]


def _validate(collection: sqlite3.Row, value: dict[str, Any]) -> None:
    try:
        Draft202012Validator(json.loads(collection["schema_json"])).validate(value)
    except ValidationError as exc:
        path = ".".join(str(part) for part in exc.absolute_path) or "$"
        raise PlatformError(f"record validation failed at {path}: {exc.message}") from exc


def create_record(
    conn: sqlite3.Connection,
    *,
    owner_id: str,
    namespace: str,
    collection_name: str,
    value: dict[str, Any],
    metadata: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
) -> tuple[dict[str, Any], bool]:
    value, _ = security.redact_value(value)
    metadata, _ = security.redact_value(metadata or {})
    context, _ = security.redact_value(context or {})
    collection = _collection(conn, owner_id=owner_id, namespace=namespace, name=collection_name)
    _validate(collection, value)
    if idempotency_key:
        existing = conn.execute(
            "SELECT * FROM records WHERE collection_id=? AND idempotency_key=?",
            (collection["id"], idempotency_key),
        ).fetchone()
        if existing:
            return record_dict(existing), True
    record_id = str(uuid.uuid4())
    now = utcnow()
    conn.execute(
        """INSERT INTO records
           (id,collection_id,value_json,metadata_json,context_json,idempotency_key,
            created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)""",
        (
            record_id,
            collection["id"],
            _json(value),
            _json(metadata),
            _json(context),
            idempotency_key,
            now,
            now,
        ),
    )
    conn.execute(
        """INSERT INTO record_revisions
           (record_id,revision,value_json,metadata_json,context_json,created_at)
           VALUES (?,1,?,?,?,?)""",
        (record_id, _json(value), _json(metadata), _json(context), now),
    )
    return record_dict(
        conn.execute("SELECT * FROM records WHERE id=?", (record_id,)).fetchone()
    ), False


def update_record(
    conn: sqlite3.Connection,
    *,
    owner_id: str,
    namespace: str,
    collection_name: str,
    record_id: str,
    expected_revision: int,
    value: dict[str, Any],
    metadata: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    value, _ = security.redact_value(value)
    if metadata is not None:
        metadata, _ = security.redact_value(metadata)
    if context is not None:
        context, _ = security.redact_value(context)
    collection = _collection(conn, owner_id=owner_id, namespace=namespace, name=collection_name)
    _validate(collection, value)
    current = conn.execute(
        "SELECT * FROM records WHERE id=? AND collection_id=?",
        (record_id, collection["id"]),
    ).fetchone()
    if current is None:
        raise PlatformError("unknown record")
    if current["revision"] != expected_revision:
        raise PlatformError("record revision conflict")
    revision = expected_revision + 1
    now = utcnow()
    next_metadata = metadata if metadata is not None else json.loads(current["metadata_json"])
    next_context = context if context is not None else json.loads(current["context_json"])
    changed = conn.execute(
        """UPDATE records
              SET revision=?,value_json=?,metadata_json=?,context_json=?,updated_at=?
            WHERE id=? AND revision=?""",
        (
            revision,
            _json(value),
            _json(next_metadata),
            _json(next_context),
            now,
            record_id,
            expected_revision,
        ),
    ).rowcount
    if not changed:
        raise PlatformError("record revision conflict")
    conn.execute(
        """INSERT INTO record_revisions
           (record_id,revision,value_json,metadata_json,context_json,created_at)
           VALUES (?,?,?,?,?,?)""",
        (
            record_id,
            revision,
            _json(value),
            _json(next_metadata),
            _json(next_context),
            now,
        ),
    )
    return record_dict(conn.execute("SELECT * FROM records WHERE id=?", (record_id,)).fetchone())


def delete_record(
    conn: sqlite3.Connection,
    *,
    owner_id: str,
    namespace: str,
    collection_name: str,
    record_id: str,
) -> None:
    collection = _collection(conn, owner_id=owner_id, namespace=namespace, name=collection_name)
    changed = conn.execute(
        "UPDATE records SET status='deleted',updated_at=? WHERE id=? AND collection_id=?",
        (utcnow(), record_id, collection["id"]),
    ).rowcount
    if not changed:
        raise PlatformError("unknown record")


def search_records(
    conn: sqlite3.Connection,
    *,
    owner_id: str,
    namespace: str,
    collection_name: str,
    expression: dict[str, Any] | None,
    limit: int,
    cursor: str | None = None,
) -> list[dict[str, Any]]:
    return search_record_page(
        conn,
        owner_id=owner_id,
        namespace=namespace,
        collection_name=collection_name,
        expression=expression,
        limit=limit,
        cursor=cursor,
    )[0]


def search_record_page(
    conn: sqlite3.Connection,
    *,
    owner_id: str,
    namespace: str,
    collection_name: str,
    expression: dict[str, Any] | None,
    limit: int,
    cursor: str | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    collection = _collection(conn, owner_id=owner_id, namespace=namespace, name=collection_name)
    results: list[dict[str, Any]] = []
    after = cursor
    exhausted = False
    while len(results) < limit and not exhausted:
        rows = conn.execute(
            """SELECT * FROM records
                WHERE collection_id=? AND status='active' AND (? IS NULL OR id>?)
                ORDER BY id LIMIT 500""",
            (collection["id"], after, after),
        ).fetchall()
        exhausted = len(rows) < 500
        for row in rows:
            after = row["id"]
            record = record_dict(row)
            if filters.matches(record, expression):
                results.append(record)
            if len(results) >= limit:
                break
    if not results:
        return [], None if exhausted else after
    remaining = conn.execute(
        """SELECT 1 FROM records
            WHERE collection_id=? AND status='active' AND id>? LIMIT 1""",
        (collection["id"], after),
    ).fetchone()
    return results, after if remaining else None


def record_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "revision": int(row["revision"]),
        "value": json.loads(row["value_json"]),
        "metadata": json.loads(row["metadata_json"]),
        "context": json.loads(row["context_json"]),
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def record_history(
    conn: sqlite3.Connection,
    *,
    owner_id: str,
    namespace: str,
    collection_name: str,
    record_id: str,
) -> list[dict[str, Any]]:
    collection = _collection(conn, owner_id=owner_id, namespace=namespace, name=collection_name)
    exists = conn.execute(
        "SELECT 1 FROM records WHERE id=? AND collection_id=?",
        (record_id, collection["id"]),
    ).fetchone()
    if not exists:
        raise PlatformError("unknown record")
    return [
        {
            "revision": row["revision"],
            "value": json.loads(row["value_json"]),
            "metadata": json.loads(row["metadata_json"]),
            "context": json.loads(row["context_json"]),
            "created_at": row["created_at"],
        }
        for row in conn.execute(
            "SELECT * FROM record_revisions WHERE record_id=? ORDER BY revision DESC",
            (record_id,),
        )
    ]


def create_link(
    conn: sqlite3.Connection,
    *,
    owner_id: str,
    namespace: str,
    from_ref: str,
    relation: str,
    to_ref: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ns = conn.execute(
        "SELECT id FROM namespaces WHERE owner_id=? AND name=?", (owner_id, namespace)
    ).fetchone()
    if ns is None:
        raise PlatformError("unknown namespace")
    metadata, _ = security.redact_value(metadata or {})
    link_id = str(uuid.uuid4())
    conn.execute(
        """INSERT INTO links(id,namespace_id,from_ref,relation,to_ref,metadata_json,created_at)
           VALUES (?,?,?,?,?,?,?)""",
        (link_id, ns["id"], from_ref, relation.strip(), to_ref, _json(metadata), utcnow()),
    )
    return {
        "id": link_id,
        "from_ref": from_ref,
        "relation": relation.strip(),
        "to_ref": to_ref,
        "metadata": metadata,
    }


def list_links(conn: sqlite3.Connection, *, owner_id: str, namespace: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT l.* FROM links l JOIN namespaces n ON n.id=l.namespace_id
            WHERE n.owner_id=? AND n.name=? ORDER BY l.created_at,l.id""",
        (owner_id, namespace),
    ).fetchall()
    return [
        {
            "id": row["id"],
            "from_ref": row["from_ref"],
            "relation": row["relation"],
            "to_ref": row["to_ref"],
            "metadata": json.loads(row["metadata_json"]),
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def list_policies(
    conn: sqlite3.Connection, *, owner_id: str, namespace: str | None = None
) -> list[dict[str, Any]]:
    clauses = ["(p.namespace_id IS NULL OR n.owner_id=?)"]
    params: list[Any] = [owner_id]
    if namespace is not None:
        clauses.append("n.name=?")
        params.append(namespace)
    rows = conn.execute(
        f"""SELECT p.*,n.name AS namespace_name FROM policies p
              LEFT JOIN namespaces n ON n.id=p.namespace_id
             WHERE {" AND ".join(clauses)} ORDER BY p.kind,p.name,p.version DESC""",
        params,
    ).fetchall()
    return [
        {
            "id": row["id"],
            "namespace": row["namespace_name"],
            "kind": row["kind"],
            "name": row["name"],
            "version": row["version"],
            "config": json.loads(row["config_json"]),
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def put_policy(
    conn: sqlite3.Connection,
    *,
    namespace_id: str | None,
    kind: str,
    name: str,
    version: int,
    config: dict[str, Any],
) -> str:
    policy_id = str(uuid.uuid4())
    conn.execute(
        """INSERT INTO policies
           (id,namespace_id,kind,name,version,config_json,created_at)
           VALUES (?,?,?,?,?,?,?)""",
        (policy_id, namespace_id, kind, name, version, _json(config), utcnow()),
    )
    return policy_id
