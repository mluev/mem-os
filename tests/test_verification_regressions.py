from __future__ import annotations

import json
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from memkit import extract, jobs, outbox, privacy, reextract, store, vectors
from memkit.db import connect, transaction, utcnow
from tests.fixtures import OWNER, StubEmbedder, StubQdrant, make_db
from tests.httpharness import ApiTestCase


def test_outbox_never_mutates_a_claimed_delivery() -> None:
    conn = make_db()
    with transaction(conn):
        first = outbox.enqueue(
            conn,
            collection=vectors.MEMORIES,
            entity_id="m-1",
            operation="upsert",
            payload={"text": "old", "owner_id": OWNER},
        )
    conn.execute(
        "UPDATE index_outbox SET status='processing',claim_token='claim-1' WHERE id=?",
        (first,),
    )
    conn.commit()

    with transaction(conn):
        second = outbox.enqueue(
            conn,
            collection=vectors.MEMORIES,
            entity_id="m-1",
            operation="upsert",
            payload={"text": "new", "owner_id": OWNER},
        )

    assert second > first
    rows = conn.execute("SELECT id,status,payload_json FROM index_outbox ORDER BY id").fetchall()
    assert [(row["id"], row["status"]) for row in rows] == [
        (first, "processing"),
        (second, "pending"),
    ]
    assert json.loads(rows[0]["payload_json"])["text"] == "old"
    assert json.loads(rows[1]["payload_json"])["text"] == "new"


