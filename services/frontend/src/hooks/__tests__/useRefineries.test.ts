import { describe, it, expect, vi, afterEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { useRefineries } from "../useRefineries";

const MOCK_GEOJSON = {
  type: "FeatureCollection" as const,
  features: [
    {
      type: "Feature" as const,
      geometry: { type: "Point" as const, coordinates: [72.0, 22.3] },
      properties: {
        name: "Test Refinery",
        operator: "TestOil",
        capacity_bpd: 500000,
        country: "IN",
        status: "active" as const,
      },
    },
  ],
};

describe("useRefineries", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("does not fetch when disabled", () => {
    const spy = vi.spyOn(globalThis, "fetch");
    renderHook(() => useRefineries(false));
    expect(spy).not.toHaveBeenCalled();
  });

  it("fetches GeoJSON when enabled", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => MOCK_GEOJSON,
    } as Response);

    const { result } = renderHook(() => useRefineries(true));
    await waitFor(() => expect(result.current.refineries).not.toBeNull());
    expect(result.current.refineries!.features).toHaveLength(1);
    expect(result.current.lastUpdate).toBeInstanceOf(Date);
  });

  it("does not re-fetch once loaded", async () => {
    const spy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => MOCK_GEOJSON,
    } as Response);

    const { result, rerender } = renderHook(
      ({ on }: { on: boolean }) => useRefineries(on),
      { initialProps: { on: true } },
    );
    await waitFor(() => expect(result.current.refineries).not.toBeNull());

    rerender({ on: false });
    rerender({ on: true });
    expect(spy).toHaveBeenCalledTimes(1);
  });
});
