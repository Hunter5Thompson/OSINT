import { test, expect } from "./fixtures";

test("50 map remounts release owned canvas, terrain and style resources", async ({ page, state }, info) => {
  state.flightDensity = "dense";
  const cdp = await page.context().newCDPSession(page);
  await cdp.send("Performance.enable");
  await page.goto("/worldview?layer=recon");
  const samples: { heap: number; nodes: number }[] = [];
  for (let iteration = 0; iteration < 50; iteration++) {
    await expect(page.locator(".cesium-widget canvas")).toHaveCount(1);
    await page.getByRole("link", { name: "BRIEFING", exact: true }).click();
    await expect(page.locator(".cesium-widget canvas")).toHaveCount(0);
    await page.getByRole("link", { name: "WORLDVIEW", exact: true }).click();
    await expect(page.locator(".cesium-widget canvas")).toHaveCount(1);
    await new Promise(resolve => setTimeout(resolve, 100));
    await cdp.send("HeapProfiler.collectGarbage");
    const metrics = await cdp.send("Performance.getMetrics");
    const counters = await cdp.send("Memory.getDOMCounters");
    samples.push({ heap: metrics.metrics.find(m => m.name === "JSHeapUsedSize")!.value, nodes: counters.nodes });
  }
  await cdp.detach();
  await info.attach("retained-resources", { contentType: "application/json", body: JSON.stringify(samples) });
  const median = (values: number[]) => values.sort((a, b) => a - b)[Math.floor(values.length / 2)]!;
  const first = samples.slice(5, 10), last = samples.slice(-5);
  expect(median(last.map(x => x.nodes)) - median(first.map(x => x.nodes))).toBeLessThan(20);
  expect(median(last.map(x => x.heap)) - median(first.map(x => x.heap))).toBeLessThan(3 * 1024 * 1024);
});
