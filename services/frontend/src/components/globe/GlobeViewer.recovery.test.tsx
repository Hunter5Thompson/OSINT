import { act, fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { applyCRTShader } from "../shaders/shaderUtils";
import { GlobeViewer } from "./GlobeViewer";

const state = vi.hoisted(() => ({ viewers: [] as {
  canvas: HTMLCanvasElement; useDefaultRenderLoop: boolean; destroy: ReturnType<typeof vi.fn>;
}[] }));
vi.mock("cesium", () => ({
  Ion: {},
  Viewer: class {
    constructor(container: HTMLElement, options: { showRenderLoopErrors: boolean }) {
      expect(options.showRenderLoopErrors).toBe(false);
      let destroyed = false;
      const canvas = document.createElement("canvas"); container.append(canvas);
      const viewer = {
        canvas, useDefaultRenderLoop: true, clock: { shouldAnimate: true },
        scene: { globe: {}, fog: {}, renderError: { addEventListener: () => () => {} } },
        camera: { setView: vi.fn() }, isDestroyed: () => destroyed,
        destroy: vi.fn(() => { destroyed = true; canvas.remove(); }),
      };
      state.viewers.push(viewer); return viewer;
    }
  },
  Color: { fromCssColorString: () => ({}) }, Cartesian3: { fromDegrees: () => ({}) },
}));
vi.mock("./terrainCacheCleanup", () => ({ captureTerrainCacheRelease: () => () => {} }));
vi.mock("./baseLayer", () => ({ createBaseLayer: () => undefined }));
vi.mock("../shaders/shaderUtils", () => ({
  clearShaders: vi.fn(), applyCRTShader: vi.fn(), applyNightVisionShader: vi.fn(), applyFLIRShader: vi.fn(),
}));

it("rebuilds the owned viewer after failure and ignores the old canvas", () => {
  const ready = vi.fn();
  const view = render(<GlobeViewer onViewerReady={ready} cesiumToken="" activeShader="crt" showCountryBorders={false} showCityBuildings={false} />);
  const first = state.viewers[0]!;
  act(() => first.canvas.dispatchEvent(new Event("webglcontextlost", { cancelable: true })));
  expect(screen.getByRole("alert")).toHaveTextContent("map display was interrupted");
  expect(first.useDefaultRenderLoop).toBe(false);
  fireEvent.click(screen.getByRole("button", { name: "Reload map" }));
  expect(first.destroy).toHaveBeenCalledOnce();
  expect(first.canvas.isConnected).toBe(false);
  expect(state.viewers).toHaveLength(2);
  expect(ready).toHaveBeenCalledTimes(2);
  expect(applyCRTShader).toHaveBeenNthCalledWith(2, state.viewers[1]);
  expect(screen.queryByRole("alert")).toBeNull();
  act(() => first.canvas.dispatchEvent(new Event("webglcontextlost", { cancelable: true })));
  expect(screen.queryByRole("alert")).toBeNull();
  view.unmount();
  expect(state.viewers[1]!.destroy).toHaveBeenCalledOnce();
});
