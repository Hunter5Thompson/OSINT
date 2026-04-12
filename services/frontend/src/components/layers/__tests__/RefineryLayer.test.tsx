import { describe, it, expect, vi, afterEach } from "vitest";
import { render } from "@testing-library/react";
import { RefineryLayer, createRefineryIcon } from "../RefineryLayer";
import type { RefineryGeoJSON } from "../../../types";

// Spies must be created with vi.hoisted so they are available inside the
// vi.mock factory (which is hoisted above all imports by Vitest).
const mocks = vi.hoisted(() => {
  const bbAddSpy = vi.fn().mockReturnValue({});
  const lcAddSpy = vi.fn().mockReturnValue({});
  class MockBillboardCollection {
    add = bbAddSpy;
    removeAll = vi.fn();
    show = true;
  }
  class MockLabelCollection {
    add = lcAddSpy;
    removeAll = vi.fn();
    show = true;
  }
  return { bbAddSpy, lcAddSpy, MockBillboardCollection, MockLabelCollection };
});

vi.mock("cesium", async (importOriginal) => {
  const actual = await importOriginal<typeof import("cesium")>();
  return {
    ...actual,
    BillboardCollection: mocks.MockBillboardCollection,
    LabelCollection: mocks.MockLabelCollection,
  };
});

import * as Cesium from "cesium";

afterEach(() => {
  vi.restoreAllMocks();
  vi.clearAllMocks();
});

function fakeViewer(): Cesium.Viewer {
  const primitives = {
    add: vi.fn((p: unknown) => p),
    remove: vi.fn(),
  };
  const canvas = document.createElement("canvas");
  return {
    scene: {
      primitives,
      requestRender: vi.fn(),
      camera: { positionCartographic: { height: 10_000_000 } },
      pick: vi.fn(() => undefined),
    },
    canvas,
    isDestroyed: () => false,
  } as unknown as Cesium.Viewer;
}

const MOCK_DATA: RefineryGeoJSON = {
  type: "FeatureCollection",
  features: [
    {
      type: "Feature",
      geometry: { type: "Point", coordinates: [72.0, 22.3] },
      properties: {
        name: "Jamnagar Refinery",
        operator: "Reliance Industries",
        capacity_bpd: 1240000,
        country: "IN",
        status: "active",
      },
    },
    {
      type: "Feature",
      geometry: { type: "Point", coordinates: [50.1, 26.6] },
      properties: {
        name: "Ras Tanura",
        operator: "Saudi Aramco",
        capacity_bpd: 550000,
        country: "SA",
        status: "active",
      },
    },
  ],
};

describe("createRefineryIcon", () => {
  it("returns a canvas of correct size", () => {
    const c = createRefineryIcon(32);
    expect(c.width).toBe(32);
    expect(c.height).toBe(32);
  });
});

describe("RefineryLayer", () => {
  it("adds billboard and label collections to scene", () => {
    const viewer = fakeViewer();
    render(
      <RefineryLayer
        viewer={viewer}
        refineries={MOCK_DATA}
        visible={true}
        onSelect={vi.fn()}
      />,
    );
    expect(viewer.scene.primitives.add).toHaveBeenCalledTimes(2);
  });

  it("creates one billboard per feature when visible", () => {
    const viewer = fakeViewer();
    render(
      <RefineryLayer
        viewer={viewer}
        refineries={MOCK_DATA}
        visible={true}
        onSelect={vi.fn()}
      />,
    );
    expect(mocks.bbAddSpy).toHaveBeenCalledTimes(2);
    expect(mocks.lcAddSpy).toHaveBeenCalledTimes(2);
  });

  it("skips rendering when visible=false", () => {
    const viewer = fakeViewer();
    render(
      <RefineryLayer
        viewer={viewer}
        refineries={MOCK_DATA}
        visible={false}
        onSelect={vi.fn()}
      />,
    );
    expect(mocks.bbAddSpy).not.toHaveBeenCalled();
  });

  it("renders null to DOM", () => {
    const viewer = fakeViewer();
    const { container } = render(
      <RefineryLayer
        viewer={viewer}
        refineries={MOCK_DATA}
        visible={true}
        onSelect={vi.fn()}
      />,
    );
    expect(container.innerHTML).toBe("");
  });
});
