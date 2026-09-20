import { expect, test, type Page, type Route } from "@playwright/test";
import type { components } from "../src/api/schema";
import { backups, health, judge, me, memory, metrics, reviewStats, searchResult, session } from "./fixtures";

type Schema = components["schemas"];

async function mockApi(page: Page, handler: (route: Route, path: string) => Promise<boolean>) {
  await page.route("**/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (await handler(route, path)) return;
    if (path === "/v1/auth/me") return route.fulfill({ json: me });
    if (path === "/v1/admin/health") return route.fulfill({ json: health });
    if (path === "/v1/admin/stats/review") return route.fulfill({ json: reviewStats });
    if (path === "/v1/memories") return route.fulfill({ json: { items: [memory], total: 1, limit: 50, offset: 0 } });
    if (path === "/v1/memories/m1") return route.fulfill({ json: { memory } });
    if (path === "/v1/entities") return route.fulfill({ json: { items: [] } });
    if (path === "/v1/jobs") return route.fulfill({ json: { items: [] } satisfies Schema["JobsOut"] });
    await route.fulfill({ status: 500, json: { detail: `Unmocked endpoint: ${path}` } });
  });
}

test("records useful search feedback", async ({ page }) => {
  let feedback: unknown;
  await mockApi(page, async (route, path) => {
    if (path === "/v1/memories/search") {
      await route.fulfill({ json: searchResult });
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
  await expect(page.getByText("5 tokens · neutral-v1 · 12 ms")).toBeVisible();
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
        await route.fulfill({ json: { id: "m1", revision: 3, status: "active" } satisfies Schema["EntityOut"] });
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
      await route.fulfill({ json: { user: { ...me, handle: who, display_name: who }, csrf_required_header: "X-Requested-With" } satisfies Schema["SessionOut"] });
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
      await route.fulfill({ json: { items: [{ id: "m1", kind: "memory", title: memory.text, memory, created_at: memory.created_at, actions: ["confirm", "decline"] }] } });
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
      await route.fulfill({ json: metrics });
    } else if (path === "/v1/admin/backups") {
      await route.fulfill({ json: backups });
    } else if (path === "/v1/admin/reextract") {
      body = route.request().postData();
      await route.fulfill({ status: 202, json: { job_id: "report-1", status: "queued" } });
    } else return false;
    return true;
  });
  await page.goto("/ui/ops");
  await expect(page.getByRole("heading", { name: "Verified backups" })).toBeVisible();
  await expect(page.getByText("protected", { exact: true })).toBeVisible();
  await expect(page.getByText("Counts match", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Start v7 review batch" })).not.toBeAttached();
  await page.getByRole("button", { name: "Re-extraction report" }).click();
  await expect.poll(() => body).toBeNull();
  await expect(page.getByText("Job report-1 queued")).toBeVisible();
});

test("shows model audit input and output as JSON objects", async ({ page }) => {
  await mockApi(page, async (route, path) => {
    if (path !== "/v1/admin/judge-runs/1") return false;
    await route.fulfill({ json: judge });
    return true;
  });
  await page.goto("/ui/judge-runs/1");
  await expect(page.locator("pre").first()).toContainText('"messages"');
  await expect(page.locator("pre").last()).toContainText('"memories"');
});

test("shows the server's session message and extracted memory counts", async ({ page }) => {
  await mockApi(page, async (route, path) => {
    if (path !== "/v1/admin/sessions") return false;
    await route.fulfill({ json: { items: [session], total: 1, limit: 100, offset: 0 } satisfies Schema["SessionsOut"] });
    return true;
  });
  await page.goto("/ui/sessions");
  await expect(page.getByText("7 messages", { exact: true })).toBeVisible();
  await expect(page.getByText("3 extracted memories", { exact: true })).toBeVisible();
});

test("compares actual index counts and reports cancellation accurately", async ({ page }) => {
  await mockApi(page, async (route, path) => {
    if (path === "/v1/admin/metrics") await route.fulfill({ json: { ...metrics, index_parity: { database_active: 2, qdrant_active: 1 } } satisfies Schema["MetricsOut"] });
    else if (path === "/v1/admin/backups") await route.fulfill({ json: { items: [] } satisfies Schema["BackupsOut"] });
    else if (path === "/v1/jobs") await route.fulfill({ json: { items: [{ id: "job-1", kind: "export", status: "running", result: null, error: null, error_code: null, created_at: memory.created_at, finished_at: null }] } satisfies Schema["JobsOut"] });
    else if (path === "/v1/jobs/job-1/cancel") await route.fulfill({ json: { job_id: "job-1", status: "cancel_requested" } satisfies Schema["JobQueuedOut"] });
    else return false;
    return true;
  });
  await page.goto("/ui/ops");
  await expect(page.getByText("Counts differ", { exact: true })).toBeVisible();
  await expect(page.getByText("2 / 1", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(page.getByText("Cancellation requested", { exact: true })).toBeVisible();
});

test("members see their usage without fetching administrator diagnostics", async ({ page }) => {
  const forbidden: string[] = [];
  await mockApi(page, async (route, path) => {
    if (path === "/v1/auth/me") await route.fulfill({ json: { ...me, role: "member" } satisfies Schema["PrincipalView"] });
    else if (path === "/v1/admin/health" || path === "/v1/admin/backups") {
      forbidden.push(path);
      await route.fulfill({ status: 403, json: { detail: "administrator required" } });
    } else if (path === "/v1/admin/metrics") await route.fulfill({ json: { ...metrics, outbox_pending: null, month_limit_usd: null, outbox_oldest_age_seconds: null, outbox_retries: null, index_parity: { database_active: 1, qdrant_active: null }, backup_freshness_seconds: null } satisfies Schema["MetricsOut"] });
    else return false;
    return true;
  });
  await page.goto("/ui/ops");
  await expect(page.getByRole("heading", { name: "Your usage", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Recent jobs", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Reindex", exact: true })).not.toBeAttached();
  await expect(page.getByText("No backup", { exact: true })).not.toBeAttached();
  await page.getByRole("button", { name: "Refresh", exact: true }).click();
  expect(forbidden).toEqual([]);
});

test("keeps historical evidence separate from current support", async ({ page }) => {
  await mockApi(page, async (route, path) => {
    if (path !== "/v1/memories/m1/sources") return false;
    await route.fulfill({ json: { memory, source_role: "user", evidence: [], historical_evidence: [{ message_id: 1, start_char: 0, end_char: 7, excerpt: "Use npm", verified: true, role: "user", created_at: memory.created_at, supported_revisions: [1], evidence_status: "historical" }] } satisfies Schema["MemorySourcesOut"] });
    return true;
  });
  await page.goto("/ui/memories?memory=m1");
  await page.getByRole("tab", { name: "Evidence", exact: true }).click();
  await expect(page.getByText("No source spans support the current wording.")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Historical evidence", exact: true })).toBeVisible();
  await expect(page.getByText("Supports revision 1", { exact: true })).toBeVisible();
});
