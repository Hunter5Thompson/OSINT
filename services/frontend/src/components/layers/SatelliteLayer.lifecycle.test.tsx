import { render } from "@testing-library/react";
import * as Cesium from "cesium";
import { afterEach, describe, expect, it, vi } from "vitest";
import reference from "../../../../../tests/fixtures/satellites/reference-vectors.json";
import gp from "../../../../../tests/fixtures/satellites/celestrak-100651.json";
import type { Satellite } from "../../types";
import type { OrbitSatellite } from "../../types/satelliteOrbit";
import { SatelliteLayer } from "./SatelliteLayer";

const tle = reference.cases.find(row => row.orbit.format === "tle")!.orbit;
const iss: Satellite = {
  norad_id: 25544, name: "ISS (ZARYA)", category: "station",
  tle_line1: tle.line1!, tle_line2: tle.line2!, inclination_deg: 51.6439,
  period_min: 92.897, operator_country: "INT", satellite_type: "station",
};

function surface() {
  const primitives = new Cesium.PrimitiveCollection();
  const clock = new Cesium.Clock({
    currentTime: Cesium.JulianDate.fromIso8601("2019-12-09T16:38:29.362Z"),
    shouldAnimate: false,
  });
  const moveEnd = new Cesium.Event();
  const canvas = document.createElement("canvas");
  const pick = vi.fn(() => undefined);
  let destroyed = false;
  const viewer = {
    clock, isDestroyed: () => destroyed,
    get scene() {
      if (destroyed) throw new Error("scene accessed after destroy");
      return { primitives, canvas, pick, requestRender: () => {} };
    },
    camera: { positionCartographic: { height: 8_000_000 }, moveEnd },
    entities: new Cesium.EntityCollection(),
  } as unknown as Cesium.Viewer;
  return { viewer, primitives, clock, moveEnd, canvas, pick, destroy: () => { destroyed = true; } };
}

function point(primitives: Cesium.PrimitiveCollection): Cesium.Cartesian3 {
  const collection = primitives.get(0) as Cesium.BillboardCollection;
  return Cesium.Cartesian3.clone(collection.get(0).position);
}

