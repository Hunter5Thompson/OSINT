import * as Cesium from "cesium";
import { describe, expect, it, vi } from "vitest";

import type {
  BoundaryAsset,
  BoundaryAssetLease,
  BoundaryGeometryV1,
  BoundaryPackV1,
} from "../catalog";
import type {
  AssetDescriptor,
  GeometryLod,
  RenderAssetDescriptor,
  ResolvedPresentationInput,
} from "../contracts";
import { parseCatalogRevision, parseScopeKeyCandidate } from "../contracts";
import {
  CesiumSpatialScopeAdapter,
  ViewerSpatialCesiumRuntime,
  type BoundaryAssetProvider,
  type ScopePrimitiveBuilder,
  type SpatialCesiumRuntime,
  type SpatialPrimitiveContainer,
} from "../cesium/CesiumSpatialScopeAdapter";
import {
  buildScopePrimitives,
  buildScopeGeometry,
  CesiumScopePrimitiveHandle,
  type ScopePrimitiveHandle,
} from "../cesium/buildScopePrimitives";

function geometry(
  polygons: BoundaryGeometryV1["polygons"],
): BoundaryGeometryV1 {
  return { schemaVersion: 1, geometryType: "MultiPolygon", polygons };
}

const overviewGeometry = geometry([
  [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]],
]);
const regionalGeometry = geometry([
  [[[0, 0], [9, 0], [9, 9], [0, 9], [0, 0]]],
]);
const localGeometry = geometry([
  [[[0, 0], [8, 0], [8, 8], [0, 8], [0, 0]]],
]);
const activeGeometry = overviewGeometry;
const world = parseScopeKeyCandidate("world");
const child = parseScopeKeyCandidate("country:UKR");

function childPackFor(
  label: string,
  childGeometry: BoundaryGeometryV1,
): BoundaryPackV1 {
  return {
    schemaVersion: 1,
    parentScopeKey: world,
    features: [
      { kind: "scope", scopeKey: child, label, geometry: childGeometry },
    ],
  };
}

const overviewChildPack = childPackFor("Ukraine overview", overviewGeometry);
const regionalChildPack = childPackFor("Ukraine regional", regionalGeometry);
const localChildPack = childPackFor("Ukraine local", localGeometry);
const childPack = overviewChildPack;

function descriptor(lod: GeometryLod, seed: string): RenderAssetDescriptor {
  return {
    role: "render",
    lod,
    assetId: seed.repeat(64),
    mediaType: "application/vnd.odin.boundary+json;v=1",
    byteLength: 100,
    vertexCount: 5,
  };
}

const overview = descriptor("overview", "a");
const regional = descriptor("regional", "b");
const local = descriptor("local", "c");
const overviewChildren = {
  ...descriptor("overview", "d"),
  mediaType: "application/vnd.odin.boundary-pack+json;v=1",
  featureCount: 1,
} satisfies RenderAssetDescriptor;
const regionalChildren = {
  ...descriptor("regional", "e"),
  mediaType: "application/vnd.odin.boundary-pack+json;v=1",
  featureCount: 1,
} satisfies RenderAssetDescriptor;
const localChildren = {
  ...descriptor("local", "f"),
  mediaType: "application/vnd.odin.boundary-pack+json;v=1",
  featureCount: 1,
} satisfies RenderAssetDescriptor;

function presentation(
  scopeKey = world,
  catalogSeed = "1",
): ResolvedPresentationInput {
  return {
    mode: "boundary",
    scopeKey,
    catalogRevision: parseCatalogRevision(
      `spatial-v1-${catalogSeed.repeat(12)}`,
    ),
    preferredLod: "overview",
    outlineLods: { overview, regional, local },
    childrenLods: {
      overview: overviewChildren,
      regional: regionalChildren,
      local: localChildren,
    },
    cameraExtent: { kind: "world" },
  };
}

class FakeAssetProvider implements BoundaryAssetProvider {
  readonly assets = new Map<string, BoundaryAsset>([
    [overview.assetId, overviewGeometry],
    [regional.assetId, regionalGeometry],
    [local.assetId, localGeometry],
    [overviewChildren.assetId, overviewChildPack],
    [regionalChildren.assetId, regionalChildPack],
    [localChildren.assetId, localChildPack],
  ]);
  readonly acquiredAssetIds: string[] = [];
  acquired = 0;
  activeLeases = 0;
  highWaterLeases = 0;
  released = 0;

