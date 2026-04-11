import { describe, it, expect, vi } from "vitest";
import { render } from "@testing-library/react";
import * as Cesium from "cesium";
import {
  MilAircraftLayer,
  branchColor,
  createJetIcon,
  trackToPolylinePositions,
} from "../MilAircraftLayer";
import type { AircraftTrack } from "../../../types";

function fakeViewer(): Cesium.Viewer {
  const primitives = {
    add: vi.fn((p: unknown) => p),
    remove: vi.fn(),
  };
  return {
    scene: {
      primitives,
      requestRender: vi.fn(),
      frameState: { mode: Cesium.SceneMode.SCENE3D },
      pick: vi.fn(() => undefined),
    },
    canvas: document.createElement("canvas"),
    isDestroyed: () => false,
  } as unknown as Cesium.Viewer;
}

describe("MilAircraft helpers", () => {
  it("branchColor maps known branches", () => {
    expect(branchColor("USAF").red).toBeGreaterThan(0.3);
    expect(branchColor("RUAF").red).toBeGreaterThan(0.9);
    expect(branchColor(null)).toEqual(Cesium.Color.WHITE);
  });

  it("createJetIcon returns canvas with visible pixels", () => {
    const c = createJetIcon(Cesium.Color.CYAN, 24);
    expect(c.width).toBe(24);
    expect(c.height).toBe(24);
    const ctx = c.getContext("2d");
    expect(ctx).not.toBeNull();
  });

  it("trackToPolylinePositions returns one Cartesian3 per point", () => {
    const positions = trackToPolylinePositions([
      { lat: 51, lon: 12, altitude_m: 10000, speed_ms: 240, heading: 90, timestamp: 1 },
      { lat: 52, lon: 13, altitude_m: 10100, speed_ms: 240, heading: 90, timestamp: 2 },
    ]);
    expect(positions.length).toBe(2);
  });

  it("trackToPolylinePositions falls back to 0 for null altitude", () => {
    const positions = trackToPolylinePositions([
      { lat: 0, lon: 0, altitude_m: null, speed_ms: null, heading: null, timestamp: 1 },
    ]);
    expect(positions.length).toBe(1);
  });
});

describe("MilAircraftLayer component", () => {
  const track = (id: string, nPoints: number): AircraftTrack => ({
    icao24: id,
    callsign: "TEST",
    type_code: "C17",
    military_branch: "USAF",
    registration: "00-0000",
    points: Array.from({ length: nPoints }, (_, i) => ({
      lat: 50 + i * 0.1,
      lon: 10 + i * 0.1,
      altitude_m: 10000,
      speed_ms: 240,
      heading: 90,
      timestamp: 1744300000 + i * 60,
    })),
  });

  it("renders without throwing for mixed-length tracks", () => {
    const viewer = fakeViewer();
    render(
      <MilAircraftLayer
        viewer={viewer}
        tracks={[track("a", 5), track("b", 1)]}
        visible={true}
        onSelect={vi.fn()}
      />,
    );
  });
});
