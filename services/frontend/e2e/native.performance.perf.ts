import { createHash } from "node:crypto";
import { test, expect } from "./fixtures";
import { attachRenderProbe, beginRenderSample, finishRenderSample } from "./renderProbe";

test("native dense globe delivers scene frames during movement and separately at rest", async ({ page, state }, info) => {
  state.flightDensity = "dense";
  await page.goto("/worldview?layer=recon");
  await expect(page.locator(".cesium-widget canvas")).toHaveCount(1);
  await expect.poll(() => state.requests.filter(x => x.startsWith("/api/flights")).length).toBeGreaterThan(0);
  await page.getByRole("button", { name: "close Layers", exact: true }).click();
  await page.getByRole("button", { name: "expand Search", exact: true }).click();
  await page.getByRole("textbox", { name: "Search entities" }).fill("Fixture location");
  await page.getByRole("button", { name: "§ Location Fixture location" }).click();
  await page.getByRole("button", { name: "close Search", exact: true }).click();
  await attachRenderProbe(page);
  await new Promise(resolve => setTimeout(resolve, 10000));
  const source = await (await page.request.get("/cesium/Cesium.js")).body();
  const records = [];
  for (let repetition = 1; repetition <= 3; repetition++) {
    const begin = await beginRenderSample(page);
    const started = performance.now();
    await page.mouse.move(1440, 650); await page.mouse.down();
    while (performance.now() - started < 30000) {
      const angle = (performance.now() - started) / 10000 * 2 * Math.PI;
      await page.mouse.move(1440 + 80 * (Math.cos(angle) - 1), 650 + 50 * Math.sin(angle));
      await new Promise(resolve => setTimeout(resolve, 16));
    }
    await page.mouse.move(1400, 650); await page.mouse.up();
    records.push({ repetition, ...await finishRenderSample(page, begin) });
  }
  await page.getByRole("button", { name: "expand Layers", exact: true }).click();
  const toggle = page.getByRole("button", { name: "flights", exact: true });
  const actionLatencies: number[] = [];
  for (let i = 0; i < 20; i++) {
    const before = await toggle.getAttribute("aria-pressed");
    actionLatencies.push(await toggle.evaluate(element => new Promise<number>(resolve => {
      const start = performance.now();
      (element as HTMLButtonElement).click();
      requestAnimationFrame(() => requestAnimationFrame(() => resolve(performance.now() - start)));
    })));
    await expect(toggle).toHaveAttribute("aria-pressed", before === "true" ? "false" : "true");
  }
  const actionP95Ms = [...actionLatencies].sort((a, b) => a - b)[18]!;
  const idleStart = await beginRenderSample(page);
  await new Promise(resolve => setTimeout(resolve, 10000));
  const idle = await finishRenderSample(page, idleStart);
  await info.attach("native-public-events", { contentType: "application/json", body: JSON.stringify({
    records, idle, actionLatencies, actionP95Ms, engineSha256: createHash("sha256").update(source).digest("hex"),
    method: "Public scene.postRender events; one CDP attachment before warmup; no coverage counters",
    profile: "1920x1080; 10000 co-located fixed synthetic flights; 10s warmup; 3x30s active; 10s idle",
    limits: "Synthetic fixture, no live density, imagery-service or operator acceptance",
  }) });
  expect(actionP95Ms).toBeLessThanOrEqual(200);
  for (const record of records) {
    expect(record.fps).toBeGreaterThanOrEqual(30);
    expect(record.frameGapP95Ms).not.toBeNull();
    expect(record.frameGapP95Ms!).toBeLessThanOrEqual(33.3);
  }
  await page.evaluate(() => { window.__odinRenderProbe?.remove(); delete window.__odinRenderProbe; });
});
