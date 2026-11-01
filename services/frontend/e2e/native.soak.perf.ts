import { appendFileSync } from "node:fs";
import { test, expect } from "./fixtures";

// An explicit separate command, never a silently skipped CI test.
test("60 minute native layer, time and route lifecycle soak", async ({ page, state }, info) => {
  const durationMs = 60 * 60 * 1000;
  test.setTimeout(durationMs + 120000);
  state.flightDensity = "dense";
  const cdp = await page.context().newCDPSession(page);
  await cdp.send("Performance.enable");
  const samples: { minute: number; heap: number; nodes: number; documents: number }[] = [];
  const start = performance.now();
  let iteration = 0;
  await page.goto("/worldview?layer=recon");
  do {
    await expect(page.locator(".cesium-widget canvas")).toHaveCount(1);
    const expand = page.getByRole("button", { name: "expand Layers", exact: true });
    if (await expand.isVisible()) await expand.click();
    const flights = page.getByRole("button", { name: "flights", exact: true });
    await flights.click(); await flights.click();
    await page.getByRole("button", { name: "7d", exact: true }).click();
    await page.getByRole("button", { name: "step back", exact: true }).click();
    await page.getByRole("button", { name: "now", exact: true }).click();
    await expect(page.locator(".cesium-widget-errorPanel")).toHaveCount(0);
    await page.getByRole("link", { name: "BRIEFING", exact: true }).click();
    await expect(page.locator(".cesium-widget canvas")).toHaveCount(0);
    await page.getByRole("link", { name: "WORLDVIEW", exact: true }).click();
    await expect(page.locator(".cesium-widget canvas")).toHaveCount(1);
    await new Promise(resolve => setTimeout(resolve, 25000));
    // Compare retained heap at the same mounted route after collection. This
    // says nothing about GPU/driver memory; record that separately on the host.
    await cdp.send("HeapProfiler.collectGarbage");
    const metrics = await cdp.send("Performance.getMetrics");
    const counters = await cdp.send("Memory.getDOMCounters");
    const sample = { minute: (performance.now() - start) / 60000,
      heap: metrics.metrics.find(m => m.name === "JSHeapUsedSize")!.value,
      nodes: counters.nodes, documents: counters.documents };
    samples.push(sample);
    appendFileSync(info.outputPath("soak.jsonl"), JSON.stringify(sample) + "\n");
    iteration++;
  } while (performance.now() - start < durationMs);
  await cdp.detach();
  await info.attach("soak-summary", { contentType: "application/json", body: JSON.stringify({
    samples, iteration, durationMs: performance.now() - start,
    limits: "Synthetic fixture; retained JS heap and DOM only, no live/model/human acceptance",
  }) });
  // Freeze tolerances before the run: compare warm five-sample windows. A
  // bounded one-off cache is allowed; continuing retained growth is not.
  const median = (values: number[]) => values.sort((a, b) => a - b)[Math.floor(values.length / 2)]!;
  const first = samples.slice(5, 10), last = samples.slice(-5);
  expect(median(last.map(x => x.heap)) - median(first.map(x => x.heap))).toBeLessThan(5 * 1024 * 1024);
  expect(median(last.map(x => x.nodes)) - median(first.map(x => x.nodes))).toBeLessThan(50);
});
