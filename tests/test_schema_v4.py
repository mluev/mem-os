"""Schema-v4 boundary and migration acceptance tests."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from memkit import db

LEGACY_V3 = """
PRAGMA foreign_keys=ON;
CREATE TABLE owners (id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE sessions (
    id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES owners(id),
    agent_id TEXT NOT NULL, started_at TEXT NOT NULL, ended_at TEXT, meta TEXT
);
CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id), role TEXT NOT NULL,
    content TEXT NOT NULL, created_at TEXT NOT NULL, processed INTEGER NOT NULL DEFAULT 0,
    external_source TEXT, external_id TEXT
);
CREATE TABLE judge_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, model TEXT NOT NULL,
    prompt_version TEXT NOT NULL, input_json TEXT NOT NULL, output_json TEXT,
    error TEXT, input_tokens INTEGER, output_tokens INTEGER, cost_usd REAL,
    latency_ms INTEGER, created_at TEXT NOT NULL
);
CREATE TABLE memories (
    id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES owners(id), agent_id TEXT,
    scope TEXT NOT NULL, scope_key TEXT, type TEXT NOT NULL, text TEXT NOT NULL,
    importance REAL NOT NULL, confidence REAL NOT NULL, status TEXT NOT NULL,
    superseded_by TEXT REFERENCES memories(id), valid_from TEXT NOT NULL,
    valid_until TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    last_retrieved_at TEXT, retrieval_count INTEGER NOT NULL DEFAULT 0,
    extraction_version TEXT NOT NULL, judge_run_id INTEGER REFERENCES judge_runs(id),
    source_role TEXT NOT NULL
);
CREATE TABLE task_board (
    memory_id TEXT PRIMARY KEY REFERENCES memories(id) ON DELETE CASCADE,
    workflow_status TEXT NOT NULL, project_key TEXT, position REAL NOT NULL,
    version INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE memory_sources (
    memory_id TEXT NOT NULL REFERENCES memories(id),
    message_id INTEGER NOT NULL REFERENCES messages(id), PRIMARY KEY(memory_id, message_id)
);
PRAGMA user_version=3;
"""


class TestSchemaV4(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="memkit-v4-"))
        self.path = self.root / "memkit.db"

    def _legacy_database(self) -> None:
        conn = sqlite3.connect(self.path)
        conn.executescript(LEGACY_V3)
        now = "2026-08-09T00:00:00Z"
        conn.execute("INSERT INTO owners VALUES ('u-1','owner',?)", (now,))
        rows = [
            (
                "m-task",
                "u-1",
                "chat",
                "project",
                "mem-os",
                "task",
                "Ship the audit repair",
                0.8,
                0.9,
                "active",
                None,
                now,
                "2026-08-10T00:00:00Z",
                now,
                now,
                None,
                0,
                "v3",
                None,
                "user",
            ),
            (
                "m-pref",
                "u-1",
                "chat",
                "project",
                "mem-os",
                "preference",
                "Prefers pnpm",
                0.8,
                0.9,
                "active",
                None,
                now,
                None,
                now,
                now,
                None,
                0,
                "v3",
                None,
                "user",
            ),
            (
                "m-long",
                "u-1",
                "chat",
                "user",
                None,
                "fact",
                "x" * 2161,
                0.5,
                0.8,
                "active",
                None,
                now,
                None,
                now,
                now,
                None,
                0,
                "v3",
                None,
                "user",
            ),
        ]
        conn.executemany(
            "INSERT INTO memories VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
        conn.execute(
            "INSERT INTO task_board VALUES ('m-task','doing','mem-os',1024,3,?,?)",
            (now, now),
        )
        conn.commit()
        conn.close()

    def test_v3_upgrade_exports_and_retires_tasks(self) -> None:
        self._legacy_database()
        db.init_db(self.path)

        conn = db.connect(self.path)
        self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 4)
        tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        self.assertNotIn("task_board", tables)
        self.assertIn("index_outbox", tables)
        self.assertIn("jobs", tables)
        self.assertIn("namespaces", tables)

        columns = {row[1] for row in conn.execute("PRAGMA table_info(memories)")}
        self.assertNotIn("type", columns)
        self.assertNotIn("scope", columns)
        self.assertNotIn("scope_key", columns)
        self.assertTrue({"kind", "context_json", "tags_json", "redacted"} <= columns)

        task = conn.execute("SELECT * FROM memories WHERE id='m-task'").fetchone()
        self.assertEqual(task["kind"], "observation")
        self.assertEqual(task["status"], "archived")
        self.assertIsNone(task["valid_until"])

        overlong = conn.execute("SELECT * FROM memories WHERE id='m-long'").fetchone()
        self.assertEqual(len(overlong["text"]), 2161)
        self.assertEqual(overlong["legacy_imported"], 1)
        pref = conn.execute("SELECT * FROM memories WHERE id='m-pref'").fetchone()
        self.assertEqual(pref["kind"], "preference")
        self.assertEqual(json.loads(pref["context_json"]), {"source_workspace": "mem-os"})

        backup = self.path.with_suffix(".db.v3.bak")
        export = self.root / "exports" / "task-board-v3.json"
        self.assertTrue(backup.is_file())
        payload = json.loads(export.read_text())
        self.assertEqual(payload["schema_version"], 3)
        self.assertEqual(payload["tasks"][0]["memory_id"], "m-task")
        self.assertEqual(payload["tasks"][0]["due_at"], "2026-08-10T00:00:00Z")

    def test_fresh_schema_has_defence_in_depth_constraints(self) -> None:
        db.init_db(self.path)
        conn = db.connect(self.path)
        db.ensure_owner(conn, "u-1", "owner")
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute(
                """INSERT INTO memories
                   (id,owner_id,kind,text,importance,confidence,status,valid_from,
                    created_at,updated_at,extraction_version,source_role,context_json,tags_json)
                   VALUES ('bad','u-1','fact','   ',2,0.5,'active','x','x','x','manual',
                           'manual','{}','[]')"""
            )


if __name__ == "__main__":
    unittest.main()
