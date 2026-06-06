import type { ReactNode } from "react";
import { describe, it, expect } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { TimeProvider, useTime } from "../TimeContext";

// viewer=null path: clock is internal/simulated, no Cesium needed.
const wrapper = ({ children }: { children: ReactNode }) => (
  <TimeProvider viewer={null}>{children}</TimeProvider>
);

describe("TimeContext", () => {
  it("starts in live mode with getTimeMs ~ now", () => {
    const { result } = renderHook(() => useTime(), { wrapper });
    expect(result.current.mode).toBe("live");
    expect(Math.abs(result.current.getTimeMs() - Date.now())).toBeLessThan(2000);
  });

  it("seek sets cursor and bumps discontinuityEpoch (even forward)", () => {
    const { result } = renderHook(() => useTime(), { wrapper });
    const before = result.current.discontinuityEpoch;
    act(() => result.current.seek(1_700_000_000_000));
    expect(result.current.getTimeMs()).toBe(1_700_000_000_000);
    expect(result.current.discontinuityEpoch).toBe(before + 1);
  });

  it("setMode replay bumps discontinuityEpoch", () => {
    const { result } = renderHook(() => useTime(), { wrapper });
    const before = result.current.discontinuityEpoch;
    act(() => result.current.setMode("replay"));
    expect(result.current.mode).toBe("replay");
    expect(result.current.discontinuityEpoch).toBe(before + 1);
  });
});
