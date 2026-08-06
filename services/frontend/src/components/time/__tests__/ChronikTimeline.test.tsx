import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ChronikTimeline } from "../ChronikTimeline";
import { EVENT_COLORS } from "../../layers/EventLayer";
import type { HistogramBucket, SpatialApplicationV1, TimelineNotable } from "../../../types";

const buckets: HistogramBucket[] = [
  { ts: "2026-06-01T00:00:00Z", count: 200, dominant_category: "civil", by_category: { civil: 200, military: 1 }, by_severity: { low: 200, critical: 1 } },
  { ts: "2026-06-01T01:00:00Z", count: 10, dominant_category: "military", by_category: { military: 10 }, by_severity: { high: 10 } },
];
const notables: TimelineNotable[] = [
  { id: "n1", time: "2026-06-01T00:45:00Z", time_basis: "indexed", severity: "critical", title: "Strike", is_incident: true, rank: 0 },
];
const globalApplication: SpatialApplicationV1 = {
  schema_version: 1,
  requested_scope_key: null,
  catalog_revision: null,
  derivation_revision: null,
  boundary_policy: null,
  relation: "occurs-in",
  mode: "global",
  completeness: "complete",
  included_count: 210,
  excluded_unlocated_count: 0,
  excluded_conflict_count: 0,
  excluded_stale_revision_count: 0,
};
const partialApplication: SpatialApplicationV1 = {
  ...globalApplication,
  requested_scope_key: "country:UKR",
  catalog_revision: "spatial-v1-123456789abc",
  derivation_revision: "spatial-derive-v1-123456789abc",
  boundary_policy: "natural-earth-admin-v1",
  mode: "bbox_approximate",
  completeness: "partial",
  included_count: 207,
  excluded_unlocated_count: 2,
  excluded_conflict_count: 1,
};
const base = {
  buckets, notables, rangeStartMs: Date.parse("2026-06-01T00:00:00Z"),
  rangeEndMs: Date.parse("2026-06-01T02:00:00Z"), cursorMs: Date.parse("2026-06-01T01:00:00Z"),
  mode: "live" as const, playing: true, preset: "7d" as const,
  geoLocatedCount: 3, totalCount: 210,
  onSeek: vi.fn(), onBrush: vi.fn(), onSelectNotable: vi.fn(),
  onTogglePlay: vi.fn(), onNow: vi.fn(), onPreset: vi.fn(),
  speed: 1,
  onStepBack: vi.fn(),
  onStepForward: vi.fn(),
  onReverse: vi.fn(),
  onForward: vi.fn(),
  onSetSpeedMagnitude: vi.fn(),
  spatialApplication: globalApplication,
  spatialLoading: false,
  spatialError: null,
};

describe("ChronikTimeline", () => {
  it("colours bars by dominant_category via EVENT_COLORS (NOT severity)", () => {
    render(<ChronikTimeline {...base} />);
    const bars = screen.getAllByTestId("chronik-bar");
    expect(bars[0]).toHaveStyle(`background: ${EVENT_COLORS.civil}`); // civil, not critical
    expect(bars[1]).toHaveStyle(`background: ${EVENT_COLORS.military}`);
  });
  it("renders one notable dot and selecting it calls onSelectNotable", () => {
    render(<ChronikTimeline {...base} />);
    const dot = screen.getByRole("button", { name: /Strike/i });
    fireEvent.click(dot);
    expect(base.onSelectNotable).toHaveBeenCalledWith("n1");
  });
  it("shows the located honesty line", () => {
    render(<ChronikTimeline {...base} />);
    expect(screen.getByText(/3\s*\/\s*210/)).toBeInTheDocument();
  });
  it("click on the strip seeks (does not brush)", () => {
    render(<ChronikTimeline {...base} />);
    const strip = screen.getByTestId("chronik-strip");
    fireEvent.mouseDown(strip, { clientX: 10 });
    fireEvent.mouseUp(strip, { clientX: 10 }); // no drag -> click
    expect(base.onSeek).toHaveBeenCalledTimes(1);
    expect(base.onBrush).not.toHaveBeenCalled();
  });
  it("clicking a notable dot selects it WITHOUT seeking (no bubble to strip) (#4)", () => {
    // fresh spies — `base.*` are module-level vi.fn()s shared (and called) by other tests
    const onSeek = vi.fn();
    const onBrush = vi.fn();
    const onSelectNotable = vi.fn();
    render(
      <ChronikTimeline {...base} onSeek={onSeek} onBrush={onBrush} onSelectNotable={onSelectNotable} />,
    );
    const dot = screen.getByRole("button", { name: /Strike/i });
    fireEvent.mouseDown(dot, { clientX: 50 });
    fireEvent.mouseUp(dot, { clientX: 50 });
    fireEvent.click(dot);
    expect(onSelectNotable).toHaveBeenCalledWith("n1");
    expect(onSeek).not.toHaveBeenCalled();
    expect(onBrush).not.toHaveBeenCalled();
  });

  it("labels a complete global response from spatial application accounting", () => {
    render(<ChronikTimeline {...base} />);
    expect(screen.getByTestId("chronik-spatial-status")).toHaveTextContent("global · complete");
  });

  it("shows scope loading before a response is available", () => {
    render(
      <ChronikTimeline
        {...base}
        spatialApplication={null}
        spatialLoading={true}
      />,
    );
    expect(screen.getByTestId("chronik-spatial-status")).toHaveTextContent("scope loading");
  });

  it("labels bbox approximation, partial coverage, relation, and exclusions", () => {
    render(<ChronikTimeline {...base} spatialApplication={partialApplication} />);
    const status = screen.getByTestId("chronik-spatial-status");
    expect(status).toHaveTextContent("occurs-in · bbox approx · partial");
    expect(status).toHaveTextContent("excluded 3");
  });

  it("shows scope unavailable on a request or contract failure", () => {
    render(
      <ChronikTimeline
        {...base}
        spatialApplication={null}
        spatialLoading={false}
        spatialError={new Error("backend unavailable")}
      />,
    );
    expect(screen.getByTestId("chronik-spatial-status")).toHaveTextContent("scope unavailable");
  });

  it("does not label a movement intersection as an occurs-in result", () => {
    render(
      <ChronikTimeline
        {...base}
        spatialApplication={{ ...partialApplication, relation: "intersects" }}
      />,
    );
    const status = screen.getByTestId("chronik-spatial-status");
    expect(status).toHaveTextContent("intersects · bbox approx · partial");
    expect(status).not.toHaveTextContent("occurs-in");
  });
});