  async acquire(
    descriptorValue: AssetDescriptor,
    signal: AbortSignal,
  ): Promise<BoundaryAssetLease> {
    if (signal.aborted) throw new DOMException("Aborted", "AbortError");
    const asset = this.assets.get(descriptorValue.assetId);
    if (asset === undefined) throw new Error(`missing ${descriptorValue.assetId}`);
    this.acquired += 1;
    this.acquiredAssetIds.push(descriptorValue.assetId);
    this.activeLeases += 1;
    this.highWaterLeases = Math.max(this.highWaterLeases, this.activeLeases);
    let released = false;
    return {
      asset,
      release: () => {
        if (released) return;
        released = true;
        this.released += 1;
        this.activeLeases -= 1;
      },
    };
  }
}

class FakePrimitive implements ScopePrimitiveHandle {
  show = false;
  ready = false;
  destroyed = false;

  constructor(readonly role: "render" | "pick") {}
}

class FakeContainer implements SpatialPrimitiveContainer {
  show = false;
  destroyed = false;
  readonly primitives: FakePrimitive[] = [];

  add(primitive: ScopePrimitiveHandle): void {
    this.primitives.push(primitive as FakePrimitive);
  }

  remove(primitive: ScopePrimitiveHandle): void {
    const index = this.primitives.indexOf(primitive as FakePrimitive);
    if (index < 0) return;
    const [removed] = this.primitives.splice(index, 1);
    if (removed !== undefined) removed.destroyed = true;
  }

  destroy(): void {
    if (this.destroyed) return;
    this.destroyed = true;
    for (const primitive of this.primitives) primitive.destroyed = true;
    this.primitives.splice(0);
  }
}

class FakeRuntime implements SpatialCesiumRuntime {
  readonly mounted: FakeContainer[] = [];
  readonly postRenderListeners = new Set<() => void>();
  readonly cameraListeners = new Set<() => void>();
  readonly flyCalls: Array<{ readonly positions: readonly unknown[]; readonly duration: number }> = [];
  cameraHeight = 9_000_000;
  disposed = false;

  createContainer(): SpatialPrimitiveContainer {
    return new FakeContainer();
  }

  mount(container: SpatialPrimitiveContainer): void {
    this.mounted.push(container as FakeContainer);
  }

  unmount(container: SpatialPrimitiveContainer): void {
    const candidate = container as FakeContainer;
    const index = this.mounted.indexOf(candidate);
    if (index >= 0) this.mounted.splice(index, 1);
    candidate.destroy();
  }

  onPostRender(listener: () => void): () => void {
    this.postRenderListeners.add(listener);
    return () => this.postRenderListeners.delete(listener);
  }

  onCameraMoveEnd(listener: () => void): () => void {
    this.cameraListeners.add(listener);
    return () => this.cameraListeners.delete(listener);
  }

  getCameraHeight(): number {
    return this.cameraHeight;
  }

  flyToBoundingSphere(
    positions: readonly unknown[],
    duration: number,
  ): void {
    this.flyCalls.push({ positions, duration });
  }

  firePostRender(): void {
    for (const listener of [...this.postRenderListeners]) listener();
  }

  fireCameraMoveEnd(): void {
    for (const listener of [...this.cameraListeners]) listener();
  }

  makePendingReady(): void {
    for (const container of this.mounted) {
      for (const primitive of container.primitives) primitive.ready = true;
    }
  }

  dispose(): void {
    this.disposed = true;
    this.postRenderListeners.clear();
    this.cameraListeners.clear();
    for (const container of [...this.mounted]) this.unmount(container);
  }
}

class FakeBuilder {
  readonly calls: Array<Parameters<ScopePrimitiveBuilder>[0]> = [];
  private nextError: Error | null = null;

  failNext(error: Error): void {
    this.nextError = error;
  }

