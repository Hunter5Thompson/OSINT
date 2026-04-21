import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import * as api from "../../services/api";
import { useEarthquakes } from "../../hooks/useEarthquakes";

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
});
