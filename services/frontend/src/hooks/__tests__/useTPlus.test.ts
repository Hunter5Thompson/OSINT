import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";

import { formatTPlus, useTPlus } from "../useTPlus";

describe("formatTPlus", () => {
  it("renders T+hh:mm:ss for sub-day deltas", () => {
    expect(formatTPlus(0)).toBe("T+00:00:00");
    expect(formatTPlus(2 * 3600 + 14 * 60 + 8)).toBe("T+02:14:08");
  });

  it("renders Td.hh:mm for ≥24h deltas", () => {
    expect(formatTPlus(26 * 3600 + 5 * 60)).toBe("T+1d.02:05");
  });

  it("clamps negatives to T+00:00:00", () => {
    expect(formatTPlus(-10)).toBe("T+00:00:00");
  });
});

describe("useTPlus", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("ticks every second", () => {
    const start = new Date("2026-04-25T10:00:00Z");
    vi.setSystemTime(start);
    const { result } = renderHook(() => useTPlus(start.toISOString()));
    expect(result.current).toBe("T+00:00:00");
    act(() => {
      vi.advanceTimersByTime(2000);
    });
    expect(result.current).toBe("T+00:00:02");
  });
});
