import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "../../services/api";
import type { Aircraft } from "../../types";
import { useFlights } from "../useFlights";

beforeEach(() => vi.useFakeTimers());
afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); });

describe("useFlights observable errors", () => {
  it("keeps failed first request distinct from a successful empty snapshot and clears error on recovery", async () => {
    const request = vi.spyOn(api, "getFlights").mockRejectedValueOnce(new Error("secret upstream body"));
    const { result } = renderHook(() => useFlights(true));
    await act(async () => { await Promise.resolve(); });
    expect(result.current.error).toBe("unavailable");
    expect(result.current.lastUpdate).toBeNull();
    request.mockResolvedValueOnce([]);
    await act(async () => { await vi.advanceTimersByTimeAsync(15_000); });
    expect(result.current.error).toBeNull();
    expect(result.current.flights).toEqual([]);
    expect(result.current.lastUpdate).toBeInstanceOf(Date);
  });
  it("keeps the successful contact and receipt time after refresh failure", async () => {
    const contact: Aircraft = { icao24: "synthetic", callsign: null, latitude: 0, longitude: 0,
      altitude_m: null, velocity_ms: null, heading: null, vertical_rate: null,
      on_ground: false, is_military: false, aircraft_type: null, last_contact: null };
    const request = vi.spyOn(api, "getFlights").mockResolvedValueOnce([contact]);
    const { result } = renderHook(() => useFlights(true));
    await act(async () => { await Promise.resolve(); });
    const receipt = result.current.lastUpdate;
    request.mockRejectedValueOnce(new Error("offline"));
    await act(async () => { await vi.advanceTimersByTimeAsync(15_000); });
    expect(result.current.error).toBe("unavailable");
    expect(result.current.flights).toEqual([contact]);
    expect(result.current.lastUpdate).toBe(receipt);
  });
  it("ignores a stale failure after disable and reenable", async () => {
    let reject!: (error: Error) => void;
    vi.spyOn(api, "getFlights").mockReturnValueOnce(new Promise((_, r) => { reject = r; })).mockResolvedValueOnce([]);
    const { result, rerender } = renderHook(({ enabled }) => useFlights(enabled), { initialProps: { enabled: true } });
    rerender({ enabled: false });
    rerender({ enabled: true });
    await act(async () => { await Promise.resolve(); });
    const receipt = result.current.lastUpdate;
    await act(async () => { reject(new Error("old failure")); });
    expect(result.current.error).toBeNull();
    expect(result.current.lastUpdate).toBe(receipt);
  });
});
