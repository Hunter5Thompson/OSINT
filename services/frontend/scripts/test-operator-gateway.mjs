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
  const source = page.getByRole("link", { name: "https://example.test/reviewed-source", exact: true });
  await expect(source).toHaveAttribute("href", "https://example.test/reviewed-source");
  await page.keyboard.press("Tab");
  await source.focus();
  await expect(source).toBeFocused();
  const focus = await source.evaluate(element => getComputedStyle(element).outlineStyle);
  assert.notEqual(focus, "none");
  assert.equal(queries.length, 1);
  assert.equal(queries[0].report_id, "r-probe");
  assert.equal(queries[0].report_message, question);
  await page.reload();
  await expect(page.getByText("Gateway fake answer", { exact: true })).toBeVisible();
  await expect(source).toBeVisible();
  const contrastRatios = await page.locator(
    ".briefing-chat-meta, .briefing-munin-state, .briefing-dossier-submeta, .briefing-report-sub",
  ).evaluateAll(elements => {
    const canvas = document.createElement("canvas"); canvas.width = canvas.height = 1;
    const context = canvas.getContext("2d");
    if (!context) throw new Error("No color conversion context");
    const luminance = color => {
      context.clearRect(0, 0, 1, 1); context.fillStyle = color; context.fillRect(0, 0, 1, 1);
      const rgb = [...context.getImageData(0, 0, 1, 1).data].slice(0, 3).map(value => {
        const v = value / 255; return v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4;
      });
      return .2126 * rgb[0] + .7152 * rgb[1] + .0722 * rgb[2];
    };
    return elements.map(element => {
      const style = getComputedStyle(element);
      // The opaque basalt surface is a conservative reference for these dark,
      // partially transparent dossier panels. This is a bounded palette check.
      const fg = luminance(style.color), bg = luminance(style.getPropertyValue("--basalt"));
      return (Math.max(fg, bg) + .05) / (Math.min(fg, bg) + .05);
    });
  });
  assert(contrastRatios.length > 0);
  assert(contrastRatios.every(ratio => ratio >= 4.5), JSON.stringify(contrastRatios));
  assert.deepEqual(errors, []);
  if (process.env.ODIN_GATEWAY_SCREENSHOT) {
    await page.screenshot({ path: process.env.ODIN_GATEWAY_SCREENSHOT, fullPage: true });
  }
  console.log("PASS: built dossier chat, server credentials, SSE result and persisted reload");
} finally {
  await browser.close();
}
