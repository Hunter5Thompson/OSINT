import { describe, it, expect, vi, afterEach } from "vitest";
import { render } from "@testing-library/react";
import * as Cesium from "cesium";
import { GDACSLayer } from "../GDACSLayer";
import type { LabelArbiterApi } from "../../../hooks/useLabelArbiter";
import type { GDACSEvent } from "../../../types";
import { fakeViewer } from "./fakeViewer";

afterEach(() => vi.restoreAllMocks());

const gdacs = (over: Partial<GDACSEvent>): GDACSEvent => ({
  id: over.id ?? "g",
  event_type: "EQ",
  event_name: "Quake",
  alert_level: "Orange",
  severity: 2.5,
  country: "X",
  latitude: 45,
  longitude: 37,
  from_date: "2026-04-08T00:00:00Z",
  to_date: "2026-04-12T00:00:00Z",
  ...over,
});

describe("GDACSLayer", () => {
  it("submits label requests with world positions, never screen coordinates", () => {
    vi.spyOn(Cesium.LabelCollection.prototype, "add");
    const submit = vi.fn<LabelArbiterApi["submit"]>();
    const arbiter: LabelArbiterApi = {
      submit,
      remove: vi.fn<LabelArbiterApi["remove"]>(),
      isSelected: () => true,
      version: 0,
    };
    const viewer = fakeViewer();
    render(
      <GDACSLayer
        viewer={viewer}
        events={[gdacs({ id: "g1" })]}
        visible={true}
        labelArbiter={arbiter}
      />,
    );
    expect(submit).toHaveBeenCalledWith("gdacs", expect.any(Array));
    const requests = submit.mock.calls[0]![1];
    expect(requests.length).toBeGreaterThan(0);
    const request = requests[0]!;
    expect(request).toEqual(
      expect.objectContaining({
        key: "gdacs:g1",
        text: "Quake",
        fontSizePx: 11,
        pixelOffsetY: -22,
        priority: 2.5,
      }),
    );
    expect(request.position).toBeInstanceOf(Cesium.Cartesian3);
    expect(request).not.toHaveProperty("rect");
  });

  it("removes its requests when it goes invisible", () => {
    vi.spyOn(Cesium.LabelCollection.prototype, "add");
    const remove = vi.fn<LabelArbiterApi["remove"]>();
    const arbiter: LabelArbiterApi = {
      submit: vi.fn<LabelArbiterApi["submit"]>(),
      remove,
      isSelected: () => true,
      version: 0,
    };
    const viewer = fakeViewer();
    const events = [gdacs({ id: "g1" })];
    const { rerender } = render(
      <GDACSLayer viewer={viewer} events={events} visible={true} labelArbiter={arbiter} />,
    );
    rerender(
      <GDACSLayer viewer={viewer} events={events} visible={false} labelArbiter={arbiter} />,
    );
    expect(remove).toHaveBeenCalledWith("gdacs");
  });

  it("KEEPS existing label behaviour when no arbiter is supplied", () => {
    const labelAdd = vi.spyOn(Cesium.LabelCollection.prototype, "add");
    const viewer = fakeViewer();
    render(<GDACSLayer viewer={viewer} events={[gdacs({ id: "a" })]} visible={true} />);
    expect(labelAdd).toHaveBeenCalled();
  });

  it("submits a camera-independent set — the hook owns viewport truth", () => {
    vi.spyOn(Cesium.LabelCollection.prototype, "add");
    const submit = vi.fn<LabelArbiterApi["submit"]>();
    const insideBox = gdacs({
      id: "inside",
      event_name: "Inside",
      latitude: 0.5,
      longitude: 0.5,
    });
    const farAway = gdacs({
      id: "far",
      event_name: "Far",
      latitude: 40,
      longitude: 100,
    });
    render(
      <GDACSLayer
        viewer={fakeViewer(Cesium.Rectangle.fromDegrees(0, 0, 1, 1))}
        events={[insideBox, farAway]}
        visible={true}
        labelArbiter={{
          submit,
          remove: vi.fn<LabelArbiterApi["remove"]>(),
          isSelected: () => true,
          version: 0,
        }}
      />,
    );
    expect(submit).toHaveBeenCalled();
    const requests = submit.mock.calls.at(-1)![1];
    expect(requests.map((r) => r.key).sort()).toEqual(
      [`gdacs:${farAway.id}`, `gdacs:${insideBox.id}`].sort(),
    );
  });
});
