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
    {
      type: "Feature" as const,
      geometry: { type: "Point" as const, coordinates: [50.158, 26.643] },
      properties: {
        name: "Enriched Refinery",
        operator: "Saudi Aramco",
        capacity_bpd: 550000,
        country: "SA",
        status: "active" as const,
        facility_type: "refinery" as const,
        image_url: "https://commons.wikimedia.org/wiki/Special:FilePath/X.jpg",
        source_url: "https://www.wikidata.org/wiki/Q860840",
        qid: "Q860840",
        coord_quality: "wikidata_verified" as const,
        coord_source: "wikidata",
        specs: ["WGS84 position: 26°38'34\"N, 50°9'29\"E"],
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
    expect(result.current.refineries!.features).toHaveLength(2);
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

  it("exposes Wikidata-enriched provenance fields", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => MOCK_GEOJSON,
    } as Response);

    const { result } = renderHook(() => useRefineries(true));
    await waitFor(() =>
      expect(result.current.refineries?.features.length).toBeGreaterThanOrEqual(2),
    );

    const enriched = result.current.refineries!.features.find(
      (f) => f.properties.name === "Enriched Refinery",
    )!;
    expect(enriched.properties.qid).toBe("Q860840");
    expect(enriched.properties.coord_quality).toBe("wikidata_verified");
    expect(enriched.properties.coord_source).toBe("wikidata");
  });
});
