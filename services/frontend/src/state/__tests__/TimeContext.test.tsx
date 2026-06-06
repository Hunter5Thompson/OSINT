import type { ReactNode } from "react";
import { describe, it, expect } from "vitest";
import { renderHook, act } from "@testing-library/react";
import * as Cesium from "cesium";
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

  it("seek ignores a non-finite cursor (no NaN crash)", () => {
    const { result } = renderHook(() => useTime(), { wrapper });
    act(() => result.current.seek(1_700_000_000_000));
    act(() => result.current.seek(Number.NaN));
    expect(result.current.getTimeMs()).toBe(1_700_000_000_000); // unchanged
  });
});

describe("TimeContext clock seam (with a viewer)", () => {
  function fakeClockViewer() {
    const clock = {
      clockStep: Cesium.ClockStep.TICK_DEPENDENT,
      clockRange: Cesium.ClockRange.CLAMPED,
      currentTime: Cesium.JulianDate.now(),
      startTime: Cesium.JulianDate.now(),
      stopTime: Cesium.JulianDate.now(),
      multiplier: 1,
      shouldAnimate: false,
      onTick: { addEventListener: () => () => {} },
    };
    const viewer = { clock, isDestroyed: () => false } as unknown as Cesium.Viewer;
    return { viewer, clock };
  }

  it("animates the clock in live mode on viewer attach (L2-01)", () => {
    const { viewer, clock } = fakeClockViewer();
    renderHook(() => useTime(), {
      wrapper: ({ children }: { children: ReactNode }) => (
        <TimeProvider viewer={viewer}>{children}</TimeProvider>
      ),
    });
    expect(clock.shouldAnimate).toBe(true);
    expect(clock.clockStep).toBe(Cesium.ClockStep.SYSTEM_CLOCK);
    expect(clock.clockRange).toBe(Cesium.ClockRange.UNBOUNDED);
  });

  it("clamps the clock to the replay window (L2-02)", () => {
    const { viewer, clock } = fakeClockViewer();
    const { result } = renderHook(() => useTime(), {
      wrapper: ({ children }: { children: ReactNode }) => (
        <TimeProvider viewer={viewer}>{children}</TimeProvider>
      ),
    });
    const start = Date.parse("2026-05-01T00:00:00Z");
    const end = Date.parse("2026-05-01T06:00:00Z");
    act(() => {
      result.current.setReplayWindow(start, end);
      result.current.setMode("replay");
    });
    expect(clock.clockRange).toBe(Cesium.ClockRange.CLAMPED);
    expect(clock.clockStep).toBe(Cesium.ClockStep.SYSTEM_CLOCK_MULTIPLIER);
    expect(Cesium.JulianDate.toDate(clock.startTime).getTime()).toBe(start);
    expect(Cesium.JulianDate.toDate(clock.stopTime).getTime()).toBe(end);
  });
});
