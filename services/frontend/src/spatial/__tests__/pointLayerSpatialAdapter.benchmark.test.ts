import { describe, expect, it, vi } from "vitest";

import type { BoundaryGeometryV1 } from "../catalog";
import type { ContainmentAssetDescriptor } from "../contracts";
import { createSpatialContainmentController } from "../containment";
import { createStrictPointLayerAdapter } from "../pointLayerSpatialAdapter";

interface BenchmarkPoint {
  readonly longitude: number;
  readonly latitude: number;
}

const geometry: BoundaryGeometryV1 = {
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

const descriptor: ContainmentAssetDescriptor = {
  assetId: "b".repeat(64),
  mediaType: "application/vnd.odin.spatial-boundary+json;version=1",
  byteLength: 512,
  vertexCount: 5,
  role: "containment",
  maxErrorMeters: 25,
};

describe("strict point-layer high-cardinality budget", () => {
  it("accounts for 30k points while keeping the downstream render set bounded", async () => {
    const containment = createSpatialContainmentController({
      assets: {
        acquire: vi.fn().mockResolvedValue({
          asset: geometry,
          release: vi.fn(),
        }),
      },
    });
    containment.commit({ scopeKind: "country", descriptor, stateRevision: 1 });
    await vi.waitFor(() => expect(containment.getSnapshot().phase).toBe("ready"));
    const adapter = createStrictPointLayerAdapter<BenchmarkPoint>({
      containment,
      coordinates: (point) => [point.longitude, point.latitude],
    });
    const records = Array.from({ length: 30_000 }, (_, index) => {
      if (index % 3 === 0) return { longitude: 5, latitude: 5 };
      if (index % 3 === 1) return { longitude: 20, latitude: 20 };
      return { longitude: 0, latitude: 5 };
    });

    adapter.apply(records.slice(0, 300));
    const started = performance.now();
    const result = adapter.apply(records);
    const durationMs = performance.now() - started;
    const downstreamRenderCount = Math.min(result.includedCount, 250);
    const retainedResults: Array<ReturnType<typeof adapter.apply>> = [];
    const retainedHeapBefore = process.memoryUsage().heapUsed;
    for (let index = 0; index < 16; index += 1) {
      retainedResults.push(adapter.apply(records));
    }
    const retainedHeapDeltaBytes = Math.max(
      0,
      process.memoryUsage().heapUsed - retainedHeapBefore,
    );
    const retainedHeapBytesPerPass = Math.ceil(retainedHeapDeltaBytes / 16);

    process.stdout.write(`SPATIAL_POINT_BENCHMARK ${JSON.stringify({
      inputCount: result.inputCount,
      includedCount: result.includedCount,
      excludedOutsideCount: result.excludedOutsideCount,
      excludedBoundaryUncertainCount: result.excludedBoundaryUncertainCount,
      downstreamRenderCount,
      durationMs: Number(durationMs.toFixed(3)),
      retainedHeapDeltaBytes,
      retainedHeapBytesPerPass,
    })}\n`);

    expect(result).toMatchObject({
      inputCount: 30_000,
      includedCount: 10_000,
      excludedOutsideCount: 10_000,
      excludedBoundaryUncertainCount: 10_000,
      excludedInvalidCoordinateCount: 0,
    });
    expect(downstreamRenderCount).toBe(250);
    expect(retainedResults).toHaveLength(16);
    expect(durationMs).toBeLessThan(750);
    expect(retainedHeapDeltaBytes).toBeLessThan(64 * 1024 * 1024);
    expect(retainedHeapBytesPerPass).toBeLessThan(4 * 1024 * 1024);
    containment.dispose();
  });
});
