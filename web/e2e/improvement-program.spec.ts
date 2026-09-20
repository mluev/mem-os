import { expect, test, type Page, type Route } from "@playwright/test";
import type { TeamMemory } from "../src/api/types";

const health = { database: { schema_version: 1 }, qdrant: { available: true, memories: 1, raw: 1 }, embedder: { ready: true, device: "cpu", revision: "revision" }, outbox: { pending: 0 }, jobs: {} };
const scope = { id: "alice-space", slug: "alice", name: "Alice", kind: "user", writable: true };
const me = { id: "alice-id", user_id: "alice-id", handle: "alice", display_name: "Alice", role: "admin", own_entity_id: scope.id, scopes: [scope] };
const memory: TeamMemory = { id: "m1", text: "Use pnpm for this project", kind: "preference", context: {}, tags: [], source_role: "user", status: "active", review_status: "pending", importance: 0.6, confidence: 0.9, revision: 1, scope: "Alice", scope_slug: "alice", subject: null, subject_slug: null, author: "Alice", created_at: "2026-09-20T00:00:00Z", updated_at: "2026-09-20T00:00:00Z", valid_until: null, writable: true };

async function mockApi(page: Page, handler: (route: Route, path: string) => Promise<boolean>) {
  await page.route("**/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (await handler(route, path)) return;
    if (path === "/v1/auth/me") return route.fulfill({ json: me });
    if (path === "/v1/admin/health") return route.fulfill({ json: health });
    if (path.startsWith("/v1/admin/stats/")) return route.fulfill({ json: { start: "2026-09-01", end: "2026-09-20", totals: { pending: 0 }, series: [] } });
    if (path === "/v1/memories") return route.fulfill({ json: { items: [memory], total: 1, limit: 50, offset: 0 } });
    if (path === "/v1/memories/m1") return route.fulfill({ json: { memory } });
    if (path === "/v1/entities") return route.fulfill({ json: { items: [] } });
    if (path === "/v1/jobs") return route.fulfill({ json: { items: [], next_cursor: null } });
    await route.fulfill({ status: 500, json: { detail: `Unmocked endpoint: ${path}` } });
  });
}

test("records useful search feedback", async ({ page }) => {
  let feedback: unknown;
  await mockApi(page, async (route, path) => {
    if (path === "/v1/memories/search") {
      await route.fulfill({ json: { retrieval_id: "run-1", memories: [{ ...memory, score: 0.9, similarity: 0.8, lexical: 1 }], raw: [], used_tokens: 5, policy_id: "neutral-v1", timings: { total_ms: 12 }, took_ms: 12 } });
      return true;
    }
    if (path === "/v1/retrieval-runs/run-1/feedback") {
      feedback = route.request().postDataJSON();
      expect(route.request().headers()["x-requested-with"]).toBe("memkit");
      await route.fulfill({ status: 201, json: { recorded: true } });
      return true;
    }
    return false;
  });
  await page.goto("/ui/search");
  await page.getByLabel("Query").fill("package manager");
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await page.getByRole("button", { name: "Useful" }).click();
  await expect.poll(() => feedback).toEqual({ memory_id: "m1", useful: true, correct: true });
});

test("shows a failed evidence check without quoting the altered span", async ({ page }) => {
  await mockApi(page, async (route, path) => {
    if (path !== "/v1/memories/m1/sources") return false;
    await route.fulfill({ json: { memory, source_role: "user", evidence: [{ message_id: 1, start_char: 0, end_char: 13, excerpt: "ALTERED WORDS", verified: false, role: "user", created_at: memory.created_at }] } });
    return true;
  });
  await page.goto("/ui/memories?memory=m1");
  await page.getByRole("tab", { name: "Evidence", exact: true }).click();
  await expect(page.getByText("1 span · 1 could not be verified")).toBeVisible();
  await expect(page.getByRole("alert")).toContainText("no longer matches");
  await expect(page.getByText("ALTERED WORDS")).not.toBeVisible();
});

