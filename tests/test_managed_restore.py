"""Execute the managed restore payload against isolated real databases."""

import ast
import contextlib
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo

from memkit import db, privacy, store
from tests.conftest import _pg_bin
from tests.fixtures import StubQdrant, seed_team


def payload(name):
    worker = Path(__file__).resolve().parents[1] / "cli/src/memos_cli/assets/server_worker.py"
    module = ast.parse(worker.read_text())
    return next(
        ast.literal_eval(node.value)
        for node in module.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == name for target in node.targets)
    )


@pytest.fixture
def managed_database(database_url):
    name = f"restore_test_{uuid.uuid4().hex[:12]}"
    target = make_conninfo(database_url, dbname=name)
    with db.connect(database_url) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        db.init_db(target)
        try:
            yield target
        finally:
            # The payload preserves the former database under a different name.
            for row in admin.execute(
                "SELECT datname FROM pg_database WHERE datname=%s OR starts_with(datname,%s)",
                (name, name + "_"),
            ).fetchall():
                admin.execute(
                    sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(row["datname"]))
                )


def environment(target, tmp_path):
    return dict(
        os.environ,
        MEMKIT_DATABASE_URL=target,
        MEMKIT_BACKUP_DIR=str(tmp_path / "backups"),
        MEMKIT_EXPORT_DIR=str(tmp_path / "exports"),
        PATH=os.pathsep.join(
            [
                os.environ.get("MEMKIT_TEST_PG_CLIENT_BIN") or _pg_bin() or "",
                os.environ.get("PATH", ""),
            ]
        ),
    )


def snapshot(target, tmp_path):
    archive = tmp_path / "snapshot.dump"
    subprocess.run(  # noqa: S603
        ["pg_dump", "--format=custom", f"--dbname={target}", f"--file={archive}"],  # noqa: S607
        env=environment(target, tmp_path),
        check=True,
        capture_output=True,
        timeout=30,
    )
    return archive


