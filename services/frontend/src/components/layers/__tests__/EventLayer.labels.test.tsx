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
    },
    camera: {
      positionCartographic: { height: 1_000 }, // low altitude → labels would otherwise show
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
