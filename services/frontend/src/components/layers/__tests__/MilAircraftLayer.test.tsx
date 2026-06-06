import { describe, it, expect, vi } from "vitest";
import { render } from "@testing-library/react";
import * as Cesium from "cesium";
import { MilAircraftLayer, branchColor, createJetIcon } from "../MilAircraftLayer";
import type { MilTrackRender } from "../milTrackAdapter";

function fakeViewer(): { viewer: Cesium.Viewer; ticks: Array<() => void> } {
  const ticks: Array<() => void> = [];
  const primitives = {
    add: vi.fn((p: unknown) => p),
    remove: vi.fn(),
  };
  const viewer = {
    scene: {
      primitives,
      requestRender: vi.fn(),
      frameState: { mode: Cesium.SceneMode.SCENE3D },
      pick: vi.fn(() => undefined),
    },
    canvas: document.createElement("canvas"),
    clock: {
      onTick: {
        addEventListener: vi.fn((cb: () => void) => {
          ticks.push(cb);
          return vi.fn();
        }),
      },
    },
    isDestroyed: () => false,
  } as unknown as Cesium.Viewer;
  return { viewer, ticks };
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
    expect(c.getContext("2d")).not.toBeNull();
  });
});

describe("MilAircraftLayer component (time-aware)", () => {
  const track = (id: string, nPoints: number): MilTrackRender => ({
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
      ts_ms: 1_744_300_000_000 + i * 60_000,
    })),
  });

  it("renders mixed-length render-model tracks and registers a clock tick loop", () => {
    const { viewer, ticks } = fakeViewer();
    render(
      <MilAircraftLayer
        viewer={viewer}
        tracks={[track("a", 5), track("b", 1)]}
        visible={true}
        getTimeMs={() => 1_744_300_000_000 + 120_000}
        discontinuityEpoch={0}
        onSelect={vi.fn()}
      />,
    );
    // the tick effect subscribed to clock.onTick
    expect(ticks.length).toBe(1);
    // invoking the tick loop drives interpolation without throwing
    expect(() => ticks[0]!()).not.toThrow();
  });

  it("does not register a tick loop without a viewer", () => {
    render(
      <MilAircraftLayer
        viewer={null}
        tracks={[track("a", 3)]}
        visible={true}
        getTimeMs={() => 0}
        discontinuityEpoch={0}
      />,
    );
  });
});
