import { appendFileSync, readFileSync } from "node:fs";
import { test, expect } from "./fixtures";

declare global { interface Window { __odinContextLossCount?: number } }

// An explicit separate command, never a silently skipped CI test.
test("60 minute native layer, time and route lifecycle soak", async ({ page, state }, info) => {
  const durationMs = 60 * 60 * 1000;
  test.setTimeout(durationMs + 120000);
  state.flightDensity = "dense";
  await page.addInitScript(() => {
    window.__odinContextLossCount = 0;
    document.addEventListener("webglcontextlost", () => { window.__odinContextLossCount! += 1; }, true);
  });
  page.on("console", message => {
    if (["warning", "error"].includes(message.type())) {
      appendFileSync(info.outputPath("console.jsonl"), JSON.stringify({
        at: new Date().toISOString(), type: message.type(), text: message.text(),
      }) + "\n");
    }
  });
  const cdp = await page.context().newCDPSession(page);
  const browserSession = await page.context().browser()!.newBrowserCDPSession();
  await cdp.send("Performance.enable");
  const samples: { minute: number; heap: number; nodes: number; documents: number;
    browserRssMiB: number; gpuRssMiB: number; rendererRssMiB: number }[] = [];
  const start = performance.now();
  let iteration = 0;
  await page.goto("/worldview?layer=recon");
  do {
    await expect(page.locator(".cesium-widget-errorPanel, [data-testid=globe-render-error]")).toHaveCount(0);
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
    await expect(page.locator(".cesium-widget-errorPanel, [data-testid=globe-render-error]")).toHaveCount(0);
    expect(await page.evaluate(() => window.__odinContextLossCount)).toBe(0);
    // Compare retained heap at the same mounted route after collection. This
    // says nothing about GPU/driver memory; record that separately on the host.
    await cdp.send("HeapProfiler.collectGarbage");
    const metrics = await cdp.send("Performance.getMetrics");
    const counters = await cdp.send("Memory.getDOMCounters");
    const processes = (await browserSession.send("SystemInfo.getProcessInfo")).processInfo;
    const rss = (type: string) => processes.filter(process => process.type.toLowerCase() === type)
      .reduce((sum, process) => {
        try {
          const status = readFileSync(`/proc/${process.id}/status`, "utf8");
          return sum + Number(/VmRSS:\s+(\d+)/.exec(status)![1]) / 1024;
        } catch { return sum; } // A renderer can exit between the CDP list and /proc read.
      }, 0);
    const sample = { minute: (performance.now() - start) / 60000,
      heap: metrics.metrics.find(m => m.name === "JSHeapUsedSize")!.value,
      nodes: counters.nodes, documents: counters.documents,
      browserRssMiB: rss("browser"), gpuRssMiB: rss("gpu"), rendererRssMiB: rss("renderer") };
    expect(sample.browserRssMiB).toBeGreaterThan(0);
    expect(sample.gpuRssMiB).toBeGreaterThan(0);
    expect(sample.rendererRssMiB).toBeGreaterThan(0);
    samples.push(sample);
    appendFileSync(info.outputPath("soak.jsonl"), JSON.stringify(sample) + "\n");
    iteration++;
  } while (performance.now() - start < durationMs);
  await cdp.detach();
  await browserSession.detach();
  await info.attach("soak-summary", { contentType: "application/json", body: JSON.stringify({
    samples, iteration, durationMs: performance.now() - start,
    limits: "Synthetic fixture; retained JS/DOM and this isolated browser process tree; no remote terrain/model/human acceptance",
  }) });
  // Freeze tolerances before the run: compare warm five-sample windows. A
  // bounded one-off cache is allowed; continuing retained growth is not.
  const median = (values: number[]) => values.sort((a, b) => a - b)[Math.floor(values.length / 2)]!;
  const first = samples.slice(5, 10), last = samples.slice(-5);
  expect(median(last.map(x => x.heap)) - median(first.map(x => x.heap))).toBeLessThan(5 * 1024 * 1024);
  expect(median(last.map(x => x.nodes)) - median(first.map(x => x.nodes))).toBeLessThan(50);
  // Native criteria frozen before this candidate's first soak. Browser-process
  // RSS exposed continuing growth that JS heap/DOM checks alone did not detect.
  const nativeFirst = samples.filter(x => x.minute >= 10 && x.minute <= 15);
  const nativeLast = samples.filter(x => x.minute >= 55 && x.minute <= 60);
  expect(nativeFirst.length).toBeGreaterThanOrEqual(5);
  expect(nativeLast.length).toBeGreaterThanOrEqual(5);
  for (const [key, limit] of [["browserRssMiB", 32], ["gpuRssMiB", 64], ["rendererRssMiB", 128]] as const) {
    expect(median(nativeLast.map(x => x[key])) - median(nativeFirst.map(x => x[key]))).toBeLessThan(limit);
  }
  const warm = samples.filter(x => x.minute >= 10);
  const meanTime = warm.reduce((sum, x) => sum + x.minute, 0) / warm.length;
  const meanRss = warm.reduce((sum, x) => sum + x.browserRssMiB, 0) / warm.length;
  const slope = warm.reduce((sum, x) => sum + (x.minute - meanTime) * (x.browserRssMiB - meanRss), 0)
    / warm.reduce((sum, x) => sum + (x.minute - meanTime) ** 2, 0);
  expect(slope).toBeLessThan(0.5);
});
