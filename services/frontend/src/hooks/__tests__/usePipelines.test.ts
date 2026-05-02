import { describe, it, expect, vi, afterEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { usePipelines } from "../usePipelines";

const MOCK_GEOJSON = {
  type: "FeatureCollection" as const,
  features: [
    {
      type: "Feature" as const,
      geometry: {
        type: "LineString" as const,
        coordinates: [[28.7, 60.5], [13.5, 54.1]],
      },
      properties: {
        name: "Nord Stream 1",
        tier: "major" as const,
        type: "gas" as const,
        status: "active" as const,
        operator: "Nord Stream AG",
        capacity_bcm: 55.0,
        length_km: 1224,
        countries: ["Russia", "Germany"],
        source_url: "https://en.wikipedia.org/wiki/Nord_Stream",
      },
    },
  ],
};

describe("usePipelines", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("does not fetch when disabled", () => {
    const spy = vi.spyOn(globalThis, "fetch");
    renderHook(() => usePipelines(false));
    expect(spy).not.toHaveBeenCalled();
  });

  it("fetches GeoJSON when enabled and exposes source_url", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => MOCK_GEOJSON,
    } as Response);

    const { result } = renderHook(() => usePipelines(true));
    await waitFor(() =>
      expect(result.current.pipelines?.features.length).toBe(1),
    );
    const props = result.current.pipelines!.features[0]!.properties;
    expect(props.name).toBe("Nord Stream 1");
    expect(props.source_url).toBe("https://en.wikipedia.org/wiki/Nord_Stream");
    expect(props.qid).toBeUndefined();
  });
});
