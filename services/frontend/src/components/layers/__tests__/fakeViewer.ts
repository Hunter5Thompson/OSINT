import * as Cesium from "cesium";
import { vi } from "vitest";

export function fakeViewer(
  rect: Cesium.Rectangle = Cesium.Rectangle.fromDegrees(-180, -85, 180, 85),
): Cesium.Viewer & { _fireMoveEnd: () => void; _computeViewRectangle: ReturnType<typeof vi.fn> } {
  const primitives = { add: vi.fn((p: unknown) => p), remove: vi.fn() };
  const moveEndListeners: Array<() => void> = [];
  const computeViewRectangle = vi.fn(() => rect);
  return {
    scene: {
      primitives,
      requestRender: vi.fn(),
      frameState: { mode: Cesium.SceneMode.SCENE3D },
      globe: { ellipsoid: Cesium.Ellipsoid.WGS84 },
    },
    camera: {
      positionCartographic: { height: 3_000_000 },
      computeViewRectangle,
      moveEnd: {
        addEventListener: vi.fn((cb: () => void) => { moveEndListeners.push(cb); }),
        removeEventListener: vi.fn(),
      },
    },
    canvas: document.createElement("canvas"),
    isDestroyed: () => false,
    _fireMoveEnd: () => moveEndListeners.forEach((cb) => cb()),
    _computeViewRectangle: computeViewRectangle,
  } as unknown as Cesium.Viewer & { _fireMoveEnd: () => void; _computeViewRectangle: ReturnType<typeof vi.fn> };
}
