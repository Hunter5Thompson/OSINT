// services/frontend/src/components/globe/__tests__/isPhotorealSurfacePick.test.ts
import { describe, it, expect } from "vitest";
import type * as Cesium from "cesium";
import { isPhotorealSurfacePick } from "../isPhotorealSurfacePick";

// Plain objects stand in for picks/tilesets — no real Cesium viewer needed.
const photoreal = { _odinPhotoreal: true } as unknown as Cesium.Cesium3DTileset;

describe("isPhotorealSurfacePick", () => {
  it("returns false for empty-space picks (null/undefined)", () => {
    expect(isPhotorealSurfacePick(undefined, null)).toBe(false);
    expect(isPhotorealSurfacePick(null, null)).toBe(false);
  });

  it("returns true when the pick belongs to the photoreal tileset (by reference)", () => {
    expect(isPhotorealSurfacePick({ primitive: photoreal }, photoreal)).toBe(true);
    expect(isPhotorealSurfacePick({ tileset: photoreal }, photoreal)).toBe(true);
    expect(isPhotorealSurfacePick({ content: { tileset: photoreal } }, photoreal)).toBe(true);
  });

  it("returns true via the _odinPhotoreal marker even when the reference is null", () => {
    // A picked tile feature exposes its (marked) owning tileset via .tileset /
    // .content.tileset; a non-feature surface pick exposes it via .primitive.
    expect(isPhotorealSurfacePick({ tileset: { _odinPhotoreal: true } }, null)).toBe(true);
    expect(isPhotorealSurfacePick({ content: { tileset: { _odinPhotoreal: true } } }, null)).toBe(true);
    expect(isPhotorealSurfacePick({ primitive: { _odinPhotoreal: true } }, null)).toBe(true);
  });

  it("returns false for a real data-layer primitive (billboard/polyline)", () => {
    const layerPick = { primitive: { id: "flight-billboard" }, id: { name: "Flight 123" } };
    expect(isPhotorealSurfacePick(layerPick, photoreal)).toBe(false);
  });

  it("returns false for an UNmarked, UNreferenced 3D-tileset-like pick (contract guard)", () => {
    // Some other tileset that is neither the photoreal reference nor marked.
    const otherTileset = { isCesium3DTileset: true };
    expect(isPhotorealSurfacePick({ primitive: otherTileset }, photoreal)).toBe(false);
    expect(isPhotorealSurfacePick({ tileset: otherTileset }, photoreal)).toBe(false);
  });
});
