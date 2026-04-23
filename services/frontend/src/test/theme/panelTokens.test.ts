import { beforeAll, describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

describe("hlidskjalf panel tokens", () => {
  let cssText = "";

  beforeAll(async () => {
    cssText = readFileSync(resolve(process.cwd(), "src/theme/hlidskjalf.css"), "utf8");
  });

  it("exposes --hl-panel-bg on :root", () => {
    expect(cssText).toContain("--hl-panel-bg: rgba(18, 17, 14, 0.84);");
  });

  it("exposes --hl-panel-border", () => {
    expect(cssText).toContain("--hl-panel-border: 1px solid var(--granite);");
  });

  it("exposes --hl-panel-blur", () => {
    expect(cssText).toContain("--hl-panel-blur: blur(12px);");
  });
});
