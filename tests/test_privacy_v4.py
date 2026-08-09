from __future__ import annotations

import json
import tempfile
import zipfile
from pathlib import Path

from memkit import outbox, platform, privacy, store
from memkit.db import transaction
from tests.fixtures import OWNER, StubEmbedder, StubQdrant, make_db


def test_export_is_complete_and_erasure_removes_truth_and_generations() -> None:
    conn = make_db()
    client = StubQdrant()
    embedder = StubEmbedder()
    with transaction(conn):
        store.add_message(
            conn,
            session_id="privacy",
            owner_id=OWNER,
            agent_id="chat",
            role="user",
            content="A durable evidence event long enough to index",
        )
        memory_id = store.add_memory(
            conn, owner_id=OWNER, text="Prefers local storage", kind="preference"
        )
        platform.create_namespace(conn, owner_id=OWNER, name="personal")
        platform.create_collection(
            conn,
            owner_id=OWNER,
            namespace="personal",
            name="records",
            schema={
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        )
        platform.create_record(
            conn,
            owner_id=OWNER,
            namespace="personal",
            collection_name="records",
            value={"name": "sample"},
        )
    outbox.drain(conn, client, embedder, limit=100)
    output = Path(tempfile.mkdtemp())
    archive = privacy.export_owner(conn, owner_id=OWNER, export_dir=output)
    with zipfile.ZipFile(archive) as handle:
        payload = json.loads(handle.read("export.json"))
    assert payload["memories"][0]["id"] == memory_id
    assert payload["messages"] and payload["records"] and payload["record_revisions"]

    counts = privacy.erase_owner(conn, client, embedder, owner_id=OWNER)
    assert counts == {"memories": 1, "messages": 1}
    assert conn.execute("SELECT COUNT(*) FROM owners").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM index_outbox").fetchone()[0] == 0
    assert all(not values for values in client._store.values())
