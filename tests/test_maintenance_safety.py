"""Failure schedules at the PostgreSQL/index/privacy boundary."""

from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest

from memkit import jobs, outbox, privacy, reindex, store, vectors
from memkit.db import connect
from tests.fixtures import StubEmbedder, make_db, seed_team
from tests.test_reindex_v4 import AliasQdrant
from tests.test_verification_regressions import FilterAwareQdrant


class IndexedCollections(AliasQdrant, FilterAwareQdrant):
    pass


@pytest.fixture
def system():
    conn = make_db(seed=False)
    team = seed_team(conn)
    client = IndexedCollections()
    with TemporaryDirectory() as directory:
        yield conn, team, client, StubEmbedder(), Path(directory)
    conn.close()


def add(conn, team, text="Private durable fact"):
    with conn.transaction():
        return store.add_memory(
            conn, scope_id=team.scope_of("alice"), author_id=team.alice_id, text=text, kind="fact"
        )


def test_reassigned_outbox_claim_cannot_write(system):
    conn, team, client, embedder, _ = system
    memory_id = add(conn, team)
    row = outbox._claim_next(conn, ignore_schedule=True, lease_seconds=300)
    conn.execute("UPDATE index_outbox SET claim_token='replacement' WHERE id=%s", (row["id"],))
    outbox._deliver(conn, client, embedder, row, vector=None, max_attempts=8)
    assert memory_id not in client.points


def test_obsolete_delete_does_not_remove_restored_memory(system):
    conn, team, client, embedder, _ = system
    memory_id = add(conn, team)
    outbox.drain(conn, client, embedder)
    with conn.transaction():
        store.set_memory_status(
            conn, memory_id=memory_id, scopes=[team.scope_of("alice")], status="archived"
        )
    deletion = outbox._claim_next(conn, ignore_schedule=True, lease_seconds=300)
    with conn.transaction():
        store.set_memory_status(
            conn, memory_id=memory_id, scopes=[team.scope_of("alice")], status="active"
        )
    reindex.rebuild(conn, client, embedder)
    outbox._deliver(conn, client, embedder, deletion, vector=None, max_attempts=8)
    live = client._store[client.aliases[vectors.live_alias(vectors.MEMORIES)]]
    assert memory_id in live


def test_erase_clears_retired_generations_and_managed_exports(system):
    conn, team, client, embedder, directory = system
    memory_id = add(conn, team)
    outbox.drain(conn, client, embedder)
    reindex.rebuild(conn, client, embedder)
    reindex.rebuild(conn, client, embedder)
    exported = privacy.export_user(
        conn,
        user_id=team.alice_id,
        private_scope_id=team.scope_of("alice"),
        export_dir=directory / "exports",
    )
    privacy.erase_user(
        conn,
        client,
        user_id=team.alice_id,
        private_scope_id=team.scope_of("alice"),
        export_dir=directory / "exports",
        backup_dir=directory / "backups",
    )
    assert not Path(exported["path"]).exists()
    assert all(memory_id not in points for points in client._store.values())


def test_erase_survives_external_failure_and_retries_without_user(system):
    conn, team, client, embedder, directory = system
    memory_id = add(conn, team)
    outbox.drain(conn, client, embedder)
    job_id = jobs.create(
        conn,
        kind="erase",
        user_id=team.alice_id,
        input_data={"user_id": team.alice_id, "private_scope_id": team.scope_of("alice")},
    )
    jobs.claim(conn, job_id)
    kwargs = dict(
        user_id=team.alice_id,
        private_scope_id=team.scope_of("alice"),
        job_id=job_id,
        export_dir=directory / "exports",
        backup_dir=directory / "backups",
    )
    with (
        patch.object(client, "delete", side_effect=RuntimeError("unreachable")),
        pytest.raises(privacy.ErasureCleanupPending),
    ):
        privacy.erase_user(conn, client, **kwargs)
    assert conn.execute("SELECT 1 FROM users WHERE id=%s", (team.alice_id,)).fetchone() is None
    assert jobs.get(conn, job_id)["user_id"] is None
    assert jobs.get(conn, job_id)["input"]["erasure"]["database_erased"] is True
    result = privacy.erase_user(conn, client, **kwargs)
    assert result["memories"] == 1
    assert memory_id not in client.points
    manifests = [
        p for p in (directory / "backups" / "erasures").glob("*.json") if p.name != "manifest.json"
    ]
    assert len(manifests) == 1
    assert json.loads(manifests[0].read_text())["user_id"] == team.alice_id


