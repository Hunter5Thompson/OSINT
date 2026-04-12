import { describe, it, expect, vi, afterEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { useDatacenters } from "../useDatacenters";

const MOCK_GEOJSON = {
  type: "FeatureCollection" as const,
  features: [
    {
      type: "Feature" as const,
      geometry: { type: "Point" as const, coordinates: [-77.49, 39.04] },
      properties: {
        name: "Test DC",
        operator: "TestCorp",
        tier: "hyperscaler" as const,
        capacity_mw: 100,
        country: "US",
        city: "Ashburn",
      },
    },
  ],
};

describe("useDatacenters", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("does not fetch when disabled", () => {
    const spy = vi.spyOn(globalThis, "fetch");
    renderHook(() => useDatacenters(false));
    expect(spy).not.toHaveBeenCalled();
  });

  it("fetches GeoJSON when enabled", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => MOCK_GEOJSON,
    } as Response);

    const { result } = renderHook(() => useDatacenters(true));
    await waitFor(() => expect(result.current.datacenters).not.toBeNull());
    expect(result.current.datacenters!.features).toHaveLength(1);
    expect(result.current.lastUpdate).toBeInstanceOf(Date);
  });

  it("does not re-fetch once loaded", async () => {
    const spy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => MOCK_GEOJSON,
    } as Response);

    const { result, rerender } = renderHook(
      ({ on }: { on: boolean }) => useDatacenters(on),
      { initialProps: { on: true } },
    );
    await waitFor(() => expect(result.current.datacenters).not.toBeNull());

    rerender({ on: false });
    rerender({ on: true });
    expect(spy).toHaveBeenCalledTimes(1);
  });
});
