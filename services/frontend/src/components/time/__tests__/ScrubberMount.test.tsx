import { afterEach, describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, act, waitFor } from "@testing-library/react";
import * as Cesium from "cesium";
import * as api from "../../../services/api";
import { ScrubberMount } from "../ScrubberMount";
import { TimeProvider } from "../../../state/TimeContext";

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

const HIST = {
  t_start: "a", t_end: "b", bucket_ms: 1,
  buckets: [{ ts: "2026-06-01T00:00:00Z", count: 1, dominant_category: "civil", by_category: {}, by_severity: {} }],
  notables: [],
  geo_events: [{ id: "g1", time: "2026-06-01T00:00:00Z", severity: "high", lat: 1, lon: 2, is_incident: false }],
  total_count: 1, geo_located_count: 1, geo_truncated: false,
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
  (viewer: Cesium.Viewer | null, props: Parameters<typeof ScrubberMount>[0]) =>
  () => (
    <TimeProvider viewer={viewer}>
      <ScrubberMount {...props} />
    </TimeProvider>
  );

describe("ScrubberMount", () => {
  it("renders the ChronikTimeline strip", () => {
    vi.spyOn(api, "getTimeHistogram").mockResolvedValue(HIST as never);
    const Comp = wrap(null, { onSelectEvent: vi.fn(), onTimelineData: vi.fn() });
    render(<Comp />);
    expect(screen.getByTestId("chronik-strip")).toBeInTheDocument();
  });

  it("lifts geo_events up via onTimelineData", async () => {
    vi.spyOn(api, "getTimeHistogram").mockResolvedValue(HIST as never);
    const onTimelineData = vi.fn();
    const Comp = wrap(null, { onSelectEvent: vi.fn(), onTimelineData });
    render(<Comp />);
    await waitFor(() =>
      expect(onTimelineData).toHaveBeenCalledWith(
        expect.objectContaining({
          geoEvents: expect.arrayContaining([expect.objectContaining({ id: "g1" })]),
        }),
      ),
    );
  });

  it("click pauses the live clock, then NOW re-pins to now + resumes (HARD gates)", () => {
    vi.spyOn(api, "getTimeHistogram").mockResolvedValue(HIST as never);
    const { viewer, clock } = fakeClockViewer();
    const Comp = wrap(viewer, { onSelectEvent: vi.fn(), onTimelineData: vi.fn() });
    render(<Comp />);

    act(() => {
      const strip = screen.getByTestId("chronik-strip");
      fireEvent.mouseDown(strip, { clientX: 5 });
      fireEvent.mouseUp(strip, { clientX: 5 });
    });
    expect(clock.shouldAnimate).toBe(false); // paused on click

    act(() => {
      fireEvent.click(screen.getByLabelText("now"));
    });
    expect(clock.shouldAnimate).toBe(true); // resumed by play()
    const cursorMs = Cesium.JulianDate.toDate(clock.currentTime).getTime();
    expect(Math.abs(cursorMs - Date.now())).toBeLessThan(3000); // re-pinned to now (gate)
  });

  it("reverse-play sets a negative multiplier and animates", () => {
    vi.spyOn(api, "getTimeHistogram").mockResolvedValue(HIST as never);
    const { viewer, clock } = fakeClockViewer();
    const Comp = wrap(viewer, { onSelectEvent: vi.fn(), onTimelineData: vi.fn() });
    render(<Comp />);
    act(() => { fireEvent.click(screen.getByLabelText("reverse play")); });
    expect(clock.multiplier).toBeLessThan(0);
    expect(clock.shouldAnimate).toBe(true);
  });

  it("forward-play after reverse restores a positive multiplier", () => {
    vi.spyOn(api, "getTimeHistogram").mockResolvedValue(HIST as never);
    const { viewer, clock } = fakeClockViewer();
    const Comp = wrap(viewer, { onSelectEvent: vi.fn(), onTimelineData: vi.fn() });
    render(<Comp />);
    act(() => { fireEvent.click(screen.getByLabelText("reverse play")); });
    act(() => { fireEvent.click(screen.getByLabelText("forward play")); });
    expect(clock.multiplier).toBeGreaterThan(0);
  });

  it("step forward pauses and advances the cursor (deterministic, no wall-clock)", () => {
    vi.spyOn(api, "getTimeHistogram").mockResolvedValue(HIST as never);
    const { viewer, clock } = fakeClockViewer();
    const Comp = wrap(viewer, { onSelectEvent: vi.fn(), onTimelineData: vi.fn() });
    render(<Comp />);
    act(() => {
      const strip = screen.getByTestId("chronik-strip");
      fireEvent.mouseDown(strip, { clientX: 0 });
      fireEvent.mouseUp(strip, { clientX: 0 });
    });
    const atStart = Cesium.JulianDate.toDate(clock.currentTime).getTime();
    act(() => { fireEvent.click(screen.getByLabelText("step forward")); });
    expect(clock.shouldAnimate).toBe(false);
    const after = Cesium.JulianDate.toDate(clock.currentTime).getTime();
    expect(after).toBeGreaterThan(atStart);
  });

  it("NOW after reverse clears the reverse direction (speed back to positive)", () => {
    vi.spyOn(api, "getTimeHistogram").mockResolvedValue(HIST as never);
    const { viewer, clock } = fakeClockViewer();
    const Comp = wrap(viewer, { onSelectEvent: vi.fn(), onTimelineData: vi.fn() });
    render(<Comp />);
    act(() => { fireEvent.click(screen.getByLabelText("reverse play")); });
    act(() => { fireEvent.click(screen.getByLabelText("now")); });
    expect(clock.multiplier).toBeGreaterThan(0);
  });
});
