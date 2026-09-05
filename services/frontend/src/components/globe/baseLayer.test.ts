import { beforeEach, describe, expect, it, vi } from "vitest";
import * as Cesium from "cesium";
import { createBaseLayer } from "./baseLayer";

vi.mock("cesium", () => ({
  buildModuleUrl: vi.fn((path: string) => "/cesium/" + path),
  TileMapServiceImageryProvider: { fromUrl: vi.fn().mockResolvedValue({}) },
  ImageryLayer: {
    fromProviderAsync: vi.fn().mockReturnValue({ reference: true }),
  },
}));
beforeEach(() => vi.clearAllMocks());
describe("globe reference imagery", () => {
  it("uses bundled imagery without requesting a remote provider when no token exists", () => {
    expect(createBaseLayer("")).toEqual({ reference: true });
    expect(Cesium.TileMapServiceImageryProvider.fromUrl).toHaveBeenCalledWith(
      "/cesium/Assets/Textures/NaturalEarthII",
    );
  });
  it("preserves the configured Cesium imagery path when a token exists", () => {
    expect(createBaseLayer("configured")).toBeUndefined();
    expect(Cesium.TileMapServiceImageryProvider.fromUrl).not.toHaveBeenCalled();
  });
});
