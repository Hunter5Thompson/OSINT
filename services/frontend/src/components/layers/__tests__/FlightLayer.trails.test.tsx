import { cleanup, render } from "@testing-library/react";
import * as Cesium from "cesium";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Aircraft } from "../../../types";
import { FlightLayer } from "../FlightLayer";

afterEach(() => { cleanup(); vi.useRealTimers(); });

function aircraft(lon: number, lat = 0): Aircraft {
  return { icao24: `${lon}:${lat}`, callsign: null, latitude: lat, longitude: lon,
    altitude_m: 10_000, velocity_ms: 0, heading: 0, vertical_rate: 0, on_ground: false,
    last_contact: null, is_military: false, aircraft_type: null };
}

describe("FlightLayer trail viewport", () => {
  it.each([
    [Cesium.Rectangle.fromDegrees(170, -10, -170, 10), [179, -179]],
    [Cesium.Rectangle.fromDegrees(-10, -10, 10, 10), [0]],
    [null, [179, -179, 0]],
  ])("uses degree bounds including a wrapped viewport", (rect, expected) => {
    vi.useFakeTimers();
    const primitives = new Cesium.PrimitiveCollection();
    const viewer = { isDestroyed: () => false,
      scene: { primitives, frameState: { mode: Cesium.SceneMode.SCENE3D }, globe: { ellipsoid: Cesium.Ellipsoid.WGS84 } },
      camera: { positionCartographic: { height: 500_000 }, moveEnd: new Cesium.Event(),
        computeViewRectangle: () => rect } } as unknown as Cesium.Viewer;
    render(<FlightLayer viewer={viewer} visible flights={[
      aircraft(179), aircraft(-179), aircraft(0), ...(rect ? [aircraft(179, 80)] : []),
    ]} />);
    vi.advanceTimersByTime(2000);
    const trails = primitives.get(1) as Cesium.PolylineCollection;
    expect(trails.length).toBe(expected.length);
    const longitudes = Array.from({ length: trails.length }, (_, i) =>
      Math.round(Cesium.Math.toDegrees(Cesium.Cartographic.fromCartesian(trails.get(i).positions[0]!).longitude)));
    expect(longitudes).toEqual(expected);
  });
});