  readonly builder: ScopePrimitiveBuilder = async (input) => {
    this.calls.push(input);
    if (input.signal.aborted) throw new DOMException("Aborted", "AbortError");
    if (this.nextError !== null) {
      const error = this.nextError;
      this.nextError = null;
      throw error;
    }
    return {
      renderPrimitives: [new FakePrimitive("render")],
      pickPrimitives: input.includePickSurface
        ? [new FakePrimitive("pick")]
        : [],
      cameraPositions: [
        Cesium.Cartesian3.fromDegrees(179, 0),
        Cesium.Cartesian3.fromDegrees(-179, 0),
      ],
    };
  };
}

async function waitForMounted(runtime: FakeRuntime, count: number): Promise<void> {
  await waitUntil(() => runtime.mounted.length === count);
  expect(runtime.mounted).toHaveLength(count);
}

async function waitUntil(predicate: () => boolean): Promise<void> {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    if (predicate()) return;
    await Promise.resolve();
  }
  throw new Error("Condition did not settle within 100 microtasks.");
}

async function readyPresentation(
  runtime: FakeRuntime,
  promise: Promise<void>,
): Promise<void> {
  await waitUntil(() =>
    runtime.mounted.some((container) =>
      container.primitives.some((primitive) => !primitive.ready),
    ),
  );
  runtime.makePendingReady();
  runtime.firePostRender();
  await promise;
}

function setup(options: { readonly reducedMotion?: boolean } = {}) {
  const assets = new FakeAssetProvider();
  const runtime = new FakeRuntime();
  const fakeBuilder = new FakeBuilder();
  const adapter = new CesiumSpatialScopeAdapter({
    assets,
    runtime,
    buildPrimitives: fakeBuilder.builder,
    prefersReducedMotion: () => options.reducedMotion ?? false,
  });
  return { adapter, assets, runtime, fakeBuilder };
}

