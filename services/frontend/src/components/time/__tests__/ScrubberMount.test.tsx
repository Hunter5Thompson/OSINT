import { afterEach, describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, act, waitFor } from "@testing-library/react";
import * as Cesium from "cesium";
import * as api from "../../../services/api";
import { ScrubberMount } from "../ScrubberMount";
import { TimeProvider } from "../../../state/TimeContext";
import {
  parseCatalogRevision,
  parseScopeKeyCandidate,
  type SpatialQueryRef,
} from "../../../spatial/contracts";
import type { HistogramResponse, TimeHistogramQuery } from "../../../types";

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

const HIST: HistogramResponse = {
  t_start: "a", t_end: "b", bucket_ms: 1,
  buckets: [{ ts: "2026-06-01T00:00:00Z", count: 1, dominant_category: "civil", by_category: {}, by_severity: {} }],
  notables: [],
  geo_events: [{ id: "g1", time: "2026-06-01T00:00:00Z", severity: "high", lat: 1, lon: 2, is_incident: false }],
  total_count: 1, geo_located_count: 1, geo_truncated: false,
  spatial_application: {
    schema_version: 1,
    requested_scope_key: null,
    catalog_revision: null,
    derivation_revision: null,
    boundary_policy: null,
    relation: "occurs-in",
    mode: "global",
    completeness: "complete",
    included_count: 1,
    excluded_unlocated_count: 0,
    excluded_conflict_count: 0,
    excluded_stale_revision_count: 0,
  },
};

function scope(scopeKey: string): SpatialQueryRef {
  return {
    schemaVersion: 1,
    scopeKey: parseScopeKeyCandidate(scopeKey),
    catalogRevision: parseCatalogRevision("spatial-v1-123456789abc"),
    boundaryPolicy: "natural-earth-admin-v1",
  };
}

function scopedHistogram(spatialScope: SpatialQueryRef): HistogramResponse {
  return {
    ...HIST,
    spatial_application: {
      ...HIST.spatial_application,
      requested_scope_key: spatialScope.scopeKey,
      catalog_revision: spatialScope.catalogRevision,
      derivation_revision: "spatial-derive-v1-123456789abc",
      boundary_policy: spatialScope.boundaryPolicy,
      mode: "bbox_approximate",
      completeness: "partial",
    },
  };
}

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

  it("does not request a legacy-global histogram while spatial scope is hydrating", () => {
    const spy = vi.spyOn(api, "getTimeHistogram").mockResolvedValue(HIST);
    const Comp = wrap(null, {
      onSelectEvent: vi.fn(),
      onTimelineData: vi.fn(),
      spatialScope: null,
      scopeGeneration: 0,
    });

    render(<Comp />);

    expect(spy).not.toHaveBeenCalled();
  });

  it("preserves time state and range while replacing the committed scope", async () => {
    const ukraine = scope("country:UKR");
    const poland = scope("country:POL");
    const calls: TimeHistogramQuery[] = [];
    vi.spyOn(api, "getTimeHistogram").mockImplementation(async (request) => {
      calls.push(request);
      if (!request.spatialScope) throw new Error("unexpected legacy fallback");
      return scopedHistogram(request.spatialScope);
    });
    const { viewer, clock } = fakeClockViewer();
    const onSelectEvent = vi.fn();
    const onTimelineData = vi.fn();
    const renderTree = (spatialScope: SpatialQueryRef, scopeGeneration: number) => (
      <TimeProvider viewer={viewer}>
        <ScrubberMount
          onSelectEvent={onSelectEvent}
          onTimelineData={onTimelineData}
          spatialScope={spatialScope}
          scopeGeneration={scopeGeneration}
        />
      </TimeProvider>
    );
    const mounted = render(renderTree(ukraine, 1));
    await waitFor(() => expect(calls.some((request) => request.spatialScope === ukraine)).toBe(true));
    const ukraineRequest = calls.filter((request) => request.spatialScope === ukraine).at(-1);

    act(() => {
      fireEvent.click(screen.getByLabelText("reverse play"));
      const strip = screen.getByTestId("chronik-strip");
      fireEvent.mouseDown(strip, { clientX: 1 });
      fireEvent.mouseUp(strip, { clientX: 1 });
    });
    const cursorBeforeScopeChange = Cesium.JulianDate.toDate(clock.currentTime).getTime();
    expect(clock.multiplier).toBeLessThan(0);
    expect(screen.getByText("▶ REPLAY")).toBeInTheDocument();
    expect(calls.every((request) => request.spatialScope === ukraine)).toBe(true);

    mounted.rerender(renderTree(poland, 2));
    await waitFor(() => expect(calls.some((request) => request.spatialScope === poland)).toBe(true));
    const polandRequest = calls.find((request) => request.spatialScope === poland);

    expect(polandRequest?.tStart).toBe(ukraineRequest?.tStart);
    expect(polandRequest?.tEnd).toBe(ukraineRequest?.tEnd);
    expect(Cesium.JulianDate.toDate(clock.currentTime).getTime()).toBe(cursorBeforeScopeChange);
    expect(clock.multiplier).toBeLessThan(0);
    expect(screen.getByText("▶ REPLAY")).toBeInTheDocument();
    expect(calls.every((request) => request.spatialScope !== undefined)).toBe(true);
  });

  it("removes stale bars synchronously when the breadcrumb scope changes", async () => {
    const ukraine = scope("country:UKR");
    const poland = scope("country:POL");
    const pendingPoland = new Promise<HistogramResponse>(() => {});
    vi.spyOn(api, "getTimeHistogram").mockImplementation((request) => {
      if (request.spatialScope === ukraine) return Promise.resolve(scopedHistogram(ukraine));
      return pendingPoland;
    });
    const onSelectEvent = vi.fn();
    const onTimelineData = vi.fn();
    const renderTree = (spatialScope: SpatialQueryRef, scopeGeneration: number) => (
      <TimeProvider viewer={null}>
        <ScrubberMount
          onSelectEvent={onSelectEvent}
          onTimelineData={onTimelineData}
          spatialScope={spatialScope}
          scopeGeneration={scopeGeneration}
        />
      </TimeProvider>
    );
    const mounted = render(renderTree(ukraine, 1));
    await waitFor(() => expect(screen.getAllByTestId("chronik-bar")).toHaveLength(1));

    mounted.rerender(renderTree(poland, 2));

    expect(screen.queryAllByTestId("chronik-bar")).toHaveLength(0);
    expect(screen.getByTestId("chronik-spatial-status")).toHaveTextContent("scope loading");
  });
});
