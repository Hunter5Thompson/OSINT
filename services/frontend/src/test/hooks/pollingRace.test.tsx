import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import * as api from "../../services/api";
import { useEarthquakes } from "../../hooks/useEarthquakes";
import { useFIRMSHotspots } from "../../hooks/useFIRMSHotspots";
import { useAircraftTracks } from "../../hooks/useAircraftTracks";
import { useFlights } from "../../hooks/useFlights";
import { useVessels } from "../../hooks/useVessels";

describe("useEarthquakes cancelled guard", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("does not setState after unmount when fetch resolves late", async () => {
    let resolve!: (v: unknown) => void;
    const pending = new Promise<unknown>((r) => { resolve = r; });
    vi.spyOn(api, "getEarthquakes").mockReturnValue(pending as never);

    const { result, unmount } = renderHook(() => useEarthquakes(true));
    unmount();

    // Resolve AFTER unmount — must not produce a React warning and list stays empty.
    await act(async () => {
      resolve([{ id: "eq1", latitude: 0, longitude: 0, magnitude: 4.5, time: "2026-04-21T00:00:00Z" }]);
      await Promise.resolve();
    });

    expect(result.current.earthquakes).toEqual([]);
  });

  it("resets loading to false when disabled mid-fetch", async () => {
    let resolveFetch!: (v: unknown) => void;
    const pending = new Promise<unknown>((r) => { resolveFetch = r; });
    vi.spyOn(api, "getEarthquakes").mockReturnValue(pending as never);

    const { result, rerender } = renderHook(
      ({ enabled }) => useEarthquakes(enabled),
      { initialProps: { enabled: true } },
    );

    // Wait for the fetch to start and loading to flip true.
    await waitFor(() => expect(result.current.loading).toBe(true));

    // Toggle off BEFORE the fetch resolves.
    rerender({ enabled: false });

    // The late resolve must not leave loading stuck at true.
    await act(async () => {
      resolveFetch([]);
      await Promise.resolve();
    });

    expect(result.current.loading).toBe(false);
  });
});

describe("useFIRMSHotspots cancelled guard", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("resets loading to false when disabled mid-fetch", async () => {
    let resolveFetch!: (v: unknown) => void;
    const pending = new Promise<unknown>((r) => { resolveFetch = r; });
    vi.spyOn(api, "getFIRMSHotspots").mockReturnValue(pending as never);

    const { result, rerender } = renderHook(
      ({ enabled }) => useFIRMSHotspots(enabled),
      { initialProps: { enabled: true } },
    );

    await waitFor(() => expect(result.current.loading).toBe(true));
    rerender({ enabled: false });

    await act(async () => {
      resolveFetch([]);
      await Promise.resolve();
    });

    expect(result.current.loading).toBe(false);
  });
});

describe("useAircraftTracks cancelled guard", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("resets loading to false when disabled mid-fetch", async () => {
    let resolveFetch!: (v: unknown) => void;
    const pending = new Promise<unknown>((r) => { resolveFetch = r; });
    vi.spyOn(api, "getAircraftTracks").mockReturnValue(pending as never);

    const { result, rerender } = renderHook(
      ({ enabled }) => useAircraftTracks(enabled),
      { initialProps: { enabled: true } },
    );

    await waitFor(() => expect(result.current.loading).toBe(true));
    rerender({ enabled: false });

    await act(async () => {
      resolveFetch([]);
      await Promise.resolve();
    });

    expect(result.current.loading).toBe(false);
  });
});

describe("useFlights cancelled guard", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("ignores a late resolve after the hook is disabled", async () => {
    let resolveFetch!: (v: unknown) => void;
    const pending = new Promise<unknown>((r) => { resolveFetch = r; });
    vi.spyOn(api, "getFlights").mockReturnValue(pending as never);

    const { result, rerender } = renderHook(
      ({ enabled }) => useFlights(enabled),
      { initialProps: { enabled: true } },
    );

    await waitFor(() => expect(result.current.loading).toBe(true));
    rerender({ enabled: false });

    await act(async () => {
      resolveFetch([
        {
          icao24: "abc123",
          callsign: "ODIN1",
          latitude: 1,
          longitude: 2,
          altitude_m: 1000,
          velocity_ms: 200,
          heading: 90,
          vertical_rate: 0,
          on_ground: false,
          last_contact: "2026-06-24T10:00:00Z",
          is_military: false,
          aircraft_type: null,
        },
      ]);
      await Promise.resolve();
    });

    expect(result.current.loading).toBe(false);
    expect(result.current.flights).toEqual([]);
  });
});

describe("useVessels cancelled guard", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("ignores a late resolve after the hook is disabled", async () => {
    let resolveFetch!: (v: unknown) => void;
    const pending = new Promise<unknown>((r) => { resolveFetch = r; });
    vi.spyOn(api, "getVessels").mockReturnValue(pending as never);

    const { result, rerender } = renderHook(
      ({ enabled }) => useVessels(enabled),
      { initialProps: { enabled: true } },
    );

    await waitFor(() => expect(result.current.loading).toBe(true));
    rerender({ enabled: false });

    await act(async () => {
      resolveFetch([
        {
          mmsi: 123456789,
          name: "ODIN SEA",
          latitude: 1,
          longitude: 2,
          speed_knots: 12,
          course: 180,
          ship_type: 70,
          destination: null,
        },
      ]);
      await Promise.resolve();
    });

    expect(result.current.loading).toBe(false);
    expect(result.current.vessels).toEqual([]);
  });
});