def test_manifest_failure_prevents_authoritative_deletion(system):
    conn, team, client, _, directory = system
    memory_id = add(conn, team)
    with (
        patch.object(privacy, "_write_erasure_manifest", side_effect=OSError("full disk")),
        pytest.raises(privacy.ErasureCleanupPending),
    ):
        privacy.erase_user(
            conn,
            client,
            user_id=team.alice_id,
            private_scope_id=team.scope_of("alice"),
            export_dir=directory / "exports",
            backup_dir=directory / "backups",
        )
    assert conn.execute("SELECT 1 FROM memories WHERE id=%s", (memory_id,)).fetchone()


def test_maintenance_excludes_other_writes_and_releases_on_failure(system):
    from memkit import maintenance

    conn, _, _, _, _ = system
    with connect(os.environ["MEMKIT_DATABASE_URL"]) as other:
        with pytest.raises(RuntimeError, match="abort"), maintenance.exclusive(conn):
            with conn.transaction():
                maintenance.require_write(conn)  # same-session reentry
            with other.transaction(), pytest.raises(maintenance.MaintenanceBusy):
                maintenance.require_write(other)
            raise RuntimeError("abort")
        with other.transaction():
            maintenance.require_write(other)


def test_rebuild_refuses_payload_corruption_before_alias_swap(system):
    conn, team, _, embedder, _ = system
    memory_id = add(conn, team)

    class CorruptingIndex(IndexedCollections):
        def upsert(self, collection_name, points, wait=True):
            super().upsert(collection_name, points, wait=wait)
            if "__g" in collection_name:
                self._store[collection_name][memory_id]["text"] = "incorrect text"

    client = CorruptingIndex()
    with pytest.raises(reindex.ReindexError):
        reindex.rebuild(conn, client, embedder)
    assert not client.aliases


def test_rebuild_blocks_other_process_writes_during_embedding(system):
    from memkit import maintenance

    conn, team, client, _, _ = system
    memory_id = add(conn, team)
    attempts = []

    class CheckedEmbedder(StubEmbedder):
        def encode(self, texts):
            with connect(os.environ["MEMKIT_DATABASE_URL"]) as writer:
                with pytest.raises(maintenance.MaintenanceBusy):
                    add(writer, team, "must wait until rebuild finishes")
                attempts.append(True)
            return super().encode(texts)

    reindex.rebuild(conn, client, CheckedEmbedder())
    assert attempts
    assert conn.execute("SELECT count(*) AS n FROM memories").fetchone()["n"] == 1
    assert memory_id in client._store[client.aliases[vectors.live_alias(vectors.MEMORIES)]]


def test_missing_restore_manifest_never_means_no_erasures(system):
    _, _, _, _, directory = system
    with pytest.raises(RuntimeError, match="manifest is missing"):
        privacy.erasure_manifest(directory)


def test_real_restore_drill_replays_erasures_without_touching_source(system, monkeypatch):
    from memkit import operations
    from memkit.config import Settings

    conn, team, client, _, directory = system
    add(conn, team)
    with conn.transaction():
        survivor = store.add_memory(
            conn,
            scope_id=team.scope_of("bob"),
            author_id=team.bob_id,
            text="Bob keeps this fact",
            kind="fact",
        )
    settings = Settings(
        database_url=os.environ["MEMKIT_DATABASE_URL"],
        backup_dir=directory / "backups",
        export_dir=directory / "exports",
    )
    _postgres_tools_on_path(monkeypatch)
    artifact = operations.create_backup(settings)
    privacy.erase_user(
        conn,
        client,
        user_id=team.alice_id,
        private_scope_id=team.scope_of("alice"),
        backup_dir=settings.backup_dir,
        export_dir=settings.export_dir,
    )
    report = operations.restore_drill(settings, Path(artifact["path"]))
    assert report["verified"] is True
    assert report["counts"]["users"] == 1
    assert report["counts"]["memories"] == 1
    assert report["counts"]["memory_revisions"] == 1
    assert report["erasures"]["reapplied"] == 1
    assert str(conn.execute("SELECT id FROM memories").fetchone()["id"]) == survivor
    assert not conn.execute(
        "SELECT datname FROM pg_database WHERE datname LIKE 'memkit_restore_%'"
    ).fetchall()


def test_archive_verification_reads_beyond_table_of_contents(system, monkeypatch):
    import subprocess

    from memkit import operations
    from memkit.config import Settings

    conn, team, _, _, directory = system
    add(conn, team)
    settings = Settings(
        database_url=os.environ["MEMKIT_DATABASE_URL"], backup_dir=directory / "backups"
    )
    _postgres_tools_on_path(monkeypatch)
    artifact = operations.create_backup(settings)
    archive = Path(artifact["path"])
    truncated = directory / "truncated.dump"
    truncated.write_bytes(archive.read_bytes()[:-100])
    # The old check accepts this file: compressed table bodies lie after the TOC.
    operations._run([operations._tool("pg_restore"), "--list", str(truncated)])
    with pytest.raises(subprocess.CalledProcessError):
        operations.verify_backup(truncated)


