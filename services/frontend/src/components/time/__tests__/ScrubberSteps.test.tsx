import { act, cleanup, render } from "@testing-library/react";
import type { ComponentProps } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as time from "../../../state/TimeContext";
import * as histogram from "../../../hooks/useTimeHistogram";
import type { HistogramResponse } from "../../../types";
import type { ChronikTimeline } from "../ChronikTimeline";
import { ScrubberMount } from "../ScrubberMount";

const capture: { props: ComponentProps<typeof ChronikTimeline> | null } = { props: null };
vi.mock("../ChronikTimeline", () => ({ ChronikTimeline: (props: ComponentProps<typeof ChronikTimeline>) => {
  capture.props = props;
  return null;
} }));
afterEach(() => { cleanup(); vi.restoreAllMocks(); capture.props = null; });

describe("Scrubber requested grid", () => {
  it.each([null, 0, 2, 120])("steps 12 minutes in a 24h grid with %s occupied bins", (occupied) => {
    const seek = vi.fn();
    let mode: "live" | "replay" = "live";
    let cursorMs = Date.now() - 12 * 3600_000;
    vi.spyOn(time, "useTime").mockImplementation(() => ({
      mode, cursorMs, playing: false, speed: 1, seek, pause: vi.fn(), play: vi.fn(),
      setMode: (value) => { mode = value; }, setReplayWindow: vi.fn(), setSpeed: vi.fn(),
      discontinuityEpoch: 0, getTimeMs: () => cursorMs,
    }));
    const data = occupied === null ? null : { buckets: Array.from({ length: occupied }, () => ({})), geo_events: [] } as unknown as HistogramResponse;
    vi.spyOn(histogram, "useTimeHistogram").mockReturnValue({ data, loading: occupied === null, error: null });
    render(<ScrubberMount onSelectEvent={vi.fn()} onTimelineData={vi.fn()} />);
    act(() => capture.props!.onPreset("24h"));
    act(() => capture.props!.onStepForward());
    expect(seek).toHaveBeenLastCalledWith(cursorMs + 12 * 60_000);
    act(() => capture.props!.onStepBack());
    expect(seek).toHaveBeenLastCalledWith(cursorMs - 12 * 60_000);

    const start = cursorMs;
    const end = start + 18 * 60_000;
    act(() => capture.props!.onBrush(start, end));
    act(() => capture.props!.onStepForward());
    expect(seek).toHaveBeenLastCalledWith(start + 12 * 60_000);
    cursorMs = end - 60_000;
    act(() => capture.props!.onPreset("7d")); // rerender and switch to the coarser requested grid
    act(() => capture.props!.onStepForward());
    expect(seek).toHaveBeenLastCalledWith(end);
  });
});
