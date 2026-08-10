import { describe, expect, it, vi } from "vitest";

import type {
  BoundaryAsset,
  BoundaryAssetLease,
  BoundaryGeometryV1,
} from "../catalog";
import type { ContainmentAssetDescriptor } from "../contracts";
import {
  createSpatialContainmentController,
  type SpatialContainmentAssetPort,
} from "../containment";

interface Deferred<T> {
  readonly promise: Promise<T>;
  resolve(value: T): void;
}

function deferred<T>(): Deferred<T> {
  let resolvePromise: (value: T) => void = () => undefined;
  const promise = new Promise<T>((resolve) => {
    resolvePromise = resolve;
  });
  return { promise, resolve: resolvePromise };
}

const descriptor: ContainmentAssetDescriptor = {
  assetId: "a".repeat(64),
  mediaType: "application/vnd.odin.spatial-boundary+json;version=1",
  byteLength: 512,
  vertexCount: 5,
  role: "containment",
  maxErrorMeters: 25,
};

const square: BoundaryGeometryV1 = {
  schemaVersion: 1,
  geometryType: "MultiPolygon",
  polygons: [[[
    [0, 0],
    [10, 0],
    [10, 10],
    [0, 10],
    [0, 0],
  ]]],
};

function lease(asset: BoundaryAsset, release = vi.fn()): BoundaryAssetLease {
  return { asset, release };
}

describe("SpatialContainmentPort lifecycle", () => {
  it("invalidates the old index synchronously at semantic commit", async () => {
    const pending = deferred<BoundaryAssetLease>();
    const assets: SpatialContainmentAssetPort = {
      acquire: vi.fn(() => pending.promise),
    };
    const containment = createSpatialContainmentController({ assets });
    containment.commit({ scopeKind: "world", descriptor: null, stateRevision: 1 });
    expect(containment.getSnapshot()).toEqual({ phase: "building", stateRevision: 1 });
    await vi.waitFor(() => expect(containment.getSnapshot().phase).toBe("ready"));
    const world = containment.getSnapshot();
    expect(world.phase).toBe("ready");

    const listener = vi.fn();
    containment.subscribe(listener);
    containment.commit({ scopeKind: "country", descriptor, stateRevision: 2 });

    expect(containment.getSnapshot()).toEqual({ phase: "building", stateRevision: 2 });
    expect(containment.getSnapshot()).not.toBe(world);
    expect(listener).toHaveBeenCalledTimes(1);
    containment.dispose();
  });

  it("builds the fixed index and classifies inside, outside, and the error band", async () => {
    const release = vi.fn();
    const assets: SpatialContainmentAssetPort = {
      acquire: vi.fn().mockResolvedValue(lease(square, release)),
    };
    const containment = createSpatialContainmentController({ assets });

    containment.commit({ scopeKind: "country", descriptor, stateRevision: 4 });
    await vi.waitFor(() => expect(containment.getSnapshot().phase).toBe("ready"));

    const ready = containment.getSnapshot();
    expect(ready.phase).toBe("ready");
    if (ready.phase !== "ready") throw new Error("expected ready containment");
    expect(ready.contains(5, 5)).toBe("inside");
    expect(ready.contains(20, 20)).toBe("outside");
    expect(ready.contains(0, 5)).toBe("boundary-uncertain");
    expect(assets.acquire).toHaveBeenCalledWith(descriptor, expect.any(AbortSignal));

    containment.dispose();
    expect(release).toHaveBeenCalledTimes(1);
  });

  it("cannot publish a stale asset completion over a newer semantic generation", async () => {
    const pending = deferred<BoundaryAssetLease>();
    const release = vi.fn();
    const assets: SpatialContainmentAssetPort = {
      acquire: vi.fn(() => pending.promise),
    };
    const containment = createSpatialContainmentController({ assets });

    containment.commit({ scopeKind: "country", descriptor, stateRevision: 8 });
    containment.commit({ scopeKind: "world", descriptor: null, stateRevision: 9 });
    expect(containment.getSnapshot()).toEqual({ phase: "building", stateRevision: 9 });
    pending.resolve(lease(square, release));
    await vi.waitFor(() => expect(containment.getSnapshot().phase).toBe("ready"));

    const current = containment.getSnapshot();
    expect(current.phase).toBe("ready");
    expect(current.stateRevision).toBe(9);
    if (current.phase !== "ready") throw new Error("expected world containment");
    expect(current.contains(-179, -89)).toBe("inside");
    expect(release).toHaveBeenCalledTimes(1);
    containment.dispose();
  });

  it("is unavailable without a containment asset and never falls back to a bbox", () => {
    const assets: SpatialContainmentAssetPort = { acquire: vi.fn() };
    const containment = createSpatialContainmentController({ assets });

    containment.commit({ scopeKind: "admin1", descriptor: null, stateRevision: 3 });

    expect(containment.getSnapshot()).toEqual({ phase: "unavailable", stateRevision: 3 });
    expect(assets.acquire).not.toHaveBeenCalled();
    containment.dispose();
  });

  it("uses a synthetic world index for valid WGS84 points only", async () => {
    const assets: SpatialContainmentAssetPort = { acquire: vi.fn() };
    const containment = createSpatialContainmentController({ assets });
    containment.commit({ scopeKind: "world", descriptor: null, stateRevision: 1 });
    expect(containment.getSnapshot()).toEqual({ phase: "building", stateRevision: 1 });
    await vi.waitFor(() => expect(containment.getSnapshot().phase).toBe("ready"));

    const world = containment.getSnapshot();
    if (world.phase !== "ready") throw new Error("expected world containment");
    expect(world.contains(-180, -90)).toBe("inside");
    expect(world.contains(180, 90)).toBe("inside");
    expect(() => world.contains(181, 0)).toThrow(RangeError);
    expect(() => world.contains(0, Number.NaN)).toThrow(RangeError);
    expect(assets.acquire).not.toHaveBeenCalled();
    containment.dispose();
  });

  it("rejects a boundary pack as an unavailable containment geometry", async () => {
    const release = vi.fn();
    const assets: SpatialContainmentAssetPort = {
      acquire: vi.fn().mockResolvedValue(lease({
        schemaVersion: 1,
        parentScopeKey: "world" as never,
        features: [],
      }, release)),
    };
    const containment = createSpatialContainmentController({ assets });

    containment.commit({ scopeKind: "country", descriptor, stateRevision: 5 });
    await vi.waitFor(() => expect(containment.getSnapshot().phase).toBe("unavailable"));

    expect(containment.getSnapshot()).toEqual({ phase: "unavailable", stateRevision: 5 });
    expect(release).toHaveBeenCalledTimes(1);
    containment.dispose();
  });
});
