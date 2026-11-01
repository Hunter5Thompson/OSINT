import { test, expect } from "./fixtures";
import { attachRenderProbe, beginRenderSample, finishRenderSample } from "./renderProbe";

declare global { interface Window { __odinRestoreContext?: () => void } }

test("an injected WebGL loss can rebuild the map without losing layer state", async ({ page, state }, info) => {
  state.flightDensity = "dense";
  await page.goto("/worldview?layer=recon");
  await expect(page.locator(".cesium-widget canvas")).toHaveCount(1);
  const expand = page.getByRole("button", { name: "expand Layers", exact: true });
  if (await expand.isVisible()) await expand.click();
  const flights = page.getByRole("button", { name: "flights", exact: true });
  await expect(flights).toHaveAttribute("aria-pressed", "true");
  await flights.click();
  await expect(flights).toHaveAttribute("aria-pressed", "false");
  const oldCanvas = await page.locator(".cesium-widget canvas").elementHandle();
  expect(oldCanvas).not.toBeNull();
  await page.evaluate(() => {
    const canvas = document.querySelector<HTMLCanvasElement>(".cesium-widget canvas");
    const gl = canvas?.getContext("webgl2");
    const extension = gl?.getExtension("WEBGL_lose_context");
    if (!extension) throw new Error("Required context-loss test extension unavailable");
    window.__odinRestoreContext = () => { extension.restoreContext(); delete window.__odinRestoreContext; };
    extension.loseContext();
  });
  await expect(page.getByTestId("globe-render-error")).toBeVisible();
  await expect(page.getByRole("link", { name: "BRIEFING", exact: true })).toBeVisible();
  await page.evaluate(() => window.__odinRestoreContext?.());
  await page.getByRole("button", { name: "Reload map", exact: true }).click();
  await expect(page.getByTestId("globe-render-error")).toHaveCount(0);
  await expect.poll(() => oldCanvas!.evaluate(canvas => canvas.isConnected)).toBe(false);
  await expect(page.locator(".cesium-widget canvas")).toHaveCount(1);
  if (await expand.isVisible()) await expand.click();
  // A non-default selection must survive replacing the underlying viewer.
  await expect(flights).toHaveAttribute("aria-pressed", "false");
  await flights.click();
  await expect(flights).toHaveAttribute("aria-pressed", "true");
  await attachRenderProbe(page);
  const begin = await beginRenderSample(page);
  await new Promise(resolve => setTimeout(resolve, 1000));
  const restored = await finishRenderSample(page, begin);
  await info.attach("restored-rendering", { body: JSON.stringify(restored), contentType: "application/json" });
  expect(restored.frames).toBeGreaterThan(0);
  await page.evaluate(() => { window.__odinRenderProbe?.remove(); delete window.__odinRenderProbe; });
  await oldCanvas!.dispose();
});
