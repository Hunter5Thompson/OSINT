import { describe, it, expect, beforeAll } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { resolve } from "node:path";

describe("hlidskjalf panel tokens", () => {
  beforeAll(() => {
    const cssPath = resolve(fileURLToPath(import.meta.url), "../../../theme/hlidskjalf.css");
    const css = readFileSync(cssPath, "utf8");
    const style = document.createElement("style");
    style.textContent = css;
    document.head.appendChild(style);
  });

  it("exposes --hl-panel-bg as a CSS variable on :root", () => {
    const value = getComputedStyle(document.documentElement).getPropertyValue("--hl-panel-bg");
    expect(value.trim()).toBe("rgba(18,17,14,0.84)");
  });

  it("exposes --hl-panel-border as 1px solid granite", () => {
    const value = getComputedStyle(document.documentElement).getPropertyValue("--hl-panel-border");
    expect(value.trim()).toBe("1px solid var(--granite)");
  });

  it("exposes --hl-panel-blur as 12px blur", () => {
    const value = getComputedStyle(document.documentElement).getPropertyValue("--hl-panel-blur");
    expect(value.trim()).toBe("blur(12px)");
  });
});
