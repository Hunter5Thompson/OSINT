import { describe, it, expect } from "vitest";
import { signedSpeed, stepTargetMs, stepWindow } from "../transport";

describe("transport helpers", () => {
  it("signedSpeed combines UI magnitude with direction (magnitude is always positive)", () => {
    expect(signedSpeed(5, 1)).toBe(5);
    expect(signedSpeed(5, -1)).toBe(-5);
    expect(signedSpeed(-5, -1)).toBe(-5); // abs() guards a stray negative magnitude
    expect(signedSpeed(0.5, 1)).toBe(0.5);
  });

  it("stepTargetMs advances/retreats by exactly one bucket", () => {
    // span 1000ms over 10 buckets => 100ms per bucket
    expect(stepTargetMs(500, 0, 1000, 10, 1)).toBe(600);
    expect(stepTargetMs(500, 0, 1000, 10, -1)).toBe(400);
  });

  it("stepTargetMs clamps at the window bounds (no wraparound)", () => {
    expect(stepTargetMs(950, 0, 1000, 10, 1)).toBe(1000); // would be 1050 -> clamp
    expect(stepTargetMs(50, 0, 1000, 10, -1)).toBe(0); // would be -50 -> clamp
  });
});

describe("stepWindow", () => {
  const brush = { startMs: 10, endMs: 20 };
  it("uses the brush window in replay", () => {
    expect(stepWindow(true, brush, 0, 100)).toEqual(brush);
  });
  it("uses the coarse range when not in replay", () => {
    expect(stepWindow(false, brush, 0, 100)).toEqual({ startMs: 0, endMs: 100 });
  });
  it("falls back to coarse when there is no brush", () => {
    expect(stepWindow(true, null, 0, 100)).toEqual({ startMs: 0, endMs: 100 });
  });
});
