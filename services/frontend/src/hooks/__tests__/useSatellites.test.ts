import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import gp from "../../../../../tests/fixtures/satellites/celestrak-100651.json";
import { useSatellites } from "../useSatellites";

const payload = {
  schema_version: 1, fetched_at: "2026-10-09T23:06:11.823566Z",
  satellites: [{
    norad_id: 100651, name: gp.OBJECT_NAME, category: "active", operator_country: null,
    satellite_type: "unknown", inclination_deg: gp.INCLINATION, period_min: 1440 / gp.MEAN_MOTION,
    orbit: { format: "omm", elements: { ...gp, EPOCH: gp.EPOCH + "Z",
      CENTER_NAME: "EARTH", REF_FRAME: "TEME", TIME_SYSTEM: "UTC", MEAN_ELEMENT_THEORY: "SGP4" } },
  }],
  coverage: { completeness: "complete", groups: [{
    group: "active", status: "ok", accepted_records: 1,
    rejected_invalid: 0, rejected_unsupported: 0, rejections: [], failure_code: null,
  }] },
};

describe("useSatellites snapshot", () => {
  afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });
  it("delivers six-digit OMM data and preserves source fetch time", async () => {
    const fetch = vi.fn<typeof globalThis.fetch>().mockImplementation(async input =>
      Response.json(String(input).endsWith("/satellites/orbits") ? payload : []));
    vi.stubGlobal("fetch", fetch);
    const { result } = renderHook(() => useSatellites(true));
    await waitFor(() => expect(result.current.satellites[0]?.norad_id).toBe(100651));
    expect(result.current.lastUpdate?.toISOString()).toBe("2026-10-09T23:06:11.823Z");
  });

  it("rejects a resolved response from a disabled generation", async () => {
    let resolve!: (value: Response) => void;
    const pending = new Promise<Response>(done => { resolve = done; });
    vi.stubGlobal("fetch", vi.fn<typeof globalThis.fetch>().mockReturnValue(pending));
    const { result, rerender } = renderHook(({ enabled }) => useSatellites(enabled), { initialProps: { enabled: true } });
    rerender({ enabled: false });
    await act(async () => { resolve(Response.json(payload)); });
    expect(result.current.satellites).toEqual([]);
    expect(result.current.loading).toBe(false);
    expect(result.current.lastUpdate).toBeNull();
  });

  it("keeps the newest hourly response when an older request resolves late", async () => {
    vi.useFakeTimers();
    const pending: ((value: Response) => void)[] = [];
    const signals: (AbortSignal | null | undefined)[] = [];
    vi.stubGlobal("fetch", vi.fn<typeof globalThis.fetch>().mockImplementation((_input, init) => {
      signals.push(init?.signal);
      return new Promise<Response>(done => { pending.push(done); });
    }));
    const { result } = renderHook(() => useSatellites(true));
    act(() => vi.advanceTimersByTime(3_600_000));
    await act(async () => { pending[1]!(Response.json({ ...payload, fetched_at: "2026-10-10T00:06:11.823566Z" })); });
    await act(async () => { pending[0]!(Response.json(payload)); });
    expect(result.current.lastUpdate?.toISOString()).toBe("2026-10-10T00:06:11.823Z");
    expect(signals[0]?.aborted).toBe(true);
    expect(result.current.loading).toBe(false);
  });

  it("does not accept the old generation after disable and reenable", async () => {
    const pending: ((value: Response) => void)[] = [];
    vi.stubGlobal("fetch", vi.fn<typeof globalThis.fetch>().mockImplementation(() =>
      new Promise<Response>(done => { pending.push(done); })));
    const { result, rerender } = renderHook(({ enabled }) => useSatellites(enabled), { initialProps: { enabled: true } });
    rerender({ enabled: false });
    rerender({ enabled: true });
    await act(async () => { pending[1]!(Response.json({ ...payload, fetched_at: "2026-10-10T00:06:11.823566Z" })); });
    await act(async () => { pending[0]!(Response.json(payload)); });
    expect(result.current.lastUpdate?.toISOString()).toBe("2026-10-10T00:06:11.823Z");
  });

  it("reports a failed fetch instead of a silently empty successful state", async () => {
    vi.stubGlobal("fetch", vi.fn<typeof globalThis.fetch>().mockRejectedValue(new Error("Network unavailable")));
    const { result } = renderHook(() => useSatellites(true));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current).toHaveProperty("error", "Network unavailable");
  });
});
