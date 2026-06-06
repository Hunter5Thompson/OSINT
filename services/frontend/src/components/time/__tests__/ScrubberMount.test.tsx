import { afterEach, describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import * as Cesium from "cesium";
import * as api from "../../../services/api";
import { ScrubberMount } from "../ScrubberMount";
import { TimeProvider } from "../../../state/TimeContext";

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

const EMPTY = {
  domain: "events", tier: "coarse", t_start: "", t_end: "", bbox: null,
  samples: [], total_count: 0, truncated: false,
} as const;

function fakeClockViewer() {
  const clock = {
    clockStep: Cesium.ClockStep.TICK_DEPENDENT,
    clockRange: Cesium.ClockRange.UNBOUNDED,
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

const wrap =
  (viewer: Cesium.Viewer | null, onSelectWindow: (w: { tStart: string; tEnd: string }) => void) =>
  () => (
    <TimeProvider viewer={viewer}>
      <ScrubberMount onSelectWindow={onSelectWindow} />
    </TimeProvider>
  );

describe("ScrubberMount", () => {
  it("toggling to replay clamps the Cesium clock to a window (P1)", () => {
    vi.spyOn(api, "getTimeWindow").mockResolvedValue(EMPTY as never);
    const { viewer, clock } = fakeClockViewer();
    const Comp = wrap(viewer, () => {});
    render(<Comp />);

    expect(clock.clockRange).toBe(Cesium.ClockRange.UNBOUNDED); // live on mount
    act(() => {
      fireEvent.click(screen.getByLabelText("toggle mode"));
    });

    expect(clock.clockRange).toBe(Cesium.ClockRange.CLAMPED);
    expect(clock.clockStep).toBe(Cesium.ClockStep.SYSTEM_CLOCK_MULTIPLIER);
    const span =
      Cesium.JulianDate.toDate(clock.stopTime).getTime() -
      Cesium.JulianDate.toDate(clock.startTime).getTime();
    // ~6h window (JulianDate<->Date round-trips lose sub-ms precision)
    expect(Math.abs(span - 6 * 3600_000)).toBeLessThan(5);
  });

  it("notifies the parent of the replay window on toggle (P1)", () => {
    vi.spyOn(api, "getTimeWindow").mockResolvedValue(EMPTY as never);
    const onSelectWindow = vi.fn();
    const Comp = wrap(null, onSelectWindow);
    render(<Comp />);
    act(() => {
      fireEvent.click(screen.getByLabelText("toggle mode"));
    });
    expect(onSelectWindow).toHaveBeenCalledTimes(1);
    const w = onSelectWindow.mock.calls[0]![0];
    expect(Date.parse(w.tEnd) - Date.parse(w.tStart)).toBe(6 * 3600_000);
  });

  it("rolls the coarse event window forward over time (P2)", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-06-01T00:00:00Z"));
    const spy = vi.spyOn(api, "getTimeWindow").mockResolvedValue(EMPTY as never);
    const Comp = wrap(null, () => {});
    render(<Comp />);

    const firstEnd = Date.parse(spy.mock.calls[0]![0].tEnd);
    act(() => {
      vi.advanceTimersByTime(61_000); // past the 60s roll interval
    });
    const ends = spy.mock.calls.map((c) => Date.parse(c[0].tEnd));
    expect(Math.max(...ends)).toBeGreaterThan(firstEnd); // window advanced
  });
});
