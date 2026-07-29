import { describe, expect, it } from "vitest";
import type { TaskBoardItem, TaskWorkflowStatus } from "../api/types";
import { matchesProject, neighbors, placeTask } from "./Tasks";

function task(
  id: string,
  status: TaskWorkflowStatus,
  project: string | null = null,
): TaskBoardItem {
  return {
    id,
    owner_id: "u",
    agent_id: null,
    scope: project ? "project" : "user",
    scope_key: project,
    type: "task",
    text: id,
    importance: 0.6,
    confidence: 0.9,
    status: "active",
    superseded_by: null,
    valid_from: "2026-01-01T00:00:00Z",
    valid_until: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    last_retrieved_at: null,
    retrieval_count: 0,
    extraction_version: "manual",
    judge_run_id: null,
    workflow_status: status,
    project_key: project,
    position: 0,
    board_version: 1,
    board_updated_at: "2026-01-01T00:00:00Z",
  };
}

describe("task board state", () => {
  const items = [
    task("a", "todo", "memkit"),
    task("b", "todo", "other"),
    task("c", "doing", "memkit"),
  ];

  it("filters exact and unknown projects", () => {
    expect(items.filter((item) => matchesProject(item, "memkit")).map((item) => item.id)).toEqual(["a", "c"]);
    expect(matchesProject(task("x", "todo"), "__unknown__")).toBe(true);
  });

  it("moves a task across columns without mutating the source array", () => {
    const moved = placeTask(items, items[0]!, "doing", "c");
    expect(items.map((item) => item.id)).toEqual(["a", "b", "c"]);
    expect(moved.map((item) => `${item.id}:${item.workflow_status}`)).toEqual([
      "b:todo",
      "a:doing",
      "c:doing",
    ]);
  });

  it("computes visible ordering anchors for a filtered project", () => {
    const moved = placeTask(items, items[2]!, "todo", "a");
    expect(neighbors(moved, "c", "todo", "memkit")).toEqual({
      before_id: null,
      after_id: "a",
    });
  });
});
