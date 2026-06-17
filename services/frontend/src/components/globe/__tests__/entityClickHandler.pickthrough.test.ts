import { describe, it, expect } from "vitest";
import * as Cesium from "cesium";
import { isPhotorealSurfacePick } from "../isPhotorealSurfacePick";

// Mirrors EntityClickHandler's guard: abort ONLY on real UI/layer picks.
function abortsBeforeCountryHitTest(
  picked: unknown,
  tileset: Cesium.Cesium3DTileset | null,
): boolean {
  return Boolean(picked) && !isPhotorealSurfacePick(picked, tileset);
}

describe("EntityClickHandler pick-through guard", () => {
  const tileset = { _odinPhotoreal: true } as unknown as Cesium.Cesium3DTileset;

  it("does NOT abort on a photoreal-surface pick (almanac runs on 3D map)", () => {
    expect(abortsBeforeCountryHitTest({ primitive: tileset }, tileset)).toBe(false);
  });

  it("aborts on a real data-layer pick (preserves the 6 onSelect layers)", () => {
    expect(abortsBeforeCountryHitTest({ primitive: { id: "firms" } }, tileset)).toBe(true);
  });

  it("does NOT abort on empty space (existing void → country path)", () => {
    expect(abortsBeforeCountryHitTest(undefined, tileset)).toBe(false);
  });
});