describe("CesiumSpatialScopeAdapter lifecycle", () => {
  it("destroys a staging collection that failed before it could be mounted", () => {
    const viewer = {
      scene: { primitives: { add: vi.fn() } },
    } as unknown as Cesium.Viewer;
    const runtime = new ViewerSpatialCesiumRuntime(viewer);
    const staging = runtime.createContainer();
    const destroy = vi.spyOn(staging, "destroy");

    runtime.unmount(staging);

    expect(destroy).toHaveBeenCalledOnce();
  });

  it("keeps staging collections updating while primitives stay hidden until ready", async () => {
    const { adapter, assets, runtime } = setup();
    const first = adapter.present(presentation(world, "1"), 1, new AbortController().signal);
    await waitForMounted(runtime, 1);
    const firstContainer = runtime.mounted[0]!;
    expect(firstContainer.show).toBe(true);
    expect(firstContainer.primitives.every((primitive) => !primitive.show)).toBe(true);
    await readyPresentation(runtime, first);
    expect(firstContainer.show).toBe(true);

    const second = adapter.present(presentation(world, "2"), 2, new AbortController().signal);
    expect(firstContainer.show).toBe(true);
    await waitForMounted(runtime, 2);
    const secondContainer = runtime.mounted[1]!;
    expect(secondContainer.show).toBe(true);
    expect(secondContainer.primitives.every((primitive) => !primitive.show)).toBe(true);
    expect(runtime.mounted).toEqual([firstContainer, secondContainer]);
    expect(firstContainer.destroyed).toBe(false);
    await readyPresentation(runtime, second);

    expect(runtime.mounted).toEqual([secondContainer]);
    expect(firstContainer.destroyed).toBe(true);
    expect(assets.released).toBe(assets.acquired);
  });

  it("restores the last good presentation when staging fails", async () => {
    const { adapter, runtime, fakeBuilder } = setup();
    const first = adapter.present(presentation(world, "1"), 1, new AbortController().signal);
    await readyPresentation(runtime, first);
    const firstContainer = runtime.mounted[0]!;
    fakeBuilder.failNext(new Error("WebGL staging failed"));

    await expect(
      adapter.present(presentation(world, "2"), 2, new AbortController().signal),
    ).rejects.toThrow("WebGL staging failed");

    expect(runtime.mounted).toEqual([firstContainer]);
    expect(firstContainer.show).toBe(true);
    expect(firstContainer.destroyed).toBe(false);
    expect(adapter.diagnostics().activeContainers).toBe(1);
    expect(runtime.cameraListeners.size).toBe(1);
  });

  it("restores the last good presentation when staging is aborted", async () => {
    const { adapter, runtime } = setup();
    const first = adapter.present(presentation(world, "1"), 1, new AbortController().signal);
    await readyPresentation(runtime, first);
    const firstContainer = runtime.mounted[0]!;
    const aborter = new AbortController();
    const second = adapter.present(presentation(world, "2"), 2, aborter.signal);
    await waitForMounted(runtime, 2);

    aborter.abort();
    await expect(second).rejects.toMatchObject({ name: "AbortError" });

    expect(runtime.mounted).toEqual([firstContainer]);
    expect(firstContainer.show).toBe(true);
    expect(firstContainer.destroyed).toBe(false);
    expect(adapter.diagnostics().activeContainers).toBe(1);
    expect(runtime.cameraListeners.size).toBe(1);
  });

  it("clears an active presentation without disposing the reusable runtime", async () => {
    const { adapter, runtime } = setup();
    const first = adapter.present(presentation(world, "1"), 1, new AbortController().signal);
    await readyPresentation(runtime, first);

    adapter.clear();

    expect(runtime.mounted).toHaveLength(0);
    expect(runtime.cameraListeners.size).toBe(0);
    expect(runtime.disposed).toBe(false);
    expect(adapter.diagnostics()).toMatchObject({
      activeContainers: 0,
      disposed: false,
      primitiveCount: 0,
    });

    const next = adapter.present(presentation(world, "2"), 2, new AbortController().signal);
    await readyPresentation(runtime, next);
    expect(runtime.mounted).toHaveLength(1);
  });

  it("disposes stale staging and never makes it visible", async () => {
    const { adapter, assets, runtime } = setup();
    const first = adapter.present(presentation(world, "1"), 1, new AbortController().signal);
    await readyPresentation(runtime, first);

    const stale = adapter.present(presentation(world, "2"), 2, new AbortController().signal);
    await waitForMounted(runtime, 2);
    const staleContainer = runtime.mounted[1]!;
    const newest = adapter.present(presentation(world, "3"), 3, new AbortController().signal);

    await expect(stale).rejects.toMatchObject({ name: "AbortError" });
    expect(staleContainer.destroyed).toBe(true);
    expect(staleContainer.show).toBe(false);
    await waitForMounted(runtime, 2);
    await readyPresentation(runtime, newest);
    expect(runtime.mounted).toHaveLength(1);
    expect(assets.released).toBe(assets.acquired);
  });

  it("uses zero-duration camera fit for reduced motion and a dateline sphere", async () => {
    const { adapter, runtime } = setup({ reducedMotion: true });
    const current = adapter.present(presentation(), 1, new AbortController().signal);
    await readyPresentation(runtime, current);

    expect(runtime.flyCalls).toHaveLength(1);
    expect(runtime.flyCalls[0]?.duration).toBe(0);
    const positions = runtime.flyCalls[0]?.positions as readonly Cesium.Cartesian3[];
    const sphere = Cesium.BoundingSphere.fromPoints([...positions]);
    expect(sphere.radius).toBeLessThan(250_000);
    expect(sphere.center.x).toBeLessThan(0);
  });

  it("falls back to the only reviewed outline when camera height requests another LOD", async () => {
    const { adapter, assets, runtime, fakeBuilder } = setup();
    runtime.cameraHeight = 15_000_000;
    const regionalOnly: ResolvedPresentationInput = {
      ...presentation(parseScopeKeyCandidate("admin1:iso3166-2:UA-14")),
      preferredLod: "regional",
      outlineLods: { regional },
      childrenLods: {},
    };

    const current = adapter.present(regionalOnly, 1, new AbortController().signal);
    await readyPresentation(runtime, current);

    expect(assets.acquired).toBe(1);
    expect(fakeBuilder.calls[0]).toMatchObject({
      childRenderAsset: null,
      childPickAsset: null,
    });
    expect(runtime.mounted).toHaveLength(1);
    expect(adapter.diagnostics()).toMatchObject({
      activeContainers: 1,
      primitiveCount: 2,
    });
  });

  it.each([
    {
      cameraLod: "overview",
      height: 9_000_000,
      activeAsset: overviewGeometry,
      childRenderAsset: overviewChildPack,
      acquiredAssetIds: [overview.assetId, overviewChildren.assetId],
    },
    {
      cameraLod: "regional",
      height: 2_000_000,
      activeAsset: regionalGeometry,
      childRenderAsset: regionalChildPack,
      acquiredAssetIds: [
        regional.assetId,
        regionalChildren.assetId,
        overviewChildren.assetId,
      ],
    },
    {
      cameraLod: "local",
      height: 500_000,
      activeAsset: localGeometry,
      childRenderAsset: localChildPack,
      acquiredAssetIds: [
        local.assetId,
        localChildren.assetId,
        overviewChildren.assetId,
      ],
    },
  ])(
    "separates active, child-render, and preferred child-pick assets at $cameraLod LOD",
    async ({
      height,
      activeAsset,
      childRenderAsset,
      acquiredAssetIds,
    }) => {
      const { adapter, assets, runtime, fakeBuilder } = setup();
      runtime.cameraHeight = height;

      const current = adapter.present(
        presentation(),
        1,
        new AbortController().signal,
      );
      await readyPresentation(runtime, current);

      expect(fakeBuilder.calls[0]).toMatchObject({
        activeAsset,
        childRenderAsset,
        childPickAsset: overviewChildPack,
        includePickSurface: true,
      });
      expect(assets.acquiredAssetIds).toEqual(acquiredAssetIds);
      expect(assets.activeLeases).toBe(0);
      expect(assets.released).toBe(assets.acquired);
      adapter.dispose();
    },
  );

  it("uses the next available coarser child outline as a deterministic fallback", async () => {
    const { adapter, assets, runtime, fakeBuilder } = setup();
    runtime.cameraHeight = 500_000;
    const overviewChildrenOnly: ResolvedPresentationInput = {
      ...presentation(),
      childrenLods: { overview: overviewChildren },
    };

    const current = adapter.present(
      overviewChildrenOnly,
      1,
      new AbortController().signal,
    );
    await readyPresentation(runtime, current);

    expect(fakeBuilder.calls[0]).toMatchObject({
      activeAsset: localGeometry,
      childRenderAsset: overviewChildPack,
      childPickAsset: overviewChildPack,
    });
    expect(assets.acquiredAssetIds).toEqual([
      local.assetId,
      overviewChildren.assetId,
    ]);
    expect(assets.highWaterLeases).toBe(2);
    expect(assets.activeLeases).toBe(0);
    adapter.dispose();
  });

  it("does not jump from a globe request to a local-only outline", async () => {
    const { adapter, assets, runtime } = setup();
    runtime.cameraHeight = 15_000_000;
    const localOnly: ResolvedPresentationInput = {
      ...presentation(parseScopeKeyCandidate("admin1:iso3166-2:UA-14")),
      preferredLod: "local",
      outlineLods: { local },
      childrenLods: {},
    };

    const current = adapter.present(localOnly, 1, new AbortController().signal);
    let settled = false;
    void current.finally(() => {
      settled = true;
    }).catch(() => undefined);
    await waitUntil(() => settled || runtime.mounted.length > 0);
    if (runtime.mounted.length > 0) {
      runtime.makePendingReady();
      runtime.firePostRender();
    }

    await expect(current).rejects.toThrow("Spatial presentation has no renderable descriptor.");
    expect(assets.acquired).toBe(0);
    expect(runtime.mounted).toHaveLength(0);
  });

  it("records builder chunk durations for the real-browser performance gate", async () => {
    const { adapter, runtime, fakeBuilder } = setup();
    const current = adapter.present(presentation(), 1, new AbortController().signal);
    await readyPresentation(runtime, current);

    const recordChunk = fakeBuilder.calls[0]?.onChunk;
    expect(recordChunk).toBeDefined();
    recordChunk?.({ vertices: 8_000, durationMs: 12 });
    recordChunk?.({ vertices: 8_000, durationMs: 51 });

    expect(adapter.diagnostics()).toMatchObject({
      buildChunks: 2,
      maxBuildChunkDurationMs: 51,
      over50MsBuildChunks: 1,
    });
  });

  it("removes render/camera listeners and all containers on dispose", async () => {
    const { adapter, runtime } = setup();
    const current = adapter.present(presentation(), 1, new AbortController().signal);
    await waitForMounted(runtime, 1);
    expect(runtime.postRenderListeners.size).toBe(1);
    await readyPresentation(runtime, current);
    expect(runtime.postRenderListeners.size).toBe(0);
    expect(runtime.cameraListeners.size).toBe(1);

    adapter.dispose();

    expect(runtime.postRenderListeners.size).toBe(0);
    expect(runtime.cameraListeners.size).toBe(0);
    expect(runtime.mounted).toHaveLength(0);
    expect(runtime.disposed).toBe(true);
  });

  it("keeps primitive/container counts constant across 100 semantic transitions", async () => {
    const { adapter, assets, runtime } = setup();
    for (let revision = 1; revision <= 100; revision += 1) {
      const pending = adapter.present(
        presentation(world, String((revision % 9) + 1)),
        revision,
        new AbortController().signal,
      );
      await readyPresentation(runtime, pending);
      expect(runtime.mounted).toHaveLength(1);
      expect(runtime.mounted[0]?.primitives).toHaveLength(2);
      expect(runtime.postRenderListeners.size).toBe(0);
      expect(runtime.cameraListeners.size).toBe(1);
      expect(adapter.diagnostics()).toMatchObject({
        activeContainers: 1,
        primitiveCount: 2,
        stagingContainers: 0,
      });
    }

    expect(assets.acquired).toBe(200);
    expect(assets.released).toBe(assets.acquired);
    adapter.dispose();
    expect(runtime.mounted).toHaveLength(0);
    expect(runtime.postRenderListeners.size).toBe(0);
    expect(runtime.cameraListeners.size).toBe(0);
    expect(assets.released).toBe(assets.acquired);
    expect(adapter.diagnostics()).toMatchObject({
      activeContainers: 0,
      cameraListeners: 0,
      disposed: true,
      primitiveCount: 0,
      stagingContainers: 0,
    });
    expect(adapter.diagnostics().highWaterContainers).toBeLessThanOrEqual(2);
    expect(adapter.diagnostics().highWaterPrimitives).toBeLessThanOrEqual(4);
  });

  it("keeps the preferred pick primitive and bounded resources across 100 camera LOD swaps", async () => {
    const { adapter, assets, runtime, fakeBuilder } = setup();
    const initial = adapter.present(presentation(), 1, new AbortController().signal);
    await readyPresentation(runtime, initial);
    const container = runtime.mounted[0]!;
    const pick = container.primitives.find((primitive) => primitive.role === "pick");
    expect(pick).toBeDefined();
    expect(assets.activeLeases).toBe(0);

    for (let swap = 0; swap < 100; swap += 1) {
      runtime.cameraHeight = swap % 2 === 0 ? 2_000_000 : 9_000_000;
      runtime.fireCameraMoveEnd();
      await waitUntil(() => container.primitives.length === 3);
      runtime.makePendingReady();
      runtime.firePostRender();
      await waitUntil(() => container.primitives.length === 2);
      expect(container.primitives).toContain(pick);
      expect(pick?.destroyed).toBe(false);
      expect(runtime.mounted).toEqual([container]);
      expect(runtime.cameraListeners.size).toBe(1);
      expect(runtime.postRenderListeners.size).toBe(0);
      expect(assets.activeLeases).toBe(0);
      expect(assets.released).toBe(assets.acquired);
      expect(adapter.diagnostics()).toMatchObject({
        activeContainers: 1,
        cameraListeners: 1,
        primitiveCount: 2,
        stagingContainers: 0,
      });
    }

    expect(fakeBuilder.calls).toHaveLength(101);
    expect(fakeBuilder.calls.slice(1).every((call) => (
      call.childPickAsset === null && !call.includePickSurface
    ))).toBe(true);
    expect(fakeBuilder.calls.every((call) => call.stateRevision === 1)).toBe(true);
    expect(assets.acquired).toBe(202);
    expect(assets.released).toBe(202);
    expect(assets.highWaterLeases).toBeLessThanOrEqual(2);
    expect(adapter.diagnostics().highWaterContainers).toBe(1);
    expect(adapter.diagnostics().highWaterPrimitives).toBeLessThanOrEqual(3);
    adapter.dispose();
    expect(runtime.cameraListeners.size).toBe(0);
    expect(runtime.mounted).toHaveLength(0);
  });
});

