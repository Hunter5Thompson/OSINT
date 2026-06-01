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

describe("shouldShowOrbits", () => {
  it("keeps orbits visible across LEO..GEO globe-scale zoom", async () => {
    const { shouldShowOrbits } = await import("./SatelliteLayer");
    // GEO altitude (~35,786 km) used to be hidden by the 12,000 km LOD gate.
    expect(shouldShowOrbits(0, 35_786_000)).toBe(true);
    expect(shouldShowOrbits(0, 8_000_000)).toBe(true);
    // Beyond the raised LOD ceiling, orbits hide.
    expect(shouldShowOrbits(0, 60_000_000)).toBe(false);
  });

  it("is decoupled from the FPS-degradation ratchet (only level 4 suppresses)", async () => {
    const { shouldShowOrbits } = await import("./SatelliteLayer");
    // Previously degradation>=3 (driven by the ~12K point cloud) killed the cheap orbits.
    expect(shouldShowOrbits(3, 8_000_000)).toBe(true);
    expect(shouldShowOrbits(4, 8_000_000)).toBe(false);
  });
});
