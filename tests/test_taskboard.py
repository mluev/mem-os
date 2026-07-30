"""Task-board migration, ordering, lifecycle, and retrieval metadata."""

from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from memkit import mutate, retrieval, store, taskboard  # noqa: E402
from memkit.db import connect, init_db, transaction  # noqa: E402
from tests.test_extract import OWNER, StubEmbedder, StubQdrant, make_db  # noqa: E402


class TestTaskBoardMigration(unittest.TestCase):
    def test_v1_database_backfills_unknown_tasks(self):
        path = Path(tempfile.mkdtemp()) / "legacy.db"
        conn = sqlite3.connect(path)
        conn.executescript(
            """
            PRAGMA user_version=1;
            CREATE TABLE owners (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE judge_runs (
                id INTEGER PRIMARY KEY, kind TEXT NOT NULL, model TEXT NOT NULL,
                prompt_version TEXT NOT NULL, input_json TEXT NOT NULL,
                output_json TEXT, error TEXT, input_tokens INTEGER,
                output_tokens INTEGER, cost_usd REAL, latency_ms INTEGER,
                created_at TEXT NOT NULL
            );
            CREATE TABLE memories (
                id TEXT PRIMARY KEY,
                owner_id TEXT NOT NULL REFERENCES owners(id),
                agent_id TEXT, scope TEXT NOT NULL, scope_key TEXT,
                type TEXT NOT NULL, text TEXT NOT NULL, importance REAL NOT NULL,
                confidence REAL NOT NULL, status TEXT NOT NULL,
                superseded_by TEXT REFERENCES memories(id),
                valid_from TEXT NOT NULL, valid_until TEXT,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                last_retrieved_at TEXT, retrieval_count INTEGER NOT NULL DEFAULT 0,
                extraction_version TEXT NOT NULL,
                judge_run_id INTEGER REFERENCES judge_runs(id)
            );
            INSERT INTO owners VALUES ('u-test','test','2026-01-01T00:00:00Z');
            INSERT INTO memories
              (id,owner_id,scope,scope_key,type,text,importance,confidence,status,
               valid_from,created_at,updated_at,extraction_version)
            VALUES
              ('newer','u-test','project','memkit','task','Newer',.5,.9,'active',
               '2026-01-01T00:00:00Z','2026-01-01T00:00:00Z','2026-02-01T00:00:00Z','v1'),
              ('older','u-test','user',NULL,'task','Older',.5,.9,'active',
               '2026-01-01T00:00:00Z','2026-01-01T00:00:00Z','2026-01-01T00:00:00Z','v1');
            """
        )
        conn.commit()
        conn.close()

        init_db(path)
        migrated = connect(path)
        rows = migrated.execute(
            "SELECT * FROM task_board ORDER BY position"
        ).fetchall()
        self.assertEqual([row["memory_id"] for row in rows], ["newer", "older"])
        self.assertEqual(rows[0]["workflow_status"], "unknown")
        self.assertEqual(rows[0]["project_key"], "memkit")
        self.assertIsNone(rows[1]["project_key"])
        self.assertEqual(migrated.execute("PRAGMA user_version").fetchone()[0], 2)


