import { cleanup, render } from "@testing-library/react";
import * as Cesium from "cesium";
import { afterEach, expect, it } from "vitest";
import type { Vessel } from "../../../types";
import { ShipLayer } from "../ShipLayer";

afterEach(cleanup);

it("reuses the same atlas image across viewport refreshes and distinguishes course icons", () => {
  const primitives = new Cesium.PrimitiveCollection();
  const moveEnd = new Cesium.Event();
  const viewer = { isDestroyed: () => false,
    scene: { primitives, frameState: { mode: Cesium.SceneMode.SCENE3D }, globe: { ellipsoid: Cesium.Ellipsoid.WGS84 } },
    camera: { positionCartographic: { height: 400_000 }, moveEnd,
      computeViewRectangle: () => undefined } } as unknown as Cesium.Viewer;
  const vessel: Vessel = { mmsi: 205000001, name: "UNKNOWN SHIP", latitude: 45,
    longitude: 15, speed_knots: null, course: null, ship_type: 70, destination: null };
  const { rerender } = render(<ShipLayer viewer={viewer} vessels={[vessel]} visible />);
  const collection = primitives.get(0) as Cesium.BillboardCollection;
  const unknownImage = collection.get(0).image;
  for (let i = 0; i < 10; i++) {
    moveEnd.raiseEvent();
    expect(collection.get(0).image).toBe(unknownImage);
  }
  rerender(<ShipLayer viewer={viewer} vessels={[{ ...vessel, course: 1 }]} visible />);
  const northImage = collection.get(0).image;
  expect(northImage).not.toBe(unknownImage);
  rerender(<ShipLayer viewer={viewer} vessels={[{ ...vessel, course: 2 }]} visible />);
  expect(collection.get(0).image).toBe(northImage);
  rerender(<ShipLayer viewer={viewer} vessels={[{ ...vessel, course: 90 }]} visible />);
  expect(collection.get(0).image).not.toBe(northImage);
});
