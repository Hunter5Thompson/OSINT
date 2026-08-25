import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

describe("WorldviewPage label arbiter", () => {
  it("creates exactly one label arbiter", () => {
    const src = readFileSync(join(process.cwd(), "src/pages/WorldviewPage.tsx"), "utf8");
    expect(src.split("useLabelArbiter(").length - 1).toBe(1);
  });
});
