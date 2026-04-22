import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import * as api from "../../services/api";
import { useEarthquakes } from "../../hooks/useEarthquakes";
import { useFIRMSHotspots } from "../../hooks/useFIRMSHotspots";
import { useAircraftTracks } from "../../hooks/useAircraftTracks";

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
