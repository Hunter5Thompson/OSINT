import { describe, it, expect } from "vitest";
import { fadeAlpha } from "../EventLayer";

describe("EventLayer fadeAlpha (§7)", () => {
  const win = { startMs: 0, endMs: 100 };
  it("outside the window -> 0", () => {
    expect(fadeAlpha(-1, 50, win, 10)).toBe(0);
    expect(fadeAlpha(101, 50, win, 10)).toBe(0);
  });
  it("at the cursor -> full", () => {
    expect(fadeAlpha(50, 50, win, 10)).toBeCloseTo(1);
  });
  it("near the cursor -> linear falloff", () => {
    expect(fadeAlpha(55, 50, win, 10)).toBeCloseTo(0.5);
  });
  it("in-window but far from cursor -> floor (still faintly visible)", () => {
    expect(fadeAlpha(90, 50, win, 10)).toBeGreaterThan(0);
    expect(fadeAlpha(90, 50, win, 10)).toBeLessThan(0.5);
  });
  it("invalid timestamps are treated as outside the window", () => {
    expect(fadeAlpha(Number.NaN, 50, win, 10)).toBe(0);
    expect(fadeAlpha(Number.POSITIVE_INFINITY, 50, win, 10)).toBe(0);
  });
});
