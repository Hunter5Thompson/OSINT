import type { Page } from "@playwright/test";

interface RenderProbe { times: number[]; remove: () => void }
declare global { interface Window { __odinRenderProbe?: RenderProbe } }

/** Attach to the real mounted widget once, before warmup. No renderer patch.
 * CDP precise coverage is deliberately not used: V8 may return function-only
 * ranges rather than counts of the postRender call's executed block.
 */
export async function attachRenderProbe(page: Page): Promise<void> {
  const source = await (await page.request.get("/cesium/Cesium.js")).text();
  const match = /\w+\.prototype\.render=function\(\)\{if\(this\._canRender\)/.exec(source);
  if (!match) throw new Error("Cannot locate pinned Cesium widget; requalify the probe");
  const at = match.index + match[0].indexOf("{") + 1;
  const lines = source.slice(0, at).split("\n");
  const cdp = await page.context().newCDPSession(page);
  await cdp.send("Debugger.enable");
  let timeout: ReturnType<typeof setTimeout> | undefined;
  const paused = new Promise<void>((resolve, reject) => {
    timeout = setTimeout(() => reject(new Error("No mounted Cesium render within 10s")), 10000);
    cdp.once("Debugger.paused", async event => {
      try {
        const frame = event.callFrames[0];
        if (!frame) throw new Error("Missing widget call frame");
        const response = await cdp.send("Debugger.evaluateOnCallFrame", {
          callFrameId: frame.callFrameId,
          expression: `(() => {
            if (!this._canvas.isConnected) throw new Error('Detached widget');
            window.__odinRenderProbe?.remove();
            const probe = {times: [], remove: () => {}};
            probe.remove = this.scene.postRender.addEventListener(() => probe.times.push(performance.now()));
            window.__odinRenderProbe = probe;
            return true;
          })()`, returnByValue: true,
        });
        if (response.exceptionDetails || response.result.value !== true) {
          throw new Error("Unable to attach public postRender listener");
        }
        resolve();
      } catch (error) { reject(error); }
      finally { await cdp.send("Debugger.resume"); }
    });
  });
  try {
    await cdp.send("Debugger.setBreakpointByUrl", {
      urlRegex: "/cesium/Cesium\\.js$", lineNumber: lines.length - 1,
      columnNumber: lines.at(-1)!.length,
    });
    await paused;
  } finally {
    clearTimeout(timeout);
    await cdp.send("Debugger.disable");
    await cdp.detach();
  }
}

export async function beginRenderSample(page: Page): Promise<number> {
  return page.evaluate(() => {
    if (!window.__odinRenderProbe) throw new Error("Render probe is absent");
    window.__odinRenderProbe.times = [];
    return performance.now();
  });
}

export async function finishRenderSample(page: Page, start: number) {
  return page.evaluate((begin) => {
    const probe = window.__odinRenderProbe;
    if (!probe) throw new Error("Render probe is absent");
    const seconds = (performance.now() - begin) / 1000;
    const gaps = probe.times.slice(1).map((t, i) => t - probe.times[i]!).sort((a, b) => a - b);
    return { seconds, frames: probe.times.length, fps: probe.times.length / seconds,
      frameGapP95Ms: gaps[Math.max(0, Math.ceil(gaps.length * .95) - 1)] ?? null };
  }, start);
}
