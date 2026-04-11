import { describe, it, expect, vi } from "vitest";
import { render } from "@testing-library/react";
import * as Cesium from "cesium";
import { FIRMSLayer, createFIRMSDot, frpToSize, frpToColor } from "../FIRMSLayer";
import type { FIRMSHotspot } from "../../../types";

function fakeViewer(): Cesium.Viewer {
  const fakeScene = { frameState: { mode: Cesium.SceneMode.SCENE3D } } as unknown as Cesium.Scene;
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const bc = new Cesium.BillboardCollection({ scene: fakeScene });
  const primitives = {
    add: vi.fn((p: unknown) => p),
    remove: vi.fn(),
  };
  const canvas = document.createElement("canvas");
  return {
    scene: {
      primitives,
      requestRender: vi.fn(),
      frameState: { mode: Cesium.SceneMode.SCENE3D },
      pick: vi.fn(() => undefined),
    },
    canvas,
    isDestroyed: () => false,
  } as unknown as Cesium.Viewer;
}

describe("FIRMS canvas helpers", () => {
  it("frpToSize clamps between 6 and 22", () => {
    expect(frpToSize(0)).toBe(6);
    expect(frpToSize(40)).toBeCloseTo(16);
    expect(frpToSize(500)).toBe(22);
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

  it("renders without throwing for three hotspots (one flagged)", () => {
    const viewer = fakeViewer();
    const onSelect = vi.fn();
    render(
      <FIRMSLayer
        viewer={viewer}
        hotspots={[
          baseHotspot({ id: "a" }),
          baseHotspot({ id: "b" }),
          baseHotspot({ id: "c", possible_explosion: true }),
        ]}
        visible={true}
        onSelect={onSelect}
      />,
    );
  });
});