describe("SatelliteLayer Cesium time", () => {
  afterEach(() => vi.restoreAllMocks());
  it("moves the visible LEO immediately on seek using the viewer clock", () => {
    const view = surface();
    render(<SatelliteLayer viewer={view.viewer} satellites={[iss]} visible />);
    const before = point(view.primitives);
    view.clock.currentTime = Cesium.JulianDate.addSeconds(view.clock.currentTime, 60, new Cesium.JulianDate());
    view.clock.onTick.raiseEvent(view.clock);
    expect(Cesium.Cartesian3.distance(before, point(view.primitives))).toBeGreaterThan(1000);
  });

  it("throttles continuous reverse playback to one update per second", () => {
    const view = surface();
    let wall = 0;
    vi.spyOn(performance, "now").mockImplementation(() => wall);
    view.clock.shouldAnimate = true;
    view.clock.multiplier = -1;
    render(<SatelliteLayer viewer={view.viewer} satellites={[iss]} visible />);
    const time = Cesium.JulianDate.clone(view.clock.currentTime);
    const before = point(view.primitives);
    wall = 100;
    view.clock.currentTime = Cesium.JulianDate.addSeconds(time, -0.1, new Cesium.JulianDate());
    view.clock.onTick.raiseEvent(view.clock);
    expect(point(view.primitives)).toEqual(before);
    wall = 1000;
    view.clock.currentTime = Cesium.JulianDate.addSeconds(time, -1, new Cesium.JulianDate());
    view.clock.onTick.raiseEvent(view.clock);
    expect(Cesium.Cartesian3.distance(before, point(view.primitives))).toBeGreaterThan(100);
  });

  it("removes hover work when hidden", () => {
    const view = surface();
    const component = render(<SatelliteLayer viewer={view.viewer} satellites={[iss]} visible />);
    view.canvas.dispatchEvent(new PointerEvent("pointermove", { pointerType: "mouse", clientX: 5, clientY: 5 }));
    expect(view.pick).toHaveBeenCalled();
    view.pick.mockClear();
    component.rerender(<SatelliteLayer viewer={view.viewer} satellites={[iss]} visible={false} />);
    view.canvas.dispatchEvent(new PointerEvent("pointermove", { pointerType: "mouse", clientX: 10, clientY: 10 }));
    expect(view.pick).not.toHaveBeenCalled();
    expect(view.clock.onTick.numberOfListeners).toBe(0);
  });

  it("applies an explicit subsecond seek immediately during playback", () => {
    const view = surface();
    vi.spyOn(performance, "now").mockReturnValue(0);
    view.clock.shouldAnimate = true;
    const props = { viewer: view.viewer, satellites: [iss], visible: true, discontinuityEpoch: 0 };
    const component = render(<SatelliteLayer {...props} />);
    const before = point(view.primitives);
    view.clock.currentTime = Cesium.JulianDate.addSeconds(view.clock.currentTime, 0.5, new Cesium.JulianDate());
    component.rerender(<SatelliteLayer {...props} discontinuityEpoch={1} />);
    expect(Cesium.Cartesian3.distance(before, point(view.primitives))).toBeGreaterThan(100);
  });

  it("holds on pause and restores point and orbit on rewind", () => {
    const view = surface();
    let wall = 0;
    vi.spyOn(performance, "now").mockImplementation(() => wall);
    render(<SatelliteLayer viewer={view.viewer} satellites={[iss]} visible />);
    const start = Cesium.JulianDate.clone(view.clock.currentTime);
    const before = point(view.primitives);
    wall = 10_000;
    view.clock.onTick.raiseEvent(view.clock);
    expect(point(view.primitives)).toEqual(before);
    view.clock.currentTime = Cesium.JulianDate.addSeconds(start, 60, new Cesium.JulianDate());
    view.clock.onTick.raiseEvent(view.clock);
    const arcs = view.primitives.get(1) as Cesium.PolylineCollection;
    expect(Cesium.Cartesian3.distance(arcs.get(0).positions[0]!, point(view.primitives))).toBeLessThan(0.01);
    view.clock.currentTime = start;
    view.clock.onTick.raiseEvent(view.clock);
    expect(Cesium.Cartesian3.distance(before, point(view.primitives))).toBeLessThan(0.01);
  });

  it("keeps one layer tick listener and releases it after viewer destruction", () => {
    const view = surface();
    const component = render(<SatelliteLayer viewer={view.viewer} satellites={[iss, iss]} visible />);
    expect(view.clock.onTick.numberOfListeners).toBe(1);
    view.destroy();
    expect(() => view.clock.onTick.raiseEvent(view.clock)).not.toThrow();
    expect(() => view.moveEnd.raiseEvent()).not.toThrow();
    expect(() => component.unmount()).not.toThrow();
    expect(view.clock.onTick.numberOfListeners).toBe(0);
    expect(view.moveEnd.numberOfListeners).toBe(0);
    expect(() => view.clock.onTick.raiseEvent(view.clock)).not.toThrow();
  });

  it("bounds orbit work and honors camera LOD", () => {
    const view = surface();
    render(<SatelliteLayer viewer={view.viewer} satellites={Array.from({ length: 100 }, () => iss)} visible />);
    const arcs = view.primitives.get(1) as Cesium.PolylineCollection;
    expect(arcs.length).toBeLessThanOrEqual(64);
    expect(arcs.length).toBeGreaterThan(0);
    view.viewer.camera.positionCartographic.height = 60_000_000;
    view.moveEnd.raiseEvent();
    expect(arcs.show).toBe(false);
    view.viewer.camera.positionCartographic.height = 8_000_000;
    view.moveEnd.raiseEvent();
    expect(arcs.show).toBe(true);
  });

  it("renders a six-digit GP point and a bounded orbit without inventing a category", () => {
    const view = surface();
    view.clock.currentTime = Cesium.JulianDate.fromIso8601("2026-10-09T05:27:38.151Z");
    const row: OrbitSatellite = {
      norad_id: 100651, name: gp.OBJECT_NAME, category: "active", operator_country: null,
      satellite_type: "unknown", inclination_deg: gp.INCLINATION, period_min: 1440 / gp.MEAN_MOTION,
      orbit: { format: "omm", elements: { ...gp, EPOCH: gp.EPOCH + "Z",
        EPHEMERIS_TYPE: 0, CLASSIFICATION_TYPE: "U", CENTER_NAME: "EARTH", REF_FRAME: "TEME",
        TIME_SYSTEM: "UTC", MEAN_ELEMENT_THEORY: "SGP4" } },
    };
    render(<SatelliteLayer viewer={view.viewer} satellites={[row]} visible />);
    const billboards = view.primitives.get(0) as Cesium.BillboardCollection;
    expect(billboards.get(0).show).toBe(true);
    expect(point(view.primitives).x).toBeTypeOf("number");
    expect((view.primitives.get(1) as Cesium.PolylineCollection).length).toBe(1);
  });
});
