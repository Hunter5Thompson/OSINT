import { describe, it, expect, vi, afterEach } from "vitest";
import { render } from "@testing-library/react";
import * as Cesium from "cesium";
import { EarthquakeLayer } from "../EarthquakeLayer";
import type { Earthquake } from "../../../types";
import type { StrictPointLayerAdapter } from "../../../spatial/pointLayerSpatialAdapter";

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

const quake = (over: Partial<Earthquake>): Earthquake => ({
  id: over.id ?? "q",
  latitude: 45,
  longitude: 37,
  depth_km: 10,
  magnitude: 5.2,
  place: "x",
  time: "2026-06-06T12:00:00Z",
  tsunami: false,
  url: "https://example/",
  ...over,
});

const manyQuakes = (n: number, lon: number, lat: number): Earthquake[] =>
  Array.from({ length: n }, (_, i) => quake({ id: `q${i}`, longitude: lon, latitude: lat, magnitude: 3 + (i % 50) / 10 }));

describe("EarthquakeLayer", () => {
  it("applies strict containment to the full feed before viewport culling", () => {
    const labelAdd = vi.spyOn(Cesium.LabelCollection.prototype, "add");
    const viewer = fakeViewer();
    const source = [
      quake({ id: "outside", longitude: -120, latitude: 35 }),
      quake({ id: "inside", longitude: 37, latitude: 45 }),
    ];
    const apply = vi.fn(() => ({
      phase: "ready" as const,
      stateRevision: 2,
      records: [source[1]!],
      inputCount: 2,
      includedCount: 1,
      excludedOutsideCount: 1,
      excludedBoundaryUncertainCount: 0,
      excludedInvalidCoordinateCount: 0,
      withheldCount: 0,
    }));
    const spatialAdapter: StrictPointLayerAdapter<Earthquake> = {
      apply,
      subscribe: () => () => undefined,
    };

    render(
      <EarthquakeLayer
        viewer={viewer}
        earthquakes={source}
        visible={true}
        spatialAdapter={spatialAdapter}
      />,
    );

    expect(apply).toHaveBeenCalledWith(source);
    expect(labelAdd).toHaveBeenCalledTimes(1);
    expect(source.map((item) => item.id)).toEqual(["outside", "inside"]);
  });

  it("redraws imperatively when containment becomes ready", () => {
    const labelAdd = vi.spyOn(Cesium.LabelCollection.prototype, "add");
    const viewer = fakeViewer();
    const source = [quake({ id: "inside" })];
    let listener: () => void = () => undefined;
    let ready = false;
    const spatialAdapter: StrictPointLayerAdapter<Earthquake> = {
      apply: () => ready
        ? {
            phase: "ready",
            stateRevision: 2,
            records: source,
            inputCount: 1,
            includedCount: 1,
            excludedOutsideCount: 0,
            excludedBoundaryUncertainCount: 0,
            excludedInvalidCoordinateCount: 0,
            withheldCount: 0,
          }
        : {
            phase: "building",
            stateRevision: 2,
            records: [],
            inputCount: 1,
            includedCount: 0,
            excludedOutsideCount: 0,
            excludedBoundaryUncertainCount: 0,
            excludedInvalidCoordinateCount: 0,
            withheldCount: 1,
          },
      subscribe: (next) => {
        listener = next;
        return () => {
          listener = () => undefined;
        };
      },
    };

    render(
      <EarthquakeLayer
        viewer={viewer}
        earthquakes={source}
        visible={true}
        spatialAdapter={spatialAdapter}
      />,
    );
    expect(labelAdd).not.toHaveBeenCalled();

    ready = true;
    listener();
    expect(labelAdd).toHaveBeenCalledTimes(1);
  });

  it("caps rendered quakes at 250 (one label each)", () => {
    const labelAdd = vi.spyOn(Cesium.LabelCollection.prototype, "add");
    const viewer = fakeViewer();
    render(<EarthquakeLayer viewer={viewer} earthquakes={manyQuakes(600, 37, 45)} visible={true} />);
    expect(labelAdd.mock.calls.length).toBe(250);
  });

  it("attaches distance attenuation to the quake billboards", () => {
    const billboardAdd = vi.spyOn(Cesium.BillboardCollection.prototype, "add");
    const viewer = fakeViewer();
    render(<EarthquakeLayer viewer={viewer} earthquakes={[quake({ id: "a" })]} visible={true} />);
    const opts = billboardAdd.mock.calls[0]![0] as Record<string, unknown>;
    expect(opts.scaleByDistance).toBeInstanceOf(Cesium.NearFarScalar);
    expect(opts.translucencyByDistance).toBeInstanceOf(Cesium.NearFarScalar);
  });

  it("culls quakes outside the viewport", () => {
    const labelAdd = vi.spyOn(Cesium.LabelCollection.prototype, "add");
    const viewer = fakeViewer(Cesium.Rectangle.fromDegrees(30, 40, 45, 50));
    render(
      <EarthquakeLayer
        viewer={viewer}
        earthquakes={[
          quake({ id: "in", longitude: 37, latitude: 45 }),
          quake({ id: "out", longitude: -120, latitude: 35 }),
        ]}
        visible={true}
      />,
    );
    expect(labelAdd.mock.calls.length).toBe(1);
  });

  it("re-renders on camera move", () => {
    const viewer = fakeViewer();
    render(<EarthquakeLayer viewer={viewer} earthquakes={[quake({ id: "a" })]} visible={true} />);
    const before = viewer._computeViewRectangle.mock.calls.length;
    viewer._fireMoveEnd();
    expect(viewer._computeViewRectangle.mock.calls.length).toBeGreaterThan(before);
  });

  it("ring billboard has translucency but no scaleByDistance (pulse owns scale)", () => {
    const billboardAdd = vi.spyOn(Cesium.BillboardCollection.prototype, "add");
    const viewer = fakeViewer();
    render(<EarthquakeLayer viewer={viewer} earthquakes={[quake({ id: "a" })]} visible={true} />);
    // calls[0] = dot, calls[1] = ring (added in that order per quake)
    const ringOpts = billboardAdd.mock.calls[1]![0] as Record<string, unknown>;
    expect(ringOpts.translucencyByDistance).toBeInstanceOf(Cesium.NearFarScalar);
    expect(ringOpts.scaleByDistance).toBeUndefined();
  });

  it("emits nothing when not visible, even after a camera move", () => {
    const labelAdd = vi.spyOn(Cesium.LabelCollection.prototype, "add");
    const viewer = fakeViewer();
    render(<EarthquakeLayer viewer={viewer} earthquakes={[quake({ id: "a" })]} visible={false} />);
    labelAdd.mockClear();
    viewer._fireMoveEnd();
    expect(labelAdd.mock.calls.length).toBe(0);
  });
});
