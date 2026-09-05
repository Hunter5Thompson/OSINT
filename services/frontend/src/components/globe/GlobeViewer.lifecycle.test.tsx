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
  Ion: {}, Viewer: class { constructor() { return viewer; } },
  Color: { fromCssColorString: () => ({}) },
  Cartesian3: { fromDegrees: () => ({}) },
}));
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
    const view = render(<GlobeViewer onViewerReady={vi.fn()} cesiumToken="" activeShader="none" showCountryBorders={false} showCityBuildings={false} />);
    view.unmount();
    expect(destroy).toHaveBeenCalledOnce();
    expect(viewer.useDefaultRenderLoop).toBe(false);
    expect(viewer.clock.shouldAnimate).toBe(false);
  });
});
