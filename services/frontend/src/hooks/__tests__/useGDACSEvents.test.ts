import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import * as api from "../../services/api";
import { useGDACSEvents } from "../useGDACSEvents";

const mockEvent = {
  id: "1103127",
  event_type: "TC",
  event_name: "Tropical Cyclone IGOR",
  alert_level: "Orange",
  severity: 2.5,
  country: "Philippines",
  latitude: 12.5,
  longitude: 124.0,
  from_date: "2026-04-08T00:00:00Z",
  to_date: "2026-04-12T00:00:00Z",
};

describe("useGDACSEvents", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("fetches on mount when enabled", async () => {
    const spy = vi.spyOn(api, "getGDACSEvents").mockResolvedValue([mockEvent]);

    const { result } = renderHook(() => useGDACSEvents(true));
    await waitFor(() => expect(result.current.events.length).toBe(1));
    expect(spy).toHaveBeenCalledTimes(1);
  });

  it("clears data when disabled", async () => {
    vi.spyOn(api, "getGDACSEvents").mockResolvedValue([mockEvent]);

    const { result, rerender } = renderHook(({ on }: { on: boolean }) => useGDACSEvents(on), {
      initialProps: { on: true },
    });
    await waitFor(() => expect(result.current.events.length).toBe(1));

    rerender({ on: false });
    expect(result.current.events.length).toBe(0);
  });

  it("does not fetch when disabled", () => {
    const spy = vi.spyOn(api, "getGDACSEvents").mockResolvedValue([]);
    renderHook(() => useGDACSEvents(false));
    expect(spy).not.toHaveBeenCalled();
  });

  it("keeps stale data on error", async () => {
    vi.spyOn(api, "getGDACSEvents").mockResolvedValueOnce([mockEvent]);
    const { result } = renderHook(() => useGDACSEvents(true));
    await waitFor(() => expect(result.current.events.length).toBe(1));

    vi.spyOn(api, "getGDACSEvents").mockRejectedValueOnce(new Error("network fail"));
    await vi.advanceTimersByTimeAsync(120_000);
    expect(result.current.events.length).toBe(1);
  });
});
