import type {Page} from "@playwright/test";

declare global {
  interface Window {
    __odinScenarioClock?: { resumeWallTime: () => void };
  }
}

/** Hold the source epoch without replacing native RAF, timers or performance. */
export async function setFixedOrbitDate(page: Page, iso: string): Promise<void> {
  const epoch = Date.parse(iso);
  if (!Number.isFinite(epoch)) throw new Error("Scenario epoch must be finite");
  await page.addInitScript(epoch => {
    const NativeDate = Date;
    const realNow = NativeDate.now.bind(NativeDate);
    let fixed = true;
    let offset = 0;
    const now = () => fixed ? epoch : realNow() + offset;
    globalThis.Date = new Proxy(NativeDate, {
      construct(target, args: unknown[], newTarget) {
        return Reflect.construct(target, args.length ? args : [now()], newTarget);
      },
      apply() { return new NativeDate(now()).toString(); },
      get(target, property, receiver) {
        return property === "now" ? now : Reflect.get(target, property, receiver);
      },
    });
    window.__odinScenarioClock = {
      resumeWallTime() { offset = epoch - realNow(); fixed = false; },
    };
  }, epoch);
}

export async function resumeBrowserDate(page: Page): Promise<void> {
  await page.evaluate(() => {
    if (!window.__odinScenarioClock) throw new Error("Scenario clock is absent");
    window.__odinScenarioClock.resumeWallTime();
  });
}
