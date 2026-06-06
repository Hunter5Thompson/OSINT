import { describe, it, expect, vi, afterEach } from "vitest";
import { render } from "@testing-library/react";
import * as Cesium from "cesium";
import { FIRMSLayer, createFIRMSDot, frpToSize, frpToColor } from "../FIRMSLayer";
import type { FIRMSHotspot } from "../../../types";

afterEach(() => vi.restoreAllMocks());

function fakeViewer(
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
      pick: vi.fn(() => undefined),
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

describe("FIRMS canvas helpers", () => {
  it("frpToSize clamps between 4 and 14", () => {
    expect(frpToSize(0)).toBe(4);
    expect(frpToSize(35)).toBeCloseTo(11);
    expect(frpToSize(500)).toBe(14);
  });

  it("frpToColor interpolates yellow → orange → red", () => {
    const cold = frpToColor(0);
    const hot = frpToColor(100);
    expect(cold.red).toBeGreaterThan(0.9);
    expect(cold.green).toBeGreaterThan(0.8);
    expect(hot.red).toBeGreaterThan(0.9);
    expect(hot.green).toBeLessThan(0.3);
  });

  it("createFIRMSDot returns a canvas of non-zero size", () => {
    const c = createFIRMSDot(10, Cesium.Color.RED);
    expect(c.width).toBeGreaterThan(0);
    expect(c.height).toBeGreaterThan(0);
  });
});

describe("FIRMSLayer component", () => {
  const baseHotspot = (over: Partial<FIRMSHotspot>): FIRMSHotspot => ({
    id: over.id ?? "h",
    latitude: 48, longitude: 37,
    frp: 20, brightness: 370, confidence: "n",
    acq_date: "2026-04-11", acq_time: "1200",
    satellite: "VIIRS_SNPP_NRT", bbox_name: "ukraine",
    possible_explosion: false,
    firms_map_url: "https://example/",
    ...over,
  });

  const manyHotspots = (n: number, lon: number, lat: number): FIRMSHotspot[] =>
    Array.from({ length: n }, (_, i) => baseHotspot({ id: `h${i}`, longitude: lon, latitude: lat, frp: i }));

  it("caps rendered hotspots at 400 and attaches distance attenuation", () => {
    const addSpy = vi.spyOn(Cesium.BillboardCollection.prototype, "add");
    const viewer = fakeViewer();
    render(<FIRMSLayer viewer={viewer} hotspots={manyHotspots(600, 37, 48)} visible={true} />);
    expect(addSpy.mock.calls.length).toBe(400);
    const opts = addSpy.mock.calls[0]![0] as Record<string, unknown>;
    expect(opts.scaleByDistance).toBeInstanceOf(Cesium.NearFarScalar);
    expect(opts.translucencyByDistance).toBeInstanceOf(Cesium.NearFarScalar);
  });

  it("culls hotspots outside the viewport", () => {
    const addSpy = vi.spyOn(Cesium.BillboardCollection.prototype, "add");
    const viewer = fakeViewer(Cesium.Rectangle.fromDegrees(30, 40, 45, 50));
    render(
      <FIRMSLayer
        viewer={viewer}
        hotspots={[
          baseHotspot({ id: "in", longitude: 37, latitude: 45 }),
          baseHotspot({ id: "out", longitude: -120, latitude: 35 }),
        ]}
        visible={true}
      />,
    );
    expect(addSpy.mock.calls.length).toBe(1);
  });

  it("re-renders on camera move (re-queries the viewport)", () => {
    const viewer = fakeViewer();
    render(<FIRMSLayer viewer={viewer} hotspots={[baseHotspot({ id: "a" })]} visible={true} />);
    const before = viewer._computeViewRectangle.mock.calls.length;
    viewer._fireMoveEnd();
    expect(viewer._computeViewRectangle.mock.calls.length).toBeGreaterThan(before);
  });
});
