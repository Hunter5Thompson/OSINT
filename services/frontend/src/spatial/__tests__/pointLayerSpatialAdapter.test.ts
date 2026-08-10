import { describe, expect, it, vi } from "vitest";

import type {
  ContainmentSnapshot,
  SpatialContainmentPort,
} from "../contracts";
import { createStrictPointLayerAdapter } from "../pointLayerSpatialAdapter";

interface PointRecord {
  readonly id: string;
  readonly longitude: number;
  readonly latitude: number;
}

class MutableContainmentPort implements SpatialContainmentPort {
  private readonly listeners = new Set<() => void>();

  constructor(private snapshot: ContainmentSnapshot) {}

  getSnapshot = () => this.snapshot;

  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  setSnapshot(snapshot: ContainmentSnapshot): void {
    this.snapshot = snapshot;
    this.listeners.forEach((listener) => listener());
  }
}

const point = (
  id: string,
  longitude: number,
  latitude = 5,
): PointRecord => ({ id, longitude, latitude });

describe("strict imperative point-layer adapter", () => {
  it("filters before rendering and accounts for every strict exclusion without mutation", () => {
    const source = [
      point("inside", 1),
      point("outside", 2),
      point("uncertain", 3),
      point("invalid", Number.NaN),
    ];
    const before = source.map((record) => ({ ...record }));
    const containment = new MutableContainmentPort({
      phase: "ready",
      stateRevision: 7,
      contains(longitude) {
        if (longitude === 1) return "inside";
        if (longitude === 2) return "outside";
        if (longitude === 3) return "boundary-uncertain";
        throw new RangeError("invalid coordinate");
      },
    });
    const adapter = createStrictPointLayerAdapter({
      containment,
      coordinates: (record: PointRecord) => [record.longitude, record.latitude],
    });

    const result = adapter.apply(source);

    expect(result).toMatchObject({
      phase: "ready",
      stateRevision: 7,
      inputCount: 4,
      includedCount: 1,
      excludedOutsideCount: 1,
      excludedBoundaryUncertainCount: 1,
      excludedInvalidCoordinateCount: 1,
      withheldCount: 0,
    });
    expect(result.records).toEqual([source[0]]);
    expect(source).toEqual(before);
    expect(result.records[0]).toBe(source[0]);
    expect(Object.isFrozen(source[0])).toBe(false);
  });

  it.each(["building", "unavailable"] as const)(
    "hides all old results while containment is %s",
    (phase) => {
      const containment = new MutableContainmentPort({
        phase: "ready",
        stateRevision: 2,
        contains: () => "inside",
      });
      const adapter = createStrictPointLayerAdapter({
        containment,
        coordinates: (record: PointRecord) => [record.longitude, record.latitude],
      });
      expect(adapter.apply([point("old", 1)]).records).toHaveLength(1);

      containment.setSnapshot({ phase, stateRevision: 3 });
      expect(adapter.apply([point("old", 1)])).toMatchObject({
        phase,
        stateRevision: 3,
        records: [],
        inputCount: 1,
        includedCount: 0,
        withheldCount: 1,
      });
    },
  );

  it("forwards containment publication so an imperative renderer can redraw", () => {
    const containment = new MutableContainmentPort({
      phase: "building",
      stateRevision: 1,
    });
    const adapter = createStrictPointLayerAdapter({
      containment,
      coordinates: (record: PointRecord) => [record.longitude, record.latitude],
    });
    const redraw = vi.fn();
    const unsubscribe = adapter.subscribe(redraw);

    containment.setSnapshot({
      phase: "ready",
      stateRevision: 1,
      contains: () => "inside",
    });
    expect(redraw).toHaveBeenCalledTimes(1);
    unsubscribe();
    containment.setSnapshot({ phase: "unavailable", stateRevision: 2 });
    expect(redraw).toHaveBeenCalledTimes(1);
  });

  it("does not accept camera LOD as an input to containment", () => {
    const contains = vi.fn(() => "inside" as const);
    const containment = new MutableContainmentPort({
      phase: "ready",
      stateRevision: 11,
      contains,
    });
    const adapter = createStrictPointLayerAdapter({
      containment,
      coordinates: (record: PointRecord) => [record.longitude, record.latitude],
    });
    const records = [point("fixed", 4)];

    expect(adapter.apply(records).records).toEqual(records);
    // A camera/render LOD transition has no adapter input and cannot replace the
    // committed containment snapshot.
    expect(adapter.apply(records).records).toEqual(records);
    expect(contains).toHaveBeenNthCalledWith(1, 4, 5);
    expect(contains).toHaveBeenNthCalledWith(2, 4, 5);
  });
});
