import { describe, it, expect } from "vitest";
import * as Cesium from "cesium";
import { BORDER_PRIMITIVE_OPTIONS, BORDER_WIDTH, ringToPositions } from "../CountryBorders";

describe("CountryBorders styling", () => {
  it("uses a thicker line so borders read over photoreal terrain", () => {
    expect(BORDER_WIDTH).toBeGreaterThanOrEqual(1.5);
  });

  it("converts a [lon,lat] ring to Cartesian3 positions", () => {
    const positions = ringToPositions([[0, 0], [10, 10], [20, 20]]);
    expect(positions).toHaveLength(3);
    expect(positions[0]).toBeInstanceOf(Cesium.Cartesian3);
  });

  it("renders borders non-pickable + draped over terrain AND 3D tiles", () => {
    expect(BORDER_PRIMITIVE_OPTIONS.allowPicking).toBe(false);
    expect(BORDER_PRIMITIVE_OPTIONS.classificationType).toBe(Cesium.ClassificationType.BOTH);
  });
});
