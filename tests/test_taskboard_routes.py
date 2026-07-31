"""HTTP contract tests for taskboard.py's three routes.

`tests/test_taskboard.py` covers the ordering algebra and the migration against
the module directly. This covers the HTTP surface: 201 on create, the two
independent optimistic locks, and the fractional-position moves.

The board exists as a separate table so that moving a card does not touch
`memories.updated_at` -- retrieval ages facts from `updated_at`, so a drag would
otherwise make a stale task look fresh. That invariant is asserted here over
HTTP, not just in the unit test.
"""

from __future__ import annotations

import unittest

from tests.httpharness import ApiTestCase

BOARD_KEYS = {"items", "counts", "projects", "total", "include_archived"}
COLUMNS = ("unknown", "todo", "doing", "done")


class TaskRouteCase(ApiTestCase):
    def make_task(self, text="Ship the reconciliation pass", **kw) -> dict:
        r = self.client.post(
            "/v1/admin/tasks", json={"text": text, **kw}, headers=self.auth
        )
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()["task"]

    def board(self, **params) -> dict:
        r = self.client.get(
            "/v1/admin/tasks/board", params=params, headers=self.auth
        )
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def patch_task(self, task, **body):
        body.setdefault("expected_board_version", task["board_version"])
        return self.client.patch(
            f"/v1/admin/tasks/{task['id']}", json=body, headers=self.auth
        )


class TestBoard(TaskRouteCase):
    def test_empty_board_shape(self):
        body = self.board()
        self.assertKeys(body, BOARD_KEYS)
        self.assertEqual(set(body["counts"]), set(COLUMNS))
        self.assertEqual(body["total"], 0)

    def test_created_task_appears_with_its_column(self):
        self.make_task(workflow_status="todo")
        body = self.board()
        self.assertEqual(body["total"], 1)
        self.assertEqual(body["counts"]["todo"], 1)
        self.assertEqual(body["items"][0]["workflow_status"], "todo")

    def test_project_facet_labels_the_unknown_bucket(self):
        self.make_task(text="Task in a project", project_key="memkit")
        self.make_task(text="Task with no project")
        labels = {p["key"]: p["label"] for p in self.board()["projects"]}
        self.assertIn("memkit", labels)
        self.assertIn(None, labels)
        self.assertEqual(labels[None], "Unknown project")

    def test_archived_tasks_are_hidden_by_default(self):
        task = self.make_task()
        self.client.delete(f"/v1/memories/{task['id']}", headers=self.auth)
        self.assertEqual(self.board()["total"], 0)
        self.assertEqual(self.board(include_archived="true")["total"], 1)


class TestCreateTask(TaskRouteCase):
    def test_project_key_drives_the_scope(self):
        with_project = self.make_task(text="Scoped task", project_key="memkit")
        without = self.make_task(text="Unscoped task")
        self.assertEqual(
            self.scalar(
                "SELECT scope FROM memories WHERE id=?", with_project["id"]
            ),
            "project",
        )
        self.assertEqual(
            self.scalar("SELECT scope FROM memories WHERE id=?", without["id"]),
            "user",
        )

    def test_task_status_reaches_the_index_payload(self):
        task = self.make_task(workflow_status="doing")
        self.assertEqual(
            self.qdrant.points[task["id"]]["task_status"], "doing"
        )

    def test_bounds(self):
        for body in ({"text": ""}, {"text": "x" * 201},
                     {"text": "ok", "workflow_status": "blocked"},
                     {"text": "ok", "importance": 1.5}):
            with self.subTest(body=body):
                r = self.client.post("/v1/admin/tasks", json=body, headers=self.auth)
                self.assertEqual(r.status_code, 422)

    def test_only_task_typed_memories_get_a_board_row(self):
        note = self.seed_memory(text="Prefers pnpm", type="preference")
        self.assertEqual(
            self.scalar("SELECT COUNT(*) FROM task_board WHERE memory_id=?", note), 0
        )


