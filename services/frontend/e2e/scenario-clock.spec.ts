import {test,expect} from "@playwright/test";
import {setFixedOrbitDate,resumeBrowserDate} from "./scenarioClock";

test("fixed orbit epoch preserves native browser rendering timers",async({page})=>{
  const iso="2026-10-09T05:27:38.151Z";
  await setFixedOrbitDate(page,iso);
  await page.goto("about:blank");
  expect(await page.evaluate(()=>requestAnimationFrame.toString())).toContain("[native code]");
  expect(await page.evaluate(()=>setTimeout.toString())).toContain("[native code]");
  expect(await page.evaluate(()=>Date.now())).toBe(Date.parse(iso));
  expect(await page.evaluate(()=>new Date().getTime())).toBe(Date.parse(iso));
  expect(await page.evaluate(()=>new Date(2020,1,3).getMonth())).toBe(1);
  const nativeFrames=await page.evaluate(()=>new Promise<number>(resolve=>{
    let frames=0;const next=()=>{if(++frames===3)resolve(frames);else requestAnimationFrame(next);};requestAnimationFrame(next);
  }));
  expect(nativeFrames).toBe(3);
  expect(await page.evaluate(()=>Date.now())).toBe(Date.parse(iso));
  await resumeBrowserDate(page);
  await expect.poll(()=>page.evaluate(()=>Date.now())).toBeGreaterThan(Date.parse(iso));
});
