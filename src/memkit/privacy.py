"""Owner export and complete erasure across authoritative and derived stores."""

from __future__ import annotations

import json
import sqlite3
import zipfile
from pathlib import Path
from typing import Any

from qdrant_client import QdrantClient

from . import vectors
from .db import transaction, utcnow
from .embed import Embedder


def _rows(conn: sqlite3.Connection, query: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(query, params).fetchall()]


def export_owner(
    conn: sqlite3.Connection,
    *,
    owner_id: str,
    export_dir: Path,
) -> Path:
    export_dir.mkdir(parents=True, exist_ok=True)
    timestamp = utcnow().replace(":", "").replace("-", "")
    path = export_dir / f"memkit-export-{timestamp}.zip"
    sessions = _rows(conn, "SELECT * FROM sessions WHERE owner_id=?", (owner_id,))
    session_ids = [row["id"] for row in sessions]
    messages: list[dict[str, Any]] = []
    if session_ids:
        placeholders = ",".join("?" for _ in session_ids)
        messages = _rows(
            conn,
            f"SELECT * FROM messages WHERE session_id IN ({placeholders}) ORDER BY id",
            tuple(session_ids),
        )
    memories = _rows(
        conn, "SELECT * FROM memories WHERE owner_id=? ORDER BY created_at", (owner_id,)
    )
    memory_ids = [row["id"] for row in memories]
    sources: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    if memory_ids:
        placeholders = ",".join("?" for _ in memory_ids)
        sources = _rows(
            conn,
            f"SELECT * FROM memory_sources WHERE memory_id IN ({placeholders})",
            tuple(memory_ids),
        )
        evidence = _rows(
            conn,
            f"SELECT * FROM memory_evidence WHERE memory_id IN ({placeholders})",
            tuple(memory_ids),
        )
    namespaces = _rows(conn, "SELECT * FROM namespaces WHERE owner_id=?", (owner_id,))
    namespace_ids = [row["id"] for row in namespaces]
    collections: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    if namespace_ids:
        placeholders = ",".join("?" for _ in namespace_ids)
        collections = _rows(
            conn,
            f"SELECT * FROM collections WHERE namespace_id IN ({placeholders})",
            tuple(namespace_ids),
        )
        collection_ids = [row["id"] for row in collections]
        if collection_ids:
            placeholders = ",".join("?" for _ in collection_ids)
            records = _rows(
                conn,
                f"SELECT * FROM records WHERE collection_id IN ({placeholders})",
                tuple(collection_ids),
            )
    record_ids = [row["id"] for row in records]
    revisions: list[dict[str, Any]] = []
    if record_ids:
        placeholders = ",".join("?" for _ in record_ids)
        revisions = _rows(
            conn,
            f"SELECT * FROM record_revisions WHERE record_id IN ({placeholders})",
            tuple(record_ids),
        )
    links: list[dict[str, Any]] = []
    policies: list[dict[str, Any]] = []
    if namespace_ids:
        placeholders = ",".join("?" for _ in namespace_ids)
        links = _rows(
            conn,
            f"SELECT * FROM links WHERE namespace_id IN ({placeholders})",
            tuple(namespace_ids),
        )
        policies = _rows(
            conn,
            f"SELECT * FROM policies WHERE namespace_id IN ({placeholders})",
            tuple(namespace_ids),
        )
    feedback: list[dict[str, Any]] = []
    if memory_ids:
        placeholders = ",".join("?" for _ in memory_ids)
        feedback = _rows(
            conn,
            f"SELECT * FROM retrieval_feedback WHERE memory_id IN ({placeholders})",
            tuple(memory_ids),
        )
    payload = {
        "format": "memkit-owner-export-v1",
        "exported_at": utcnow(),
        "owner_id": owner_id,
        "sessions": sessions,
        "messages": messages,
        "memories": memories,
        "memory_sources": sources,
        "memory_evidence": evidence,
        "namespaces": namespaces,
        "collections": collections,
        "records": records,
        "record_revisions": revisions,
        "links": links,
        "policies": policies,
        "retrieval_feedback": feedback,
    }
    temporary = path.with_suffix(".zip.tmp")
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "export.json",
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        )
    temporary.replace(path)
    return path


def erase_owner(
    conn: sqlite3.Connection,
    client: QdrantClient,
    embedder: Embedder,
    *,
    owner_id: str,
) -> dict[str, int]:
    memory_ids = [
        row["id"] for row in conn.execute("SELECT id FROM memories WHERE owner_id=?", (owner_id,))
    ]
    message_ids = [
        int(row["id"])
        for row in conn.execute(
            """SELECT m.id FROM messages m JOIN sessions s ON s.id=m.session_id
                WHERE s.owner_id=?""",
            (owner_id,),
        )
    ]
    # This service has exactly one owner, so old generations also belong to the
    # target. Removing only the live alias would leave recoverable personal data.
    vectors.erase_all_indices(client)

    with transaction(conn):
        conn.execute(
            "DELETE FROM retrieval_feedback WHERE memory_id IN (SELECT id FROM memories WHERE owner_id=?)",
            (owner_id,),
        )
        conn.execute(
            "DELETE FROM memory_evidence WHERE memory_id IN (SELECT id FROM memories WHERE owner_id=?)",
            (owner_id,),
        )
        conn.execute(
            "DELETE FROM memory_sources WHERE memory_id IN (SELECT id FROM memories WHERE owner_id=?)",
            (owner_id,),
        )
        conn.execute("UPDATE memories SET superseded_by=NULL WHERE owner_id=?", (owner_id,))
        conn.execute("DELETE FROM memories WHERE owner_id=?", (owner_id,))
        conn.execute(
            "DELETE FROM record_revisions WHERE record_id IN (SELECT r.id FROM records r JOIN collections c ON c.id=r.collection_id JOIN namespaces n ON n.id=c.namespace_id WHERE n.owner_id=?)",
            (owner_id,),
        )
        conn.execute("DELETE FROM namespaces WHERE owner_id=?", (owner_id,))
        conn.execute(
            "DELETE FROM messages WHERE session_id IN (SELECT id FROM sessions WHERE owner_id=?)",
            (owner_id,),
        )
        conn.execute("DELETE FROM sessions WHERE owner_id=?", (owner_id,))
        conn.execute("DELETE FROM judge_runs WHERE owner_id=?", (owner_id,))
        if memory_ids:
            placeholders = ",".join("?" for _ in memory_ids)
            conn.execute(
                f"DELETE FROM index_outbox WHERE collection=? AND entity_id IN ({placeholders})",
                (vectors.MEMORIES, *memory_ids),
            )
        if message_ids:
            placeholders = ",".join("?" for _ in message_ids)
            conn.execute(
                f"DELETE FROM index_outbox WHERE collection=? AND entity_id IN ({placeholders})",
                (vectors.RAW, *(str(value) for value in message_ids)),
            )
        conn.execute("DELETE FROM owners WHERE id=?", (owner_id,))
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.execute("VACUUM")
    vectors.ensure_collections(client)
    return {"memories": len(memory_ids), "messages": len(message_ids)}