test("retains my wording after a conflict and saves against the fresh revision", async ({ page }) => {
  let current = { ...memory };
  const patches: unknown[] = [];
  await mockApi(page, async (route, path) => {
    if (path !== "/v1/memories/m1") return false;
    if (route.request().method() === "PATCH") {
      const patch = route.request().postDataJSON();
      patches.push(patch);
      if (patches.length === 1) {
        current = { ...memory, text: "Someone else's wording", revision: 2 };
        await route.fulfill({ status: 409, json: { detail: "revision conflict" } });
      } else {
        current = { ...current, text: patch.text, revision: 3 };
        await route.fulfill({ json: { revision: 3 } });
      }
    } else await route.fulfill({ json: { memory: current } });
    return true;
  });
  await page.goto("/ui/memories?memory=m1");
  await page.getByLabel("Memory", { exact: true }).fill("My revised wording");
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByRole("heading", { name: "Someone else edited this fact" })).toBeVisible();
  await expect(page.getByLabel("Memory", { exact: true })).toHaveValue("My revised wording");
  await page.getByRole("button", { name: "Keep mine" }).click();
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect.poll(() => patches).toEqual([{ text: "My revised wording", expected_revision: 1 }, { text: "My revised wording", expected_revision: 2 }]);
});

test("does not reuse one person's memory cache after another person signs in", async ({ page }) => {
  let who = "alice";
  let reads = 0;
  await mockApi(page, async (route, path) => {
    if (path === "/v1/auth/me") {
      await route.fulfill({ json: { ...me, handle: who, display_name: who } });
    } else if (path === "/v1/auth/logout") {
      await route.fulfill({ status: 204 });
    } else if (path === "/v1/auth/login") {
      who = route.request().postDataJSON().handle;
      await route.fulfill({ json: {} });
    } else if (path === "/v1/memories") {
      reads += 1;
      await route.fulfill({ json: { items: [{ ...memory, text: `${who} private memory` }], total: 1, limit: 50, offset: 0 } });
    } else return false;
    return true;
  });
  await page.goto("/ui/memories");
  await expect(page.getByText("alice private memory", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await page.getByLabel("Handle", { exact: true }).fill("bob");
  await page.getByLabel("Password", { exact: true }).fill("test-password");
  await page.getByRole("button", { name: "Open dashboard" }).click();
  await expect(page.getByText("bob private memory", { exact: true })).toBeVisible();
  await expect(page.getByText("alice private memory", { exact: true })).not.toBeAttached();
  expect(reads).toBe(2);
});

test("restores a review item when its revision changed", async ({ page }) => {
  let decision: unknown;
  await mockApi(page, async (route, path) => {
    if (path === "/v1/review") {
      await route.fulfill({ json: { items: [{ id: "m1", kind: "memory", title: memory.text, memory, actions: ["confirm", "decline"] }] } });
    } else if (path === "/v1/memories/m1/review") {
      decision = route.request().postDataJSON();
      await route.fulfill({ status: 409, json: { detail: "The memory changed before review" } });
    } else return false;
    return true;
  });
  await page.goto("/ui/review");
  await expect(page.getByText(memory.text, { exact: true })).toBeVisible();
  await page.keyboard.press("a");
  await expect.poll(() => decision).toEqual({ decision: "confirm", expected_revision: 1 });
  await expect(page.getByText("The memory changed before review")).toBeVisible();
  await expect(page.getByText(memory.text, { exact: true })).toBeVisible();
});

test("shows protected backups and only offers the supported re-extraction report", async ({ page }) => {
  let body: string | null | undefined;
  await mockApi(page, async (route, path) => {
    if (path === "/v1/admin/metrics") {
      await route.fulfill({ json: { month_spend_usd: 0, month_reserved_usd: 0, feedback_labels: 0, search_latency_ms: { p95: 20 }, index_parity: { matches: true }, backup_freshness_seconds: 60 } });
    } else if (path === "/v1/admin/backups") {
      await route.fulfill({ json: { items: [{ id: "b1", kind: "daily", verified_at: memory.created_at, protected: true }] } });
    } else if (path === "/v1/admin/reextract") {
      body = route.request().postData();
      await route.fulfill({ status: 202, json: { job_id: "report-1", status: "queued" } });
    } else return false;
    return true;
  });
  await page.goto("/ui/ops");
  await expect(page.getByRole("heading", { name: "Verified backups" })).toBeVisible();
  await expect(page.getByText("protected", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Start v7 review batch" })).not.toBeAttached();
  await page.getByRole("button", { name: "Re-extraction report" }).click();
  await expect.poll(() => body).toBeNull();
  await expect(page.getByText("Job report-1 queued")).toBeVisible();
});