def _postgres_tools_on_path(monkeypatch):
    """Use the PostgreSQL installation the isolated test fixture discovered."""
    from tests.conftest import _pg_bin

    binary_dir = os.environ.get("MEMKIT_TEST_PG_CLIENT_BIN") or _pg_bin()
    if binary_dir:
        monkeypatch.setenv("PATH", binary_dir + os.pathsep + os.environ["PATH"])


def test_existing_backups_require_an_explicit_audited_manifest(system):
    from memkit import operations
    from memkit.config import Settings

    _, team, _, _, directory = system
    backup_dir = directory / "backups"
    backup_dir.mkdir()
    (backup_dir / "historic.dump").write_bytes(b"prior backup")
    with pytest.raises(RuntimeError, match="audit prior erasures"):
        privacy.ensure_erasure_manifest(backup_dir)
    settings = Settings(database_url=os.environ["MEMKIT_DATABASE_URL"], backup_dir=backup_dir)
    with pytest.raises(ValueError, match="confirm BASELINE"):
        operations.initialize_erasure_manifest(settings, confirm="")
    receipt = {"user_id": team.alice_id, "private_scope_id": team.scope_of("alice")}
    result = operations.initialize_erasure_manifest(
        settings, confirm="BASELINE", receipts=[receipt]
    )
    assert result["receipts"] == 1
    assert privacy.erasure_manifest(backup_dir)[0]["user_id"] == team.alice_id


def test_erasure_does_not_treat_a_changed_backup_directory_as_a_fresh_install(system):
    import uuid

    conn, team, client, _, directory = system
    memory_id = add(conn, team)
    conn.execute(
        "INSERT INTO backup_artifacts(id,path,kind,sha256,bytes) VALUES (%s,%s,'full','old',1)",
        (str(uuid.uuid4()), "/previous-volume/retained.dump"),
    )
    with pytest.raises(RuntimeError, match="audit prior erasures"):
        privacy.erase_user(
            conn,
            client,
            user_id=team.alice_id,
            private_scope_id=team.scope_of("alice"),
            export_dir=directory / "exports",
            backup_dir=directory / "new-backups",
        )
    assert conn.execute("SELECT 1 FROM memories WHERE id=%s", (memory_id,)).fetchone()


def test_erasure_revises_and_reindexes_surviving_subject_references(system):
    conn, team, client, embedder, directory = system
    erased_scope = team.scope_of("alice")
    memory_id = store.add_memory(
        conn,
        scope_id=team.team_id,
        author_id=team.bob_id,
        subject_id=team.scope_of("alice"),
        text="Bob recorded a team decision",
        kind="fact",
    )
    outbox.drain(conn, client, embedder)
    privacy.erase_user(
        conn,
        client,
        user_id=team.alice_id,
        private_scope_id=team.scope_of("alice"),
        export_dir=directory / "exports",
        backup_dir=directory / "backups",
    )
    outbox.drain(conn, client, embedder)
    row = conn.execute("SELECT * FROM memories WHERE id=%s", (memory_id,)).fetchone()
    assert row["revision"] == 2
    assert row["subject_id"] is None
    assert row["text"] == "Bob recorded a team decision"
    revisions = conn.execute(
        "SELECT subject_id FROM memory_revisions WHERE memory_id=%s ORDER BY revision", (memory_id,)
    ).fetchall()
    assert str(revisions[0]["subject_id"]) == erased_scope
    assert revisions[1]["subject_id"] is None
    assert client.points[memory_id]["subject_id"] is None


def test_export_preserves_revision_evidence_links(system):
    import hashlib

    from memkit import extract

    conn, team, _, _, directory = system
    content = "A traceable claim with its original exact source"
    message_id, _, _ = store.add_message(
        conn,
        session_id="export-evidence",
        user_id=team.alice_id,
        scope_id=team.scope_of("alice"),
        agent_id="test",
        role="user",
        content=content,
    )
    memory_id = add(conn, team, content)
    with conn.transaction():
        extract._link_evidence(
            conn,
            memory_id,
            [
                {
                    "message_id": message_id,
                    "start_char": 0,
                    "end_char": len(content),
                    "excerpt_sha256": hashlib.sha256(content.encode()).hexdigest(),
                }
            ],
        )
    exported = privacy.export_user(
        conn,
        user_id=team.alice_id,
        private_scope_id=team.scope_of("alice"),
        export_dir=directory / "exports",
    )
    payload = json.loads(Path(exported["path"]).read_text())
    assert payload["memory_revision_evidence"] == [
        {
            "memory_id": memory_id,
            "revision": 1,
            "message_id": message_id,
            "start_char": 0,
            "end_char": len(content),
        }
    ]
    assert exported["memory_revision_evidence"] == 1