class TestPatchTask(TaskRouteCase):
    def test_moving_a_card_does_not_refresh_the_memory(self):
        """The whole reason task_board is a separate table."""
        task = self.make_task(workflow_status="todo")
        before = self.scalar(
            "SELECT updated_at FROM memories WHERE id=?", task["id"]
        )
        r = self.patch_task(task, workflow_status="doing")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["task"]["workflow_status"], "doing")
        self.assertEqual(
            self.scalar("SELECT updated_at FROM memories WHERE id=?",
                        task["id"]),
            before,
            "a drag must not make a stale task look fresh to retrieval",
        )

    def test_board_version_increments_and_stale_is_409(self):
        task = self.make_task()
        moved = self.patch_task(task, workflow_status="todo").json()["task"]
        self.assertGreater(moved["board_version"], task["board_version"])
        # Replay the original version: a second tab that never saw the move.
        stale = self.patch_task(task, workflow_status="doing")
        self.assertEqual(stale.status_code, 409, stale.text)

    def test_expected_board_version_is_required(self):
        task = self.make_task()
        r = self.client.patch(
            f"/v1/admin/tasks/{task['id']}",
            json={"workflow_status": "todo"},
            headers=self.auth,
        )
        self.assertEqual(r.status_code, 422)

    def test_memory_edits_need_their_own_expected_timestamp(self):
        """Two locks, because the two tables move independently.

        422 rather than 409: the request is missing a required field, which is a
        validation problem. A 409 is reserved for a lock that was supplied and
        lost -- see `test_board_version_increments_and_stale_is_409`.
        """
        task = self.make_task()
        r = self.patch_task(task, text="Renamed task")
        self.assertEqual(r.status_code, 422, r.text)
        self.assertIn("expected_memory_updated_at", r.text)

    def test_memory_edit_succeeds_with_both_locks(self):
        task = self.make_task()
        updated_at = self.scalar(
            "SELECT updated_at FROM memories WHERE id=?", task["id"]
        )
        r = self.patch_task(
            task, text="Renamed task", expected_memory_updated_at=updated_at
        )
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["task"]["text"], "Renamed task")

    def test_reordering_within_a_column(self):
        first = self.make_task(text="First task", workflow_status="todo")
        second = self.make_task(text="Second task", workflow_status="todo")
        third = self.make_task(text="Third task", workflow_status="todo")
        order = [i["id"] for i in self.board()["items"]]
        # Newest goes to the top of the column.
        self.assertEqual(
            order, [third["id"], second["id"], first["id"]]
        )
        # Anchors are positional, and position ascends down the column:
        # before_id is the card above the target slot, after_id the one below.
        r = self.patch_task(
            third, workflow_status="todo",
            before_id=second["id"], after_id=first["id"],
        )
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(
            [i["id"] for i in self.board()["items"]],
            [second["id"], third["id"], first["id"]],
        )

    def test_reversed_anchors_are_refused(self):
        """The guard that caught my own mistake writing the test above."""
        first = self.make_task(text="First task", workflow_status="todo")
        second = self.make_task(text="Second task", workflow_status="todo")
        third = self.make_task(text="Third task", workflow_status="todo")
        r = self.patch_task(
            third, workflow_status="todo",
            before_id=first["id"], after_id=second["id"],
        )
        self.assertEqual(r.status_code, 422, r.text)
        self.assertIn("reversed", r.text)

    def test_anchor_outside_the_target_column_is_refused(self):
        todo = self.make_task(text="A todo task", workflow_status="todo")
        doing = self.make_task(text="A doing task", workflow_status="doing")
        r = self.patch_task(todo, workflow_status="todo", before_id=doing["id"])
        self.assertEqual(r.status_code, 422, r.text)

    def test_a_task_cannot_be_its_own_anchor(self):
        task = self.make_task(workflow_status="todo")
        r = self.patch_task(
            task, workflow_status="todo", before_id=task["id"]
        )
        self.assertEqual(r.status_code, 422, r.text)

    def test_archived_task_must_be_restored_before_editing(self):
        task = self.make_task()
        self.client.delete(f"/v1/memories/{task['id']}", headers=self.auth)
        r = self.patch_task(task, workflow_status="todo")
        self.assertEqual(r.status_code, 409, r.text)

    def test_unknown_task_is_404(self):
        r = self.client.patch(
            "/v1/admin/tasks/nope",
            json={"workflow_status": "todo", "expected_board_version": 1},
            headers=self.auth,
        )
        self.assertEqual(r.status_code, 404)


if __name__ == "__main__":
    unittest.main()