class TestTaskBoard(unittest.TestCase):
    def setUp(self):
        self.conn = make_db()
        self.q = StubQdrant()
        self.embedder = StubEmbedder()

    def add(
        self,
        text: str,
        *,
        status: str = "unknown",
        project: str | None = None,
    ) -> str:
        with transaction(self.conn):
            return store.add_memory(
                self.conn,
                self.q,
                self.embedder,
                owner_id=OWNER,
                text=text,
                type="task",
                scope="project" if project else "user",
                scope_key=project,
                task_status=status,
            )

    def test_board_groups_projects_and_hides_archived_by_default(self):
        active = self.add("Active", status="todo", project="memkit")
        archived = self.add("Archived", status="done")
        with transaction(self.conn):
            result = mutate.set_status(
                self.conn,
                self.q,
                self.embedder,
                memory_id=archived,
                status="expired",
            )
        result.apply_index(self.q)

        board = taskboard.board_data(self.conn, owner_id=OWNER)
        self.assertEqual([item["id"] for item in board["items"]], [active])
        self.assertEqual(board["counts"]["todo"], 1)
        self.assertEqual(board["projects"], [{"key": "memkit", "label": "memkit", "count": 1}])

        with_archive = taskboard.board_data(
            self.conn, owner_id=OWNER, include_archived=True
        )
        self.assertEqual(with_archive["total"], 2)
        self.assertEqual(with_archive["counts"]["done"], 1)

    def test_invalid_direct_status_defaults_every_store_to_unknown(self):
        memory_id = self.add("Unclassified", status="not-a-state")
        board = taskboard._task_row(self.conn, memory_id)
        self.assertEqual(board["workflow_status"], "unknown")
        self.assertEqual(self.q.points[memory_id]["task_status"], "unknown")

    def test_patch_moves_atomically_without_refreshing_memory_timestamp(self):
        first = self.add("First", status="todo")
        moved = self.add("Moved", status="todo")
        before = taskboard._task_row(self.conn, moved)
        request = SimpleNamespace(
            app=SimpleNamespace(
                state=SimpleNamespace(
                    # One connection per thread in production; the tests hand back
                    # the same one, which is all a single-threaded test needs.
                    db=lambda: self.conn,
                    qdrant=self.q,
                    embedder=self.embedder,
                    index_dirty=False,
                )
            )
        )
        response = taskboard.patch_task(
            moved,
            taskboard.TaskPatch(
                workflow_status="doing",
                after_id=None,
                expected_board_version=before["board_version"],
            ),
            request,
        )
        after = response["task"]
        self.assertEqual(after["workflow_status"], "doing")
        self.assertEqual(after["updated_at"], before["updated_at"])
        self.assertEqual(after["board_version"], before["board_version"] + 1)
        self.assertEqual(self.q.points[moved]["task_status"], "doing")
        self.assertEqual(
            taskboard.board_data(self.conn, owner_id=OWNER)["counts"]["doing"], 1
        )
        self.assertIsNotNone(first)

    def test_stale_board_version_is_rejected(self):
        memory_id = self.add("Task")
        row = taskboard._task_row(self.conn, memory_id)
        request = SimpleNamespace(
            app=SimpleNamespace(
                state=SimpleNamespace(
                    # One connection per thread in production; the tests hand back
                    # the same one, which is all a single-threaded test needs.
                    db=lambda: self.conn,
                    qdrant=self.q,
                    embedder=self.embedder,
                    index_dirty=False,
                )
            )
        )
        with self.assertRaises(Exception) as caught:
            taskboard.patch_task(
                memory_id,
                taskboard.TaskPatch(
                    workflow_status="todo",
                    expected_board_version=row["board_version"] + 1,
                ),
                request,
            )
        self.assertEqual(caught.exception.status_code, 409)

    def test_hard_delete_cascades_board_metadata(self):
        memory_id = self.add("Disposable")
        with transaction(self.conn):
            mutate.hard_delete(self.conn, self.q, memory_id=memory_id)
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) n FROM task_board WHERE memory_id=?", (memory_id,)
            ).fetchone()["n"],
            0,
        )

    def test_retrieval_result_exposes_done_status(self):
        hit = SimpleNamespace(
            id="task-1",
            score=0.8,
            vector=None,
            payload={
                "text": "Ship",
                "type": "task",
                "scope": "user",
                "scope_key": None,
                "importance": 0.5,
                "updated_at": "2026-07-28T00:00:00Z",
                "task_status": "done",
            },
        )
        ranked = retrieval.rank(
            [hit], project=None, task=None, now=retrieval.datetime(2026, 7, 28, tzinfo=retrieval.UTC)
        )
        self.assertEqual(ranked[0].as_dict()["task_status"], "done")


if __name__ == "__main__":
    unittest.main()
