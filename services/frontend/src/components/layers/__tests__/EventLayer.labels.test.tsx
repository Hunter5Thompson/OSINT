import { afterEach, describe, it, expect, vi } from "vitest";
import { render } from "@testing-library/react";
import * as Cesium from "cesium";
import { EventLayer } from "../EventLayer";
import type { IntelEvent } from "../../../types";

afterEach(() => vi.restoreAllMocks());

function fakeViewer(): Cesium.Viewer {
  const primitives = { add: vi.fn((p: unknown) => p), remove: vi.fn() };
  return {
    scene: {
      primitives,
      requestRender: vi.fn(),
      frameState: { mode: Cesium.SceneMode.SCENE3D },
      pick: vi.fn(() => undefined),
      globe: { ellipsoid: Cesium.Ellipsoid.WGS84 },
    },
    camera: {
      positionCartographic: { height: 1_000 }, // low altitude → labels would otherwise show
      computeViewRectangle: () => undefined,
      moveEnd: { addEventListener: vi.fn(() => vi.fn()) },
    },
    isDestroyed: () => false,
  } as unknown as Cesium.Viewer;
}

const EVENTS: IntelEvent[] = [
  {
    id: "e1", title: "Airstrike near Kyiv", codebook_type: "military.airstrike",
    severity: "high", timestamp: "2026-06-01T00:00:00Z",
    location_name: "Kyiv", country: "UA", lat: 50.4, lon: 30.5,
  },
];

describe("EventLayer labels (#2)", () => {
  it("applies only a pixel offset to polar billboards and retains original pick coordinates", () => {
    const billboards = vi.spyOn(Cesium.BillboardCollection.prototype, "add");
    const labels = vi.spyOn(Cesium.LabelCollection.prototype, "add");
    const events = [0, 1].map(i => ({ ...EVENTS[0]!, id: `polar-${i}`, lat: 89, lon: 179.9 }));
    render(<EventLayer viewer={fakeViewer()} events={events} visible />);
    const options = billboards.mock.calls[0]![0]!;
    const point = Cesium.Cartographic.fromCartesian(options.position!);
    expect(Cesium.Math.toDegrees(point.latitude)).toBeCloseTo(89);
    expect(options.pixelOffset).toEqual(new Cesium.Cartesian2(18, 0));
    expect(labels.mock.calls[0]![0]!.pixelOffset).toEqual(new Cesium.Cartesian2(18, -18));
    expect((billboards.mock.results[0]!.value as unknown as Record<string, unknown>)._eventData).toMatchObject({ lat: 89, lon: 179.9 });
  });
  it("creates labels in legacy (non-time-aware) mode", () => {
    const addSpy = vi.spyOn(Cesium.LabelCollection.prototype, "add").mockReturnValue(
      {} as never,
    );
    render(<EventLayer viewer={fakeViewer()} events={EVENTS} visible={true} />);
    expect(addSpy).toHaveBeenCalled();
  });

  it("suppresses labels in time-aware mode (no globe text-wall)", () => {
    const addSpy = vi.spyOn(Cesium.LabelCollection.prototype, "add").mockReturnValue(
      {} as never,
    );
    render(
      <EventLayer
        viewer={fakeViewer()}
        events={EVENTS}
        visible={true}
        getTimeMs={() => Date.parse("2026-06-01T00:00:00Z")}
        window={{ startMs: 0, endMs: 1 }}
      />,
    );
    expect(addSpy).not.toHaveBeenCalled();
  });
});
