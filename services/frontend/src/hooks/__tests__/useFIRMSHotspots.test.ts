import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import * as api from "../../services/api";
import { useFIRMSHotspots } from "../useFIRMSHotspots";

describe("useFIRMSHotspots", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("fetches on mount when enabled", async () => {
    const spy = vi.spyOn(api, "getFIRMSHotspots").mockResolvedValue([
      {
        id: "h1", latitude: 48.1, longitude: 37.8, frp: 100, brightness: 390,
        confidence: "h", acq_date: "2026-04-11", acq_time: "1200",
        satellite: "VIIRS_SNPP_NRT", country_iso3: "UKR",
        firms_map_url: "https://example/",
      },
    ]);

    const { result } = renderHook(() => useFIRMSHotspots(true));
    await waitFor(() => expect(result.current.hotspots.length).toBe(1));
    expect(spy).toHaveBeenCalledTimes(1);
  });

  it("clears data when disabled", async () => {
    vi.spyOn(api, "getFIRMSHotspots").mockResolvedValue([
      {
        id: "h1", latitude: 0, longitude: 0, frp: 0, brightness: 0,
        confidence: "", acq_date: "", acq_time: "",
        satellite: "", country_iso3: null,
        firms_map_url: "",
      },
    ]);

    const { result, rerender } = renderHook(({ on }: { on: boolean }) => useFIRMSHotspots(on), {
      initialProps: { on: true },
    });
    await waitFor(() => expect(result.current.hotspots.length).toBe(1));

    rerender({ on: false });
    expect(result.current.hotspots.length).toBe(0);
  });
});
