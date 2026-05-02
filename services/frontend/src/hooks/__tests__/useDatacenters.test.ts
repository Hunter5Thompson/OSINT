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
    {
      type: "Feature" as const,
      geometry: { type: "Point" as const, coordinates: [8.55, 50.10] },
      properties: {
        name: "Enriched DC",
        operator: "TestCorp",
        tier: "hyperscaler" as const,
        capacity_mw: 200,
        country: "DE",
        city: "Frankfurt",
        qid: "Q1234567",
        source_url: "https://example.com/frankfurt-dc",
        coord_quality: "campus_verified" as const,
        coord_source: "https://example.com/frankfurt-dc",
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
    expect(result.current.datacenters!.features).toHaveLength(2);
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

  it("preserves optional provenance fields when present", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => MOCK_GEOJSON,
    } as Response);

    const { result } = renderHook(() => useDatacenters(true));
    await waitFor(() =>
      expect(result.current.datacenters?.features.length).toBe(2),
    );

    const bare = result.current.datacenters!.features[0]!.properties;
    const enriched = result.current.datacenters!.features[1]!.properties;

    expect(bare.qid).toBeUndefined();
    expect(bare.source_url).toBeUndefined();
    expect(enriched.qid).toBe("Q1234567");
    expect(enriched.coord_quality).toBe("campus_verified");
    expect(enriched.source_url).toBe("https://example.com/frankfurt-dc");
  });
});
