import { test, expect } from "./fixtures";
import { readFileSync } from "node:fs";

declare global {
  interface Window { __odinBlobUrls?: Map<string, { bytes: number; type: string }> }
}

test("map remounts do not retain embedded worker blobs in the browser", async ({ page, state }, info) => {
  state.flightDensity = "dense";
  await page.addInitScript(() => {
    const urls = new Map<string, { bytes: number; type: string }>();
    window.__odinBlobUrls = urls;
    const create = URL.createObjectURL.bind(URL);
    const revoke = URL.revokeObjectURL.bind(URL);
    URL.createObjectURL = object => {
      const url = create(object);
      if (object instanceof Blob) urls.set(url, { bytes: object.size, type: object.type });
      return url;
    };
    URL.revokeObjectURL = url => { urls.delete(url); revoke(url); };
  });
  await page.goto("/worldview?layer=recon");
  const browserSession = await page.context().browser()!.newBrowserCDPSession();
  const processes = await browserSession.send("SystemInfo.getProcessInfo");
  const browserPid = processes.processInfo.find(process => process.type === "browser")!.id;
  const samples: { iteration: number; blobs: number; bytes: number; browserRssKiB: number }[] = [];
  for (let iteration = 0; iteration < 20; iteration++) {
    await expect(page.locator(".cesium-widget canvas")).toHaveCount(1);
    await new Promise(resolve => setTimeout(resolve, 500));
    const retained = await page.evaluate(() => {
      const blobs = [...window.__odinBlobUrls!.values()];
      return { blobs: blobs.length, bytes: blobs.reduce((sum, blob) => sum + blob.bytes, 0) };
    });
    const browserRssKiB = Number(/VmRSS:\s+(\d+)/.exec(readFileSync(`/proc/${browserPid}/status`, "utf8"))![1]);
    samples.push({ iteration, ...retained, browserRssKiB });
    await page.getByRole("link", { name: "BRIEFING", exact: true }).click();
    await expect(page.locator(".cesium-widget canvas")).toHaveCount(0);
    await page.getByRole("link", { name: "WORLDVIEW", exact: true }).click();
  }
  await expect(page.locator(".cesium-widget canvas")).toHaveCount(1);
  await browserSession.send("Memory.simulatePressureNotification", { level: "critical" });
  await new Promise(resolve => setTimeout(resolve, 1000));
  await info.attach("browser-memory-pressure", {
    body: JSON.stringify({ afterPressureRssKiB: Number(/VmRSS:\s+(\d+)/.exec(readFileSync(`/proc/${browserPid}/status`, "utf8"))![1]) }),
    contentType: "application/json",
  });
  await browserSession.detach();
  await info.attach("browser-blob-ownership", { body: JSON.stringify(samples), contentType: "application/json" });
  expect(samples.at(-1)!.bytes - samples[5]!.bytes).toBeLessThan(256 * 1024);
});
