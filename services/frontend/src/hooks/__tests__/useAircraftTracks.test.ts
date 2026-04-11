import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import * as api from "../../services/api";
import { useAircraftTracks } from "../useAircraftTracks";

describe("useAircraftTracks", () => {
  beforeEach(() => vi.useFakeTimers({ shouldAdvanceTime: true }));
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("fetches on mount when enabled", async () => {
    const spy = vi.spyOn(api, "getAircraftTracks").mockResolvedValue([
      {
        icao24: "AE1234", callsign: "RCH842", type_code: "C17",
        military_branch: "USAF", registration: "05-5140",
        points: [{ lat: 51, lon: 12, altitude_m: 10000, speed_ms: 240, heading: 90, timestamp: 1744300000 }],
      },
    ]);

    const { result } = renderHook(() => useAircraftTracks(true));
    await waitFor(() => expect(result.current.tracks.length).toBe(1));
    expect(spy).toHaveBeenCalledTimes(1);
  });

  it("clears data when disabled", async () => {
    vi.spyOn(api, "getAircraftTracks").mockResolvedValue([
      {
        icao24: "X", callsign: null, type_code: null, military_branch: null, registration: null,
        points: [],
      },
    ]);
    const { result, rerender } = renderHook(({ on }: { on: boolean }) => useAircraftTracks(on), {
      initialProps: { on: true },
    });
    await waitFor(() => expect(result.current.tracks.length).toBe(1));
    rerender({ on: false });
    expect(result.current.tracks.length).toBe(0);
  });
});