def test_stale_outbox_claim_is_recovered() -> None:
    conn = make_db()
    qdrant = StubQdrant()
    memory_id: str
    with transaction(conn):
        memory_id = store.add_memory(
            conn,
            owner_id=OWNER,
            text="recover me",
            kind="fact",
            source_role="manual",
        )
    expired = (datetime.now(UTC) - timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
    conn.execute(
        """UPDATE index_outbox SET status='processing',claim_token='dead',
                  lease_expires_at=? WHERE entity_id=?""",
        (expired, memory_id),
    )
    conn.commit()

    outcome = outbox.drain(conn, qdrant, StubEmbedder(), ignore_schedule=True)

    assert outcome.applied == 1
    assert qdrant.points[memory_id]["text"] == "recover me"


def test_erase_waits_for_active_delivery_and_cannot_resurrect() -> None:
    conn = make_db()
    path = Path(conn.execute("PRAGMA database_list").fetchone()[2])
    qdrant = StubQdrant()
    entered = threading.Event()
    release = threading.Event()

    class BlockingQdrant(StubQdrant):
        def upsert(self, collection_name, points, wait=True):
            entered.set()
            assert release.wait(timeout=5)
            return qdrant.upsert(collection_name, points, wait=wait)

        def delete_collection(self, collection_name, **kwargs):
            return qdrant.delete_collection(collection_name, **kwargs)

        def get_collections(self):
            return qdrant.get_collections()

        def create_collection(self, collection_name, **kwargs):
            return qdrant.create_collection(collection_name, **kwargs)

        def create_payload_index(self, **kwargs):
            return qdrant.create_payload_index(**kwargs)

    with transaction(conn):
        memory_id = store.add_memory(
            conn,
            owner_id=OWNER,
            text="erase me",
            kind="fact",
            source_role="manual",
        )

    drain_thread = threading.Thread(
        target=lambda: outbox.drain(connect(path), BlockingQdrant(), StubEmbedder())
    )
    erase_thread = threading.Thread(
        target=lambda: privacy.erase_owner(
            connect(path),
            qdrant,
            StubEmbedder(),
            owner_id=OWNER,
            export_dir=path.parent / "exports",
        )
    )
    drain_thread.start()
    assert entered.wait(timeout=2)
    erase_thread.start()
    release.set()
    drain_thread.join(timeout=5)
    erase_thread.join(timeout=5)

    assert not drain_thread.is_alive()
    assert not erase_thread.is_alive()
    assert memory_id not in qdrant.points
    check = connect(path)
    assert check.execute("SELECT COUNT(*) FROM memories").fetchone()[0] == 0


def test_extraction_window_claim_is_exclusive() -> None:
    conn = make_db()
    with transaction(conn):
        conn.execute(
            "INSERT INTO messages(session_id,role,content,created_at) VALUES ('s-1','user','remember tea',?)",
            (utcnow(),),
        )
    path = Path(conn.execute("PRAGMA database_list").fetchone()[2])
    first = extract.claim_window(conn, session_id="s-1", job_id="job-a")
    second = extract.claim_window(connect(path), session_id="s-1", job_id="job-b")
    assert len(first) == 1
    assert second == []


def test_stale_job_and_budget_reservation_recovery() -> None:
    conn = make_db()
    job_id = jobs.create(conn, kind="export")
    jobs.claim(conn, job_id, holder="dead-worker", lease_seconds=1)
    with transaction(conn):
        conn.execute(
            "INSERT INTO messages(session_id,role,content,created_at) VALUES ('s-1','user','recover me',?)",
            (utcnow(),),
        )
    assert extract.claim_window(conn, session_id="s-1", job_id=job_id)
    reservation_id = jobs.reserve_budget(
        conn,
        period="2026-08",
        amount_usd=0.5,
        limit_usd=1.0,
        job_id=job_id,
    )
    old = "2020-01-01T00:00:00Z"
    conn.execute("UPDATE jobs SET lease_expires_at=? WHERE id=?", (old, job_id))
    conn.execute("UPDATE budget_reservations SET updated_at=? WHERE id=?", (old, reservation_id))
    conn.commit()

    recovered = jobs.recover_stale(conn)

    assert recovered["jobs"] == 1
    assert recovered["reservations"] == 1
    assert recovered["message_claims"] == 1
    assert jobs.get(conn, job_id)["status"] == "queued"
    assert (
        conn.execute(
            "SELECT status FROM budget_reservations WHERE id=?", (reservation_id,)
        ).fetchone()[0]
        == "released"
    )
    assert (
        conn.execute("SELECT claim_token FROM messages WHERE session_id='s-1'").fetchone()[0]
        is None
    )


class TestMemoryRevisionRegression(ApiTestCase):
    def test_patch_uses_atomic_integer_revision_and_redacts(self) -> None:
        memory_id = self.seed_memory(text="original")
        row = self.db.execute("SELECT revision FROM memories WHERE id=?", (memory_id,)).fetchone()
        response = self.client.patch(
            f"/v1/memories/{memory_id}",
            headers=self.auth,
            json={"expected_revision": row["revision"], "text": "API_KEY=super-secret-value"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["revision"], 2)
        self.assertNotIn("super-secret-value", response.json()["text"])
        self.assertTrue(response.json()["redacted"])

        metadata_only = self.client.patch(
            f"/v1/memories/{memory_id}",
            headers=self.auth,
            json={"expected_revision": 2, "importance": 0.8},
        )
        self.assertEqual(metadata_only.status_code, 200, metadata_only.text)
        self.assertTrue(metadata_only.json()["redacted"])

        stale = self.client.patch(
            f"/v1/memories/{memory_id}",
            headers=self.auth,
            json={"expected_revision": 1, "text": "stale overwrite"},
        )
        self.assertEqual(stale.status_code, 409)
        history = self.client.get(f"/v1/memories/{memory_id}/history", headers=self.auth).json()[
            "revisions"
        ]
        self.assertEqual([item["revision"] for item in history], [3, 2, 1])


def test_record_delete_creates_a_revision() -> None:
    conn = make_db()
    from memkit import platform

    with transaction(conn):
        platform.create_namespace(conn, owner_id=OWNER, name="life")
        platform.create_collection(
            conn,
            owner_id=OWNER,
            namespace="life",
            name="items",
            schema={"type": "object"},
        )
        record, _ = platform.create_record(
            conn,
            owner_id=OWNER,
            namespace="life",
            collection_name="items",
            value={"title": "one"},
        )
        platform.delete_record(
            conn,
            owner_id=OWNER,
            namespace="life",
            collection_name="items",
            record_id=record["id"],
            expected_revision=1,
        )
    current = conn.execute(
        "SELECT revision,status FROM records WHERE id=?", (record["id"],)
    ).fetchone()
    assert (current["revision"], current["status"]) == (2, "deleted")
    history = platform.record_history(
        conn,
        owner_id=OWNER,
        namespace="life",
        collection_name="items",
        record_id=record["id"],
    )
    assert history[0]["status"] == "deleted"


def test_replay_resume_keeps_its_persistent_message_cursor() -> None:
    conn = make_db()
    with transaction(conn):
        conn.executemany(
            "INSERT INTO messages(session_id,role,content,processed,created_at) VALUES ('s-1','user',?,1,?)",
            [("first", utcnow()), ("second", utcnow())],
        )
    job_id = jobs.create(conn, kind="legacy_replay_dry_run", input_data={"apply": True})

    cancelled = reextract.apply_replay(
        conn,
        owner_id=OWNER,
        api_key="",
        gemini_api_key="",
        project="",
        location="",
        monthly_limit_usd=1,
        model="test",
        job_id=job_id,
        cancelled=lambda: True,
    )
    assert cancelled["cancelled"] is True
    conn.execute("UPDATE messages SET processed=1 WHERE id=(SELECT MIN(id) FROM messages)")
    conn.commit()

    def process_one(connection, **_kwargs):
        row = connection.execute(
            "SELECT id FROM messages WHERE session_id='s-1' AND processed=0 ORDER BY id LIMIT 1"
        ).fetchone()
        connection.execute("UPDATE messages SET processed=1 WHERE id=?", (row["id"],))
        connection.commit()
        return extract.ExtractionOutcome(added=1)

    with patch("memkit.reextract.extract.run_extraction", side_effect=process_one) as mocked:
        resumed = reextract.apply_replay(
            conn,
            owner_id=OWNER,
            api_key="",
            gemini_api_key="",
            project="",
            location="",
            monthly_limit_usd=1,
            model="test",
            job_id=job_id,
            cancelled=lambda: False,
        )
    assert mocked.call_count == 1
    assert resumed["added"] == 1
    assert conn.execute("SELECT COUNT(*) FROM messages WHERE processed=0").fetchone()[0] == 0