def test_direct_erasure_is_claimed_until_its_external_cleanup_finishes(system):
    conn, team, client, _, directory = system
    original = vectors.erase_user_indices

    def check_claim(*args, **kwargs):
        row = conn.execute("SELECT id,status,holder FROM jobs WHERE kind='erase'").fetchone()
        assert row["status"] == "running"
        assert row["holder"]
        with (
            connect(os.environ["MEMKIT_DATABASE_URL"]) as other,
            pytest.raises(RuntimeError, match="not queued"),
        ):
            jobs.claim(other, str(row["id"]))
        return original(*args, **kwargs)

    with patch.object(vectors, "erase_user_indices", side_effect=check_claim):
        privacy.erase_user(
            conn,
            client,
            user_id=team.alice_id,
            private_scope_id=team.scope_of("alice"),
            export_dir=directory / "exports",
            backup_dir=directory / "backups",
        )
    row = conn.execute("SELECT id,status,holder FROM jobs WHERE kind='erase'").fetchone()
    assert row["status"] == "complete"
    assert row["holder"] is None
    events = conn.execute(
        "SELECT status FROM job_events WHERE job_id=%s ORDER BY id", (row["id"],)
    ).fetchall()
    assert [event["status"] for event in events] == ["queued", "running", "complete"]


def test_reindex_job_fence_is_held_through_alias_activation(system):
    import psycopg

    conn, team, client, embedder, _ = system
    add(conn, team)
    job_id = jobs.create(conn, kind="reindex")
    holder = str(jobs.claim(conn, job_id)["holder"])
    original = vectors.swap_aliases

    def activation(*args):
        with (
            connect(os.environ["MEMKIT_DATABASE_URL"]) as other,
            pytest.raises(psycopg.errors.LockNotAvailable),
        ):
            other.execute("SELECT id FROM jobs WHERE id=%s FOR UPDATE NOWAIT", (job_id,))
        return original(*args)

    with patch.object(vectors, "swap_aliases", side_effect=activation):
        report = reindex.rebuild(
            conn, client, embedder, guard=lambda: jobs.require_current(conn, job_id, holder)
        )
    assert report["activated"]


def test_offline_erasure_replay_upgrades_a_restored_v1_database(system):
    from memkit import db, operations
    from memkit.config import Settings

    conn, team, _, _, directory = system
    backup_dir = directory / "backups"
    privacy.initialize_erasure_manifest(
        backup_dir,
        [
            {
                "user_id": team.alice_id,
                "private_scope_id": team.scope_of("alice"),
            }
        ],
    )
    conn.execute("DROP TABLE memory_revision_evidence")
    conn.execute("ALTER TABLE jobs DROP COLUMN available_at")
    conn.execute("DELETE FROM schema_migrations WHERE version=2")
    settings = Settings(database_url=os.environ["MEMKIT_DATABASE_URL"], backup_dir=backup_dir)
    try:
        result = operations.replay_erasures(settings)
        assert result == {"receipts": 1, "reapplied": 1}
        assert conn.execute("SELECT 1 FROM users WHERE id=%s", (team.alice_id,)).fetchone() is None
        assert conn.execute("SELECT 1 FROM users WHERE id=%s", (team.bob_id,)).fetchone()
        db._verify_migration_history(conn)
    finally:
        db.init_db(os.environ["MEMKIT_DATABASE_URL"])


def test_accepted_erasure_retries_a_transient_database_failure(system):
    import psycopg

    conn, team, client, _, directory = system
    memory_id = add(conn, team)
    with (
        patch.object(privacy, "_erase_database", side_effect=psycopg.OperationalError("retryable")),
        pytest.raises(privacy.ErasureCleanupPending),
    ):
        privacy.erase_user(
            conn,
            client,
            user_id=team.alice_id,
            private_scope_id=team.scope_of("alice"),
            export_dir=directory / "exports",
            backup_dir=directory / "backups",
        )
    job = conn.execute("SELECT * FROM jobs WHERE kind='erase'").fetchone()
    assert job["status"] == "queued"
    assert job["input"]["erasure"]["accepted"]
    assert not job["input"]["erasure"]["database_erased"]
    assert conn.execute("SELECT 1 FROM memories WHERE id=%s", (memory_id,)).fetchone()
    assert privacy.erasure_manifest(directory / "backups")[0]["user_id"] == team.alice_id