describe("buildScopeGeometry chunking", () => {
  function largeGeometry(vertexCount: number): BoundaryGeometryV1 {
    const ring = Array.from({ length: vertexCount - 1 }, (_, index) =>
      [index / vertexCount, index % 2] as const,
    );
    return geometry([[ [...ring, ring[0]!] ]]);
  }

  it("yields at 8,000 vertices and rechecks abort immediately after the frame", async () => {
    const controller = new AbortController();
    let converted = 0;
    let frames = 0;

    await expect(buildScopeGeometry({
      activeAsset: largeGeometry(8_001),
      childAsset: null,
      stateRevision: 1,
      signal: controller.signal,
      convertPosition: (position) => {
        converted += 1;
        return position;
      },
      scheduler: {
        now: () => 0,
        nextFrame: async () => {
          frames += 1;
          controller.abort();
        },
      },
    })).rejects.toMatchObject({ name: "AbortError" });

    expect(converted).toBe(8_000);
    expect(frames).toBe(1);
  });

  it("yields at eight milliseconds and records no task near the 50ms gate", async () => {
    let elapsed = 0;
    const chunks: Array<{ readonly vertices: number; readonly durationMs: number }> = [];
    const result = await buildScopeGeometry({
      activeAsset: largeGeometry(25),
      childAsset: null,
      stateRevision: 1,
      signal: new AbortController().signal,
      convertPosition: (position) => {
        elapsed += 1;
        return position;
      },
      scheduler: {
        now: () => elapsed,
        nextFrame: () => Promise.resolve(),
      },
      onChunk: (chunk) => chunks.push(chunk),
    });

    expect(result.cameraPositions).toHaveLength(25);
    expect(chunks.map((chunk) => chunk.vertices)).toEqual([8, 8, 8, 1]);
    expect(Math.max(...chunks.map((chunk) => chunk.durationMs))).toBeLessThan(50);
  });

  it("creates at most three batched Cesium groups and forwards the catalog pick ID", async () => {
    // GroundPolylinePrimitive reads these values during construction. A real Viewer
    // initializes them from WebGL; jsdom has no context, so emulate the WebGL minimum.
    const contextLimits = (Cesium as unknown as {
      ContextLimits: {
        _minimumAliasedLineWidth: number;
        _maximumAliasedLineWidth: number;
      };
    }).ContextLimits;
    const previousMinimum = contextLimits._minimumAliasedLineWidth;
    const previousMaximum = contextLimits._maximumAliasedLineWidth;
    contextLimits._minimumAliasedLineWidth = 1;
    contextLimits._maximumAliasedLineWidth = 1;
    let built: Awaited<ReturnType<typeof buildScopePrimitives>>;
    try {
      built = await buildScopePrimitives({
        activeAsset: activeGeometry,
        childRenderAsset: childPack,
        childPickAsset: childPack,
        stateRevision: 17,
        includePickSurface: true,
        signal: new AbortController().signal,
        scheduler: {
          now: () => 0,
          nextFrame: () => Promise.resolve(),
        },
      });
    } finally {
      contextLimits._minimumAliasedLineWidth = previousMinimum;
      contextLimits._maximumAliasedLineWidth = previousMaximum;
    }

    expect(built.renderPrimitives).toHaveLength(2);
    expect(built.pickPrimitives).toHaveLength(1);
    expect(
      built.renderPrimitives.length + built.pickPrimitives.length,
    ).toBeLessThanOrEqual(3);
    expect(
      [...built.renderPrimitives, ...built.pickPrimitives]
        .every((primitive) => !primitive.show),
    ).toBe(true);

    const pickHandle = built.pickPrimitives[0];
    expect(pickHandle).toBeInstanceOf(CesiumScopePrimitiveHandle);
    const pickPrimitive = (pickHandle as CesiumScopePrimitiveHandle).primitive;
    expect(pickPrimitive).toBeInstanceOf(Cesium.GroundPrimitive);
    const instances = (pickPrimitive as Cesium.GroundPrimitive).geometryInstances;
    const first = Array.isArray(instances) ? instances[0] : instances;
    expect(first?.id).toEqual({
      odinKind: "spatial-child",
      scopeKey: child,
      stateRevision: 17,
    });
  });
});
