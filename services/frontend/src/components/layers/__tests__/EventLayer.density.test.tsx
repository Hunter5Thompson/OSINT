import { cleanup, render } from "@testing-library/react";
import * as Cesium from "cesium";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { IntelEvent } from "../../../types";
import { EventLayer } from "../EventLayer";

beforeEach(() => vi.useFakeTimers());
afterEach(() => { cleanup(); vi.useRealTimers(); });

function event(i: number, patch: Partial<IntelEvent> = {}): IntelEvent {
  return { id: `synthetic-${i}`, title: `Synthetic event ${i}`, codebook_type: "military.exercise",
    severity: "low", timestamp: "2026-10-10T00:00:00Z", location_name: null,
    country: null, lat: 10, lon: 5, ...patch };
}
function viewer(height = 10_000_000) {
  const primitives = new Cesium.PrimitiveCollection();
  const moveEnd = new Cesium.Event();
  const instance = { isDestroyed: () => false,
    scene: { primitives, frameState: { mode: Cesium.SceneMode.SCENE3D }, globe: { ellipsoid: Cesium.Ellipsoid.WGS84 } },
    camera: { positionCartographic: { height }, moveEnd, computeViewRectangle: () => undefined } } as unknown as Cesium.Viewer;
  return { instance, primitives, moveEnd,
    billboards: () => primitives.get(0) as Cesium.BillboardCollection,
    labels: () => primitives.get(1) as Cesium.LabelCollection };
}
function data(b: Cesium.Billboard) { return b as unknown as Record<string, unknown>; }

describe("EventLayer honest aggregation and density", () => {
  it("aggregates globe events with exact member count while retaining the pinned original", () => {
    const v = viewer(), onDensity = vi.fn();
    render(<EventLayer viewer={v.instance} events={Array.from({ length: 1500 }, (_, i) => event(i))}
      visible pinnedId="synthetic-1499" onDensity={onDensity} />);
    expect(v.billboards().length).toBe(2);
    const picks = [data(v.billboards().get(0)), data(v.billboards().get(1))];
    expect(picks.find(p => p._eventData)?._eventData).toMatchObject({ id: "synthetic-1499", lat: 10, lon: 5 });
    const cluster = picks.find(p => p._eventClusterData)!;
    expect(cluster._eventData).toBeUndefined();
    expect(cluster._eventClusterData).toMatchObject({ count: 1499, lat: 10, lon: 5 });
    expect(onDensity).toHaveBeenLastCalledWith(expect.objectContaining({
      total: 1500, inView: 1500, represented: 1500, symbols: 2, aggregates: 1, omitted: 0,
    }));
  });
  it.each([[2_000_000, 600], [500_000, 1500]])("caps individual events at height %i", (height, cap) => {
    const v = viewer(height), onDensity = vi.fn();
    render(<EventLayer viewer={v.instance} events={Array.from({ length: 2000 }, (_, i) => event(i))}
      visible onDensity={onDensity} />);
    expect(v.billboards().length).toBe(cap);
    expect(onDensity).toHaveBeenLastCalledWith(expect.objectContaining({ represented: cap, omitted: 2000 - cap }));
  });
  it("uses the highest severity for a stack label without changing original pick coordinates", () => {
    const v = viewer(500_000);
    render(<EventLayer viewer={v.instance} events={[event(0), event(1, { severity: "critical", title: "Priority event" })]} visible />);
    expect(v.labels().get(0).text).toBe("Priority event (+1)");
    expect(data(v.billboards().get(0))._eventData).toMatchObject({ id: "synthetic-1", lat: 10, lon: 5 });
  });
  it("groups across the dateline, excludes out-of-window and invalid rows before counting", () => {
    const v = viewer(), onDensity = vi.fn();
    const events = [event(0, { lon: 179 }), event(1, { lon: -179 }), event(2, { lat: NaN }),
      event(3, { timestamp: "2020-01-01T00:00:00Z" }), event(0, { lon: 178 })];
    render(<EventLayer viewer={v.instance} events={events} visible getTimeMs={() => Date.parse("2026-10-10T00:00:00Z")}
      window={{ startMs: Date.parse("2026-10-09T00:00:00Z"), endMs: Date.parse("2026-10-11T00:00:00Z") }} onDensity={onDensity} />);
    expect(v.billboards().length).toBe(1);
    expect(data(v.billboards().get(0))._eventClusterData).toMatchObject({ count: 2, lat: 10 });
    const point = Cesium.Cartographic.fromCartesian(v.billboards().get(0).position);
    expect(Math.abs(Cesium.Math.toDegrees(point.longitude))).toBeCloseTo(180);
    expect(onDensity).toHaveBeenLastCalledWith(expect.objectContaining({ total: 5, invalid: 1,
      duplicates: 1, outsideWindow: 1, inView: 2, represented: 2 }));
    expect(v.labels().length).toBe(0);
  });
  it("rebuilds aggregates at detail height and repopulates a replacement viewer with unchanged inputs", () => {
    const v = viewer(), next = viewer(500_000), events = [event(0), event(1)];
    const { rerender, unmount } = render(<EventLayer viewer={v.instance} events={events} visible />);
    expect(v.billboards().length).toBe(1);
    v.instance.camera.positionCartographic.height = 500_000;
    v.moveEnd.raiseEvent();
    expect(v.billboards().length).toBe(2);
    rerender(<EventLayer viewer={next.instance} events={events} visible />);
    expect(next.billboards().length).toBe(2);
    expect(v.primitives.length).toBe(0);
    expect(v.moveEnd.numberOfListeners).toBe(0);
    unmount();
    expect(next.moveEnd.numberOfListeners).toBe(0);
    expect(vi.getTimerCount()).toBe(0);
  });
});
