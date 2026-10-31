import assert from "node:assert/strict";
import { chromium, expect } from "@playwright/test";

// Invoked by the backend gateway integration fixture with real nginx and fakes.
const origin = process.env.ODIN_GATEWAY_TEST_ORIGIN;
assert(origin && new URL(origin).hostname === "127.0.0.1");
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage();
  const queries = [];
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.route("**/*", async route => {
    const request = route.request();
    if (new URL(request.url()).origin !== origin) return route.abort();
    if (request.url().includes("/api/")) {
      assert.equal(request.headers()["x-admin-token"], undefined);
    }
    if (new URL(request.url()).pathname === "/api/intel/query") {
      queries.push(request.postDataJSON());
    }
    return route.continue();
  });
  await page.goto(`${origin}/briefing`);
  await expect(page.getByRole("heading", { name: "Gateway dossier", exact: true })).toBeVisible();
  const question = "Describe the gateway fixture";
  await page.getByPlaceholder("▸ ask Munin about this section…").fill(question);
  await page.getByPlaceholder("▸ ask Munin about this section…").press("Enter");
  await expect(page.getByText("Gateway fake answer", { exact: true })).toBeVisible();
  assert.equal(queries.length, 1);
  assert.equal(queries[0].report_id, "r-probe");
  assert.equal(queries[0].report_message, question);
  await page.reload();
  await expect(page.getByText("Gateway fake answer", { exact: true })).toBeVisible();
  assert.deepEqual(errors, []);
  if (process.env.ODIN_GATEWAY_SCREENSHOT) {
    await page.screenshot({ path: process.env.ODIN_GATEWAY_SCREENSHOT, fullPage: true });
  }
  console.log("PASS: built dossier chat, server credentials, SSE result and persisted reload");
} finally {
  await browser.close();
}
