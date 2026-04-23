import { describe, expect, it } from "vitest";
import * as Cesium from "cesium";
import { densifyLonLatSegment } from "../geoPath";

function geodesicKm(a: [number, number], b: [number, number]): number {
  const g = new Cesium.EllipsoidGeodesic(
    Cesium.Cartographic.fromDegrees(a[0], a[1]),
    Cesium.Cartographic.fromDegrees(b[0], b[1]),
  );
  return g.surfaceDistance / 1000;
}

describe("densifyLonLatSegment", () => {
  it("returns a denser path for long arcs", () => {
    const out = densifyLonLatSegment(
      [
        [0, 0],
        [10, 0],
      ],
      200,
    );

    expect(out.length).toBeGreaterThan(2);
    expect(out[0]).toEqual([0, 0]);
    expect(out[out.length - 1]?.[0]).toBeCloseTo(10, 6);
    expect(out[out.length - 1]?.[1]).toBeCloseTo(0, 6);
  });

  it("keeps each interpolated step below the configured max distance", () => {
    const maxStepKm = 120;
    const out = densifyLonLatSegment(
      [
        [-110, 52],
        [-94.5, 29.5],
      ],
      maxStepKm,
    );

    for (let i = 1; i < out.length; i += 1) {
      const d = geodesicKm(out[i - 1]! as [number, number], out[i]! as [number, number]);
      expect(d).toBeLessThanOrEqual(maxStepKm + 1.0);
    }
  });

  it("ignores invalid coordinates gracefully", () => {
    const out = densifyLonLatSegment([
      [0, 0],
      [Number.NaN, 5],
      [2, 1],
    ]);

    expect(out.length).toBeGreaterThanOrEqual(1);
    for (const [lon, lat] of out) {
      expect(Number.isFinite(lon)).toBe(true);
      expect(Number.isFinite(lat)).toBe(true);
    }
  });
});
