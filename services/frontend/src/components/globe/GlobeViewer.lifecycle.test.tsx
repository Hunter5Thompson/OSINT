import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { GlobeViewer } from "./GlobeViewer";

const { viewer, destroy } = vi.hoisted(() => {
  const destroy = vi.fn(() => { throw new Error("partially destroyed primitive"); });
  return {
    destroy,
    viewer: {
      useDefaultRenderLoop: true,
      clock: { shouldAnimate: true },
      scene: { globe: {}, fog: {} },
      camera: { setView: vi.fn() },
      isDestroyed: () => false,
      destroy,
    },
  };
});
vi.mock("cesium", () => ({
  Ion: {}, Viewer: class { constructor() {
    const style = document.createElement("style");
    style.textContent = ".cesium-credit-lightbox-overlay { display: none; }";
    document.head.append(style);
    return viewer;
  } },
  Color: { fromCssColorString: () => ({}) },
  Cartesian3: { fromDegrees: () => ({}) },
}));
vi.mock("./terrainCacheCleanup", () => ({ captureTerrainCacheRelease: () => () => {} }));
vi.mock("./baseLayer", () => ({ createBaseLayer: () => undefined }));
vi.mock("../shaders/shaderUtils", () => ({
  clearShaders: vi.fn(), applyCRTShader: vi.fn(), applyNightVisionShader: vi.fn(), applyFLIRShader: vi.fn(),
}));

describe("GlobeViewer teardown", () => {
  it("stops rendering before disposal, even if a primitive throws during destroy", () => {
    destroy.mockImplementationOnce(() => {
      expect(viewer.useDefaultRenderLoop).toBe(false);
      expect(viewer.clock.shouldAnimate).toBe(false);
      throw new Error("partially destroyed primitive");
    });
    const foreign = document.createElement("style");
    foreign.textContent = ".cesium-credit-lightbox-overlay { color: red; }";
    document.head.append(foreign);
    const before = new Set(document.head.querySelectorAll("style"));
    const view = render(<GlobeViewer onViewerReady={vi.fn()} cesiumToken="" activeShader="none" showCountryBorders={false} showCityBuildings={false} />);
    view.unmount();
    expect(new Set(document.head.querySelectorAll("style"))).toEqual(before);
    expect(foreign.isConnected).toBe(true);
    foreign.remove();
    expect(destroy).toHaveBeenCalledOnce();
    expect(viewer.useDefaultRenderLoop).toBe(false);
    expect(viewer.clock.shouldAnimate).toBe(false);
  });
});
