import { describe, it, expect } from "vitest";

describe("SatelliteLayer satData guard", () => {
  it("returns early when satData.lat is NaN", async () => {
    const module = await import("./SatelliteLayer");
    const { shouldRenderCone } = module as unknown as {
      shouldRenderCone: (sat: { lat: number; lon: number; footprint_radius_km?: number }) => boolean;
    };
    expect(shouldRenderCone({ lat: NaN, lon: 10, footprint_radius_km: 100 })).toBe(false);
    expect(shouldRenderCone({ lat: 50, lon: NaN, footprint_radius_km: 100 })).toBe(false);
    expect(shouldRenderCone({ lat: 50, lon: 10, footprint_radius_km: 100 })).toBe(true);
    expect(shouldRenderCone({ lat: 50, lon: 10, footprint_radius_km: 0 })).toBe(false);
  });
});
