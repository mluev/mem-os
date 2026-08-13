import { expect, test, type Page, type Route } from "@playwright/test";

const health = { database: { path: "memkit.db", schema_version: 6 }, qdrant: { available: true, memories: 1, raw: 1 }, embedder: { ready: true, device: "cpu", revision: "revision" }, outbox: { pending: 0 }, jobs: {} };

async function mockApi(page: Page, handler: (route: Route, path: string) => Promise<boolean>) {
  await page.route("**/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (await handler(route, path)) return;
    if (path === "/v1/admin/health") return route.fulfill({ json: health });
    await route.fulfill({ json: { items: [] } });
  });
}

test("records useful search feedback", async ({ page }) => {
  let feedback: unknown;
  await mockApi(page, async (route, path) => {
    if (path === "/v1/memories/search") {
      await route.fulfill({ json: { retrieval_id: "run-1", memories: [{ id: "m1", text: "Prefers reviewed migrations", kind: "preference", context: {}, tags: [], source_role: "user", score: 0.9, similarity: 0.8, lexical: 1 }], raw: [], used_tokens: 5, policy_id: "neutral-v1", timings: { total_ms: 12 }, took_ms: 12 } });
      return true;
    }
    if (path === "/v1/retrieval-runs/run-1/feedback") {
      feedback = route.request().postDataJSON();
      await route.fulfill({ status: 201, json: { recorded: true } });
      return true;
    }
    return false;
  });
  await page.goto("/ui/search");
  await page.getByLabel("Query").fill("migration preference");
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await page.getByRole("button", { name: "Useful" }).click();
  await expect.poll(() => feedback).toEqual({ memory_id: "m1", useful: true, correct: true });
});

test("edits a replay item without changing immutable provenance", async ({ page }) => {
  let review: unknown;
  const batch = { id: "batch-1", status: "review", model: "gemini", prompt_version: "v7", approval_checksum: null, stats: {}, created_at: "2026-08-12T00:00:00Z" };
  await mockApi(page, async (route, path) => {
    if (path === "/v1/replay-batches") { await route.fulfill({ json: { items: [batch] } }); return true; }
    if (path === "/v1/replay-batches/batch-1/items" && route.request().method() === "GET") { await route.fulfill({ json: { items: [{ id: "item-1", sequence: 0, action: "UPDATE", decision: "pending", source_role: "user", before: null, proposed: { text: "Original", kind: "fact" }, reviewed: null, evidence: [{ message_id: 1, excerpt: "exact user evidence", start_char: 0, end_char: 19 }] }] } }); return true; }
    if (path.endsWith("/review")) { review = route.request().postDataJSON(); await route.fulfill({ json: {} }); return true; }
    return false;
  });
  await page.goto("/ui/replay");
  await page.getByRole("button", { name: "Edit" }).click();
  await page.locator("textarea").fill("Reviewed text");
  await page.getByRole("button", { name: "Save edit" }).click();
  await expect.poll(() => review).toEqual({ decision: "edited", edits: { text: "Reviewed text" } });
  await expect(page.getByText("exact user evidence")).toBeAttached();
});

test("saves blinded human scoring", async ({ page }) => {
  let review: Record<string, unknown> | undefined;
  await mockApi(page, async (route, path) => {
    if (path === "/v1/evaluations") { await route.fulfill({ json: { items: [{ id: "eval-1", status: "reviewing", model: "gpt-5.6-sol" }] } }); return true; }
    if (path === "/v1/evaluations/eval-1/cases") { await route.fulfill({ json: { items: [{ id: "case-1", case_key: "case", prompt: "Question", arms: { A: "Answer A", B: "Answer B", C: "Answer C", D: "Answer D" }, review: null }] } }); return true; }
    if (path.endsWith("/review")) { review = route.request().postDataJSON(); await route.fulfill({ json: {} }); return true; }
    return false;
  });
  await page.goto("/ui/evaluations");
  const rankButtons = page.getByRole("button", { name: "Add to ranking" });
  for (let index = 0; index < 4; index += 1) {
    await rankButtons.nth(index).click();
    await expect(page.getByText(`rank ${index + 1}`, { exact: false })).toBeVisible();
  }
  await page.getByRole("button", { name: "v7 wins" }).click();
  await page.getByRole("button", { name: "Save human ranking" }).click();
  await expect.poll(() => review?.current_vs_v7).toBe("v7_win");
  expect(review?.ranking).toEqual(["A", "B", "C", "D"]);
});

test("shows verified protected backup status", async ({ page }) => {
  await mockApi(page, async (route, path) => {
    if (path === "/v1/admin/metrics") { await route.fulfill({ json: { outbox_pending: 0, oldest_unprocessed_message: null, provider_errors: 0, month_spend_usd: 0, month_reserved_usd: 0, feedback_labels: 0, search_latency_ms: { p50: 10, p95: 20, p99: 30 }, index_parity: { sqlite_active: 1, qdrant_active: 1, matches: true }, backup_freshness_seconds: 60 } }); return true; }
    if (path === "/v1/jobs") { await route.fulfill({ json: { items: [], next_cursor: null } }); return true; }
    if (path === "/v1/admin/backups") { await route.fulfill({ json: { items: [{ id: "b1", kind: "pre-promotion", verified_at: "2026-08-12T00:00:00Z", protected: 1 }] } }); return true; }
    return false;
  });
  await page.goto("/ui/ops");
  await expect(page.getByText("Verified backups")).toBeVisible();
  await expect(page.getByText("protected", { exact: true })).toBeVisible();
});

test("surfaces failed promotion after explicit confirmation", async ({ page }) => {
  const batch = { id: "batch-1", status: "approved", model: "gemini", prompt_version: "v7", approval_checksum: "checksum", stats: {}, created_at: "2026-08-12T00:00:00Z" };
  await mockApi(page, async (route, path) => {
    if (path === "/v1/replay-batches") { await route.fulfill({ json: { items: [batch] } }); return true; }
    if (path === "/v1/replay-batches/batch-1/items") { await route.fulfill({ json: { items: [] } }); return true; }
    if (path.endsWith("/promote")) { await route.fulfill({ status: 500, json: { detail: "promotion failed and SQLite plus Qdrant were rolled back automatically" } }); return true; }
    return false;
  });
  await page.goto("/ui/replay");
  await page.getByLabel("Type PROMOTE").fill("PROMOTE");
  await page.getByRole("button", { name: "Promote with rollback protection" }).click();
  await expect(page.getByText(/rolled back automatically/)).toBeVisible();
});
