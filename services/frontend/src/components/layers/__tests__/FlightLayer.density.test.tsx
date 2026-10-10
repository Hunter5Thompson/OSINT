import { cleanup, render } from "@testing-library/react";
import * as Cesium from "cesium";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Aircraft } from "../../../types";
import { FlightLayer } from "../FlightLayer";

const performanceState = vi.hoisted(() => ({ fps: 60, degradation: 0 }));
vi.mock("../../globe/PerformanceGuard", async importOriginal => ({
  ...await importOriginal<typeof import("../../globe/PerformanceGuard")>(),
  usePerformance: () => performanceState,
}));

beforeEach(() => { vi.useFakeTimers(); performanceState.degradation = 0; });
afterEach(() => { cleanup(); vi.useRealTimers(); });

function aircraft(i: number, patch: Partial<Aircraft> = {}): Aircraft {
  return { icao24: `contact-${i}`, callsign: null, latitude: 10, longitude: 5,
    altitude_m: 10_000, velocity_ms: 200, heading: 90, vertical_rate: 0,
    on_ground: false, last_contact: null, is_military: false, aircraft_type: null, ...patch };
}

function viewer(height = 10_000_000, rectangle: Cesium.Rectangle | undefined = undefined) {
  const primitives = new Cesium.PrimitiveCollection();
  const moveEnd = new Cesium.Event();
  const state = { destroyed: false, rectangle };
  const instance = { isDestroyed: () => state.destroyed,
    scene: { primitives, frameState: { mode: Cesium.SceneMode.SCENE3D },
      globe: { ellipsoid: Cesium.Ellipsoid.WGS84 } },
    camera: { positionCartographic: { height }, moveEnd,
      computeViewRectangle: () => state.rectangle } } as unknown as Cesium.Viewer;
  return { instance, primitives, moveEnd, state,
    billboards: () => primitives.get(0) as Cesium.BillboardCollection };
}

function ids(collection: Cesium.BillboardCollection): string[] {
  return Array.from({ length: collection.length }, (_, i) =>
    (collection.get(i) as unknown as { _flightData: { icao24: string } })._flightData.icao24);
}

describe("FlightLayer density and viewer ownership", () => {
  it.each([[10_000_000, 250], [2_000_000, 600], [500_000, 1500]])(
    "caps actual billboards at height %i", (height, expected) => {
      const v = viewer(height);
      render(<FlightLayer viewer={v.instance} flights={Array.from({ length: 10_000 }, (_, i) => aircraft(i))} visible />);
      expect(v.billboards().length).toBe(expected);
    },
  );

  it("keeps a selected and military contact before ordinary contacts at the cap", () => {
    const v = viewer();
    const flights = Array.from({ length: 1500 }, (_, i) => aircraft(i, { is_military: i === 1499 }));
    render(<FlightLayer viewer={v.instance} flights={flights} visible pinnedId="contact-1498" />);
    expect(ids(v.billboards()).slice(0, 2)).toEqual(["contact-1498", "contact-1499"]);
    expect(v.billboards().length).toBe(250);
  });

  it("culls invalid and duplicate contacts, reports every withheld record and preserves pick data", () => {
    const v = viewer(10_000_000, Cesium.Rectangle.fromDegrees(170, -20, -170, 20));
    const onDensity = vi.fn();
    const flights = [aircraft(0, { longitude: 179 }), aircraft(1, { longitude: -179 }),
      aircraft(2, { longitude: 0 }), aircraft(3, { latitude: 91 }),
      aircraft(4, { longitude: NaN }), aircraft(0, { longitude: 178 })];
    render(<FlightLayer viewer={v.instance} flights={flights} visible onDensity={onDensity} />);
    expect(v.billboards().length).toBe(2);
    expect(ids(v.billboards())).toEqual(["contact-0", "contact-1"]);
    expect(onDensity).toHaveBeenLastCalledWith({ total: 6, valid: 3, invalid: 2,
      duplicates: 1, inView: 2, shown: 2, omitted: 0, band: "GLOBE", cap: 250 });
    expect((v.billboards().get(0) as unknown as { _flightData: unknown })._flightData)
      .toMatchObject({ icao24: "contact-0", lat: 10, lon: 179 });
  });

  it("refreshes a camera viewport only at moveEnd and unregisters its listener", () => {
    const v = viewer(500_000, Cesium.Rectangle.fromDegrees(-10, -20, 10, 20));
    const flights = [aircraft(0), aircraft(1, { longitude: 179 })];
    const { unmount } = render(<FlightLayer viewer={v.instance} flights={flights} visible />);
    expect(ids(v.billboards())).toEqual(["contact-0"]);
    v.state.rectangle = Cesium.Rectangle.fromDegrees(170, -20, -170, 20);
    expect(ids(v.billboards())).toEqual(["contact-0"]);
    v.moveEnd.raiseEvent();
    expect(ids(v.billboards())).toEqual(["contact-1"]);
    expect(v.moveEnd.numberOfListeners).toBe(1);
    unmount();
    expect(v.moveEnd.numberOfListeners).toBe(0);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("repopulates and rebinds animation when the viewer changes but flights do not", () => {
    const first = viewer(), second = viewer();
    const flights = [aircraft(0)];
    const { rerender } = render(<FlightLayer viewer={first.instance} flights={flights} visible />);
    rerender(<FlightLayer viewer={second.instance} flights={flights} visible />);
    expect(first.primitives.length).toBe(0);
    expect(second.billboards().length).toBe(1);
    expect(first.moveEnd.numberOfListeners).toBe(0);
    expect(second.moveEnd.numberOfListeners).toBe(1);
    vi.advanceTimersByTime(2000);
    expect((second.primitives.get(1) as Cesium.PolylineCollection).length).toBe(1);
  });

  it("attenuates symbols with distance using the existing shared Cesium contract", () => {
    const v = viewer();
    render(<FlightLayer viewer={v.instance} flights={[aircraft(0)]} visible />);
    expect(v.billboards().get(0).scaleByDistance).toEqual(new Cesium.NearFarScalar(100_000, 1, 12_000_000, .45));
    expect(v.billboards().get(0).translucencyByDistance).toEqual(new Cesium.NearFarScalar(100_000, 1, 14_000_000, .35));
  });

  it("keeps dots static at degradation level four", () => {
    performanceState.degradation = 4;
    const v = viewer();
    render(<FlightLayer viewer={v.instance} flights={[aircraft(0)]} visible />);
    const position = Cesium.Cartesian3.clone(v.billboards().get(0).position);
    vi.advanceTimersByTime(2000);
    expect(v.billboards().get(0).position).toEqual(position);
    expect((v.primitives.get(1) as Cesium.PolylineCollection).length).toBe(0);
  });

  it("never mutates a destroyed viewer from a timer or retained camera callback", () => {
    const v = viewer();
    render(<FlightLayer viewer={v.instance} flights={[aircraft(0)]} visible />);
    const position = Cesium.Cartesian3.clone(v.billboards().get(0).position);
    v.state.destroyed = true;
    vi.advanceTimersByTime(2000);
    v.moveEnd.raiseEvent();
    expect(v.billboards().get(0).position).toEqual(position);
    expect((v.primitives.get(1) as Cesium.PolylineCollection).length).toBe(0);
  });
});
