import { describe, it, expect } from "vitest";
import type * as Cesium from "cesium";
import { applyTilesetPerformanceConfig, PHOTOREAL_TUNING } from "./tilesetConfig";

describe("applyTilesetPerformanceConfig", () => {
  it("sets maximumScreenSpaceError and cacheBytes from PHOTOREAL_TUNING", () => {
    // Minimal stub — type-only Cesium import means no WebGL/runtime is loaded.
    const tileset = {
      maximumScreenSpaceError: 0,
      cacheBytes: 0,
    } as unknown as Cesium.Cesium3DTileset;

    applyTilesetPerformanceConfig(tileset);

    expect(tileset.maximumScreenSpaceError).toBe(8);
    expect(tileset.maximumScreenSpaceError).toBe(PHOTOREAL_TUNING.maximumScreenSpaceError);
    expect(tileset.cacheBytes).toBe(1024 * 1024 * 1024);
    expect(tileset.cacheBytes).toBe(PHOTOREAL_TUNING.cacheBytes);
  });
});
