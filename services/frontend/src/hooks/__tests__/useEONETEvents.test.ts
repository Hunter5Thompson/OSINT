import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import * as api from "../../services/api";
import { useEONETEvents } from "../useEONETEvents";

const mockEvent = {
  id: "EONET_5678",
  title: "Hawaii Volcanic Activity",
  category: "volcanoes",
  status: "open",
  latitude: 19.4,
  longitude: -155.3,
  event_date: "2026-04-10T00:00:00Z",
};

describe("useEONETEvents", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("fetches on mount when enabled", async () => {
    const spy = vi.spyOn(api, "getEONETEvents").mockResolvedValue([mockEvent]);

    const { result } = renderHook(() => useEONETEvents(true));
    await waitFor(() => expect(result.current.events.length).toBe(1));
    expect(spy).toHaveBeenCalledTimes(1);
  });

  it("clears data when disabled", async () => {
    vi.spyOn(api, "getEONETEvents").mockResolvedValue([mockEvent]);

    const { result, rerender } = renderHook(({ on }: { on: boolean }) => useEONETEvents(on), {
      initialProps: { on: true },
    });
    await waitFor(() => expect(result.current.events.length).toBe(1));

    rerender({ on: false });
    expect(result.current.events.length).toBe(0);
  });

  it("does not fetch when disabled", () => {
    const spy = vi.spyOn(api, "getEONETEvents").mockResolvedValue([]);
    renderHook(() => useEONETEvents(false));
    expect(spy).not.toHaveBeenCalled();
  });

  it("keeps stale data on error", async () => {
    vi.spyOn(api, "getEONETEvents").mockResolvedValueOnce([mockEvent]);
    const { result } = renderHook(() => useEONETEvents(true));
    await waitFor(() => expect(result.current.events.length).toBe(1));

    vi.spyOn(api, "getEONETEvents").mockRejectedValueOnce(new Error("network fail"));
    await vi.advanceTimersByTimeAsync(120_000);
    expect(result.current.events.length).toBe(1);
  });
});