def restore(target, tmp_path, archive, *, prelude=""):
    return subprocess.run(  # noqa: S603
        [sys.executable, "-c", prelude + payload("RESTORE"), str(archive)],
        env=environment(target, tmp_path),
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_remote_restore_replaces_database_and_preserves_original(managed_database, tmp_path):
    target = managed_database
    privacy.initialize_erasure_manifest(tmp_path / "backups", [])
    with db.connect(target) as conn:
        conn.execute("CREATE TABLE restore_probe (text text)")
        conn.execute("INSERT INTO restore_probe VALUES ('before backup')")
        archive = snapshot(target, tmp_path)
        conn.execute("INSERT INTO restore_probe VALUES ('after backup')")
    result = restore(target, tmp_path, archive)
    assert result.returncode == 0, result.stderr
    original = json.loads(result.stdout)["retained_database"]
    with db.connect(target) as conn:
        assert [row["text"] for row in conn.execute("SELECT text FROM restore_probe")] == [
            "before backup"
        ]
        enabled = conn.execute(
            "SELECT datallowconn FROM pg_database WHERE datname=%s", (original,)
        ).fetchone()
        assert enabled["datallowconn"] is False
        conn.execute(
            sql.SQL("ALTER DATABASE {} ALLOW_CONNECTIONS true").format(sql.Identifier(original))
        )
    with db.connect(make_conninfo(target, dbname=original)) as previous:
        assert previous.execute("SELECT count(*) AS n FROM restore_probe").fetchone()["n"] == 2


def test_remote_restore_migrates_v1_then_replays_latest_erasure(managed_database, tmp_path):
    target = managed_database
    privacy.initialize_erasure_manifest(tmp_path / "backups", [])
    with db.connect(target) as conn:
        team = seed_team(conn)
        scope = team.scope_of("alice")
        store.add_memory(
            conn, scope_id=scope, author_id=team.alice_id, text="erase this", kind="fact"
        )
        conn.execute("DROP TABLE memory_revision_evidence")
        conn.execute("ALTER TABLE jobs DROP COLUMN available_at")
        conn.execute("DELETE FROM schema_migrations WHERE version=2")
        archive = snapshot(target, tmp_path)
    db.init_db(target)
    with db.connect(target) as conn:
        # A populated v2-only FK makes the old in-place --clean restore fail.
        bob_scope = str(
            conn.execute("SELECT id FROM entities WHERE user_id=%s", (team.bob_id,)).fetchone()[
                "id"
            ]
        )
        memory = store.add_memory(
            conn, scope_id=bob_scope, author_id=team.bob_id, text="later", kind="fact"
        )
        message, _, _ = store.add_message(
            conn,
            session_id="after-backup",
            user_id=team.bob_id,
            scope_id=bob_scope,
            agent_id="chat",
            role="user",
            content="later",
        )
        conn.execute("INSERT INTO memory_evidence VALUES (%s,%s,0,5,'fixture')", (memory, message))
        conn.execute("INSERT INTO memory_revision_evidence VALUES (%s,1,%s,0,5)", (memory, message))
        privacy.erase_user(
            conn,
            StubQdrant(),
            user_id=team.alice_id,
            private_scope_id=scope,
            backup_dir=tmp_path / "backups",
            export_dir=tmp_path / "exports",
        )
    result = restore(target, tmp_path, archive)
    assert result.returncode == 0, result.stderr
    with db.connect(target) as conn:
        db._verify_migration_history(conn)
        assert not conn.execute("SELECT 1 FROM users WHERE id=%s", (team.alice_id,)).fetchone()
        assert conn.execute("SELECT 1 FROM users WHERE id=%s", (team.bob_id,)).fetchone()
        assert conn.execute("SELECT count(*) AS n FROM memories").fetchone()["n"] == 0


def test_remote_restore_missing_manifest_does_not_replace_original(managed_database, tmp_path):
    target = managed_database
    archive = snapshot(target, tmp_path)
    with db.connect(target) as conn:
        conn.execute("CREATE TABLE keep_original (id integer)")
    result = restore(target, tmp_path, archive)
    assert result.returncode != 0
    assert "manifest" in result.stderr
    with db.connect(target) as conn:
        assert conn.execute("SELECT to_regclass('keep_original') AS t").fetchone()["t"]


def test_restore_refuses_late_database_client_and_restores_connection_gate(
    managed_database, tmp_path
):
    target = managed_database
    privacy.initialize_erasure_manifest(tmp_path / "backups", [])
    archive = snapshot(target, tmp_path)
    with db.connect(target) as writer:
        writer.execute("CREATE TABLE keep_original (id integer)")
        result = restore(target, tmp_path, archive)
        assert result.returncode != 0
        assert "Other database clients remain" in result.stderr
        assert writer.execute("SELECT to_regclass('keep_original') AS t").fetchone()["t"]
    with db.connect(target) as conn:
        assert conn.execute("SELECT to_regclass('keep_original') AS t").fetchone()["t"]
        assert not conn.execute(
            "SELECT 1 FROM pg_database WHERE starts_with(datname,%s)", (conn.info.dbname + "_",)
        ).fetchone()


def test_restore_cleanup_removes_all_managed_generations_and_exports(tmp_path, monkeypatch):
    from memkit import config, vectors

    class Collections(StubQdrant):
        def delete_collection(self, collection_name, **kwargs):
            del self._store[collection_name]

    client = Collections()
    client._store.update({"memories__g123": {}, "raw__g456": {}, "other_service": {}})
    exports = tmp_path / "exports"
    exports.mkdir()
    (exports / "private.json").write_text("private export")
    outside = tmp_path / "unrelated.json"
    outside.write_text("keep")
    (exports / "link.json").symlink_to(outside)
    monkeypatch.setattr(vectors, "get_client", lambda _: client)
    monkeypatch.setattr(config, "get_settings", lambda: config.Settings(export_dir=exports))
    with contextlib.redirect_stdout(None):
        exec(payload("RESTORE_CLEANUP"), {"__name__": "__main__"})  # noqa: S102
    assert set(client._store) == {"other_service"}
    assert list(exports.iterdir()) == []
    assert outside.read_text() == "keep"


def test_database_switch_rolls_back_both_names_on_second_rename_failure(managed_database, tmp_path):
    target = managed_database
    privacy.initialize_erasure_manifest(tmp_path / "backups", [])
    archive = snapshot(target, tmp_path)
    with db.connect(target) as conn:
        conn.execute("CREATE TABLE keep_original (id integer)")
    prelude = """from memkit import db
original_connect=db.connect
renames=[]
class FailingConnection:
 def __init__(self,conn): self.conn=conn
 def __getattr__(self,name): return getattr(self.conn,name)
 def __enter__(self): return self
 def __exit__(self,*args): return self.conn.__exit__(*args)
 def execute(self,query,*args,**kwargs):
  text=query.as_string(self.conn) if hasattr(query,'as_string') else query
  if ' RENAME TO ' in text:
   renames.append(text)
   if len(renames)==2: raise RuntimeError('injected second rename failure')
  return self.conn.execute(query,*args,**kwargs)
db.connect=lambda dsn: FailingConnection(original_connect(dsn))
"""
    result = restore(target, tmp_path, archive, prelude=prelude)
    assert result.returncode != 0
    assert "injected second rename failure" in result.stderr
    with db.connect(target) as conn:
        assert conn.execute("SELECT to_regclass('keep_original') AS t").fetchone()["t"]
        assert not conn.execute(
            "SELECT 1 FROM pg_database WHERE starts_with(datname,%s)", (conn.info.dbname + "_",)
        ).fetchone()


@pytest.mark.parametrize("has_manifest", [False, True])
def test_legacy_image_restore_refuses_receipts_it_cannot_replay(
    managed_database, tmp_path, has_manifest
):
    target = managed_database
    with db.connect(target) as conn:
        conn.execute("DROP TABLE memory_revision_evidence")
        conn.execute("ALTER TABLE jobs DROP COLUMN available_at")
        conn.execute("DELETE FROM schema_migrations WHERE version=2")
    archive = snapshot(target, tmp_path)
    if has_manifest:
        privacy.initialize_erasure_manifest(tmp_path / "backups", [])
    # Represent the old image's schema and lack of replay support, while using
    # the exact same restore payload and a real v1 archive/database.
    prelude = """from memkit import db,operations
del operations.replay_erasures
db.SCHEMA_VERSION=1
db.MIGRATIONS={1:db.DDL_V1}
"""
    result = restore(target, tmp_path, archive, prelude=prelude)
    if has_manifest:
        assert result.returncode != 0
        assert "cannot replay retained erasure receipts" in result.stderr
    else:
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)["retained_database"]
