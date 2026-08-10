import * as Cesium from "cesium";

import type {
  BoundaryAsset,
  BoundaryAssetLease,
  BoundaryPackV1,
} from "../catalog";
import type {
  AssetDescriptor,
  AssetLodSet,
  GeometryLod,
  RenderAssetDescriptor,
  ResolvedPresentationInput,
} from "../contracts";
import { bandForHeight } from "../../lib/lod";
import {
  buildScopePrimitives,
  CesiumScopePrimitiveHandle,
  type BuildScopePrimitivesOptions,
  type ScopePrimitiveBuild,
  type ScopePrimitiveHandle,
} from "./buildScopePrimitives";

export interface BoundaryAssetProvider {
  acquire(
    descriptor: AssetDescriptor,
    signal: AbortSignal,
  ): Promise<BoundaryAssetLease>;
}

export interface SpatialPrimitiveContainer {
  show: boolean;
  readonly primitives: readonly ScopePrimitiveHandle[];
  add(primitive: ScopePrimitiveHandle): void;
  remove(primitive: ScopePrimitiveHandle): void;
  destroy(): void;
}

export interface SpatialCesiumRuntime {
  createContainer(): SpatialPrimitiveContainer;
  mount(container: SpatialPrimitiveContainer): void;
  unmount(container: SpatialPrimitiveContainer): void;
  onPostRender(listener: () => void): () => void;
  onCameraMoveEnd(listener: () => void): () => void;
  getCameraHeight(): number;
  flyToBoundingSphere(positions: readonly unknown[], duration: number): void;
  dispose(): void;
}

export type ScopePrimitiveBuilder = (
  input: BuildScopePrimitivesOptions,
) => Promise<ScopePrimitiveBuild>;

class CesiumPrimitiveContainer implements SpatialPrimitiveContainer {
  readonly collection = new Cesium.PrimitiveCollection({ destroyPrimitives: true });
  readonly primitiveList: ScopePrimitiveHandle[] = [];
  destroyed = false;

  get show(): boolean {
    return this.collection.show;
  }

  set show(value: boolean) {
    this.collection.show = value;
  }

  get primitives(): readonly ScopePrimitiveHandle[] {
    return this.primitiveList;
  }

  add(primitive: ScopePrimitiveHandle): void {
    if (!(primitive instanceof CesiumScopePrimitiveHandle)) {
      throw new TypeError("Cesium runtime received a foreign primitive handle.");
    }
    this.collection.add(primitive.primitive);
    this.primitiveList.push(primitive);
  }

  remove(primitive: ScopePrimitiveHandle): void {
    const index = this.primitiveList.indexOf(primitive);
    if (index < 0) return;
    if (!(primitive instanceof CesiumScopePrimitiveHandle)) {
      throw new TypeError("Cesium runtime received a foreign primitive handle.");
    }
    this.primitiveList.splice(index, 1);
    this.collection.remove(primitive.primitive);
  }

  destroy(): void {
    if (this.destroyed) return;
    this.destroyed = true;
    this.primitiveList.splice(0);
    if (!this.collection.isDestroyed()) this.collection.destroy();
  }

  markUnmounted(): void {
    this.destroyed = true;
    this.primitiveList.splice(0);
  }
}

export class ViewerSpatialCesiumRuntime implements SpatialCesiumRuntime {
  private readonly root = new Cesium.PrimitiveCollection({ destroyPrimitives: true });
  private readonly containers = new Set<CesiumPrimitiveContainer>();
  private disposed = false;

  constructor(private readonly viewer: Cesium.Viewer) {
    viewer.scene.primitives.add(this.root);
  }

  createContainer(): SpatialPrimitiveContainer {
    if (this.disposed) throw new Error("Spatial Cesium runtime is disposed.");
    return new CesiumPrimitiveContainer();
  }

  mount(container: SpatialPrimitiveContainer): void {
    const owned = this.ownedContainer(container);
    this.root.add(owned.collection);
    this.containers.add(owned);
  }

  unmount(container: SpatialPrimitiveContainer): void {
    const owned = this.ownedContainer(container);
    if (!this.containers.delete(owned)) {
      owned.destroy();
      return;
    }
    this.root.remove(owned.collection);
    owned.markUnmounted();
  }

  onPostRender(listener: () => void): () => void {
    return this.viewer.scene.postRender.addEventListener(listener);
  }

  onCameraMoveEnd(listener: () => void): () => void {
    return this.viewer.camera.moveEnd.addEventListener(listener);
  }

  getCameraHeight(): number {
    return this.viewer.camera.positionCartographic.height;
  }

  flyToBoundingSphere(positions: readonly unknown[], duration: number): void {
    const cartesian = positions.filter(
      (position): position is Cesium.Cartesian3 => position instanceof Cesium.Cartesian3,
    );
    if (cartesian.length === 0 || this.viewer.isDestroyed()) return;
    const sphere = Cesium.BoundingSphere.fromPoints(cartesian);
    this.viewer.camera.flyToBoundingSphere(sphere, {
      duration,
      offset: new Cesium.HeadingPitchRange(0, -Cesium.Math.PI_OVER_TWO, 0),
    });
  }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    this.containers.clear();
    if (!this.viewer.isDestroyed()) {
      this.viewer.scene.primitives.remove(this.root);
    } else if (!this.root.isDestroyed()) {
      this.root.destroy();
    }
  }

  private ownedContainer(
    container: SpatialPrimitiveContainer,
  ): CesiumPrimitiveContainer {
    if (!(container instanceof CesiumPrimitiveContainer)) {
      throw new TypeError("Spatial runtime received a foreign container.");
    }
    return container;
  }
}

interface ActivePresentation {
  readonly container: SpatialPrimitiveContainer;
  readonly input: ResolvedPresentationInput;
  readonly stateRevision: number;
  readonly pickPrimitives: readonly ScopePrimitiveHandle[];
  renderPrimitives: readonly ScopePrimitiveHandle[];
  activeRenderAssetId: string | null;
  childRenderAssetId: string | null;
}

interface AcquiredAssets {
  readonly activeAsset: BoundaryAsset | null;
  readonly childRenderAsset: BoundaryPackV1 | null;
  readonly childPickAsset: BoundaryPackV1 | null;
  release(): void;
}

export interface CesiumSpatialScopeAdapterOptions {
  readonly assets: BoundaryAssetProvider;
  readonly runtime: SpatialCesiumRuntime;
  readonly buildPrimitives?: ScopePrimitiveBuilder;
  readonly prefersReducedMotion?: () => boolean;
}

export interface CesiumSpatialScopeDiagnostics {
  readonly activeContainers: number;
  readonly buildChunks: number;
  readonly cameraListeners: number;
  readonly disposed: boolean;
  readonly highWaterContainers: number;
  readonly highWaterPrimitives: number;
  readonly maxBuildChunkDurationMs: number;
  readonly over50MsBuildChunks: number;
  readonly postRenderChecks: number;
  readonly postRenderWaiters: number;
  readonly primitiveCount: number;
  readonly readyPrimitiveCount: number;
  readonly stagingContainers: number;
}

function abortError(): DOMException {
  return new DOMException("The operation was aborted.", "AbortError");
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

function asBoundaryPack(asset: BoundaryAsset, descriptor: RenderAssetDescriptor): BoundaryPackV1 {
  if (!("features" in asset)) {
    throw new Error(`Child asset ${descriptor.assetId} is not a boundary pack.`);
  }
  return asset;
}

function preferredChildDescriptor(
  input: ResolvedPresentationInput,
): RenderAssetDescriptor | null {
  return input.childrenLods[input.preferredLod] ?? null;
}

function desiredLod(height: number): GeometryLod {
  const band = bandForHeight(height);
  if (band === "GLOBE") return "overview";
  if (band === "REGIONAL") return "regional";
  return "local";
}

function renderDescriptorForHeight(
  lods: AssetLodSet,
  height: number,
): RenderAssetDescriptor | null {
  const target = desiredLod(height);
  const candidates: readonly GeometryLod[] = target === "local"
    ? ["local", "regional", "overview"]
    : target === "regional"
      ? ["regional", "overview", "local"]
      : ["overview", "regional"];
  for (const lod of candidates) {
    const descriptor = lods[lod];
    if (descriptor !== undefined) return descriptor;
  }
  return null;
}

export class CesiumSpatialScopeAdapter {
  private readonly assets: BoundaryAssetProvider;
  private readonly runtime: SpatialCesiumRuntime;
  private readonly buildPrimitives: ScopePrimitiveBuilder;
  private readonly prefersReducedMotion: () => boolean;
  private readonly staging = new Map<SpatialPrimitiveContainer, number>();
  private active: ActivePresentation | null = null;
  private presentationController: AbortController | null = null;
  private lodController: AbortController | null = null;
  private removeCameraListener: (() => void) | null = null;
  private generation = 0;
  private lodGeneration = 0;
  private postRenderChecks = 0;
  private postRenderWaiters = 0;
  private buildChunks = 0;
  private maxBuildChunkDurationMs = 0;
  private over50MsBuildChunks = 0;
  private highWaterContainers = 0;
  private highWaterPrimitives = 0;
  private disposed = false;

  constructor(options: CesiumSpatialScopeAdapterOptions) {
    this.assets = options.assets;
    this.runtime = options.runtime;
    this.buildPrimitives = options.buildPrimitives ?? buildScopePrimitives;
    this.prefersReducedMotion = options.prefersReducedMotion
      ?? (() => globalThis.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false);
  }

  async present(
    input: ResolvedPresentationInput,
    stateRevision: number,
    callerSignal: AbortSignal,
  ): Promise<void> {
    if (this.disposed) throw new Error("Cesium spatial adapter is disposed.");
    this.presentationController?.abort();
    this.lodController?.abort();
    this.removeCameraListener?.();
    this.removeCameraListener = null;
    const controller = new AbortController();
    this.presentationController = controller;
    const detachCaller = this.forwardAbort(callerSignal, controller);
    const generation = ++this.generation;
    this.lodGeneration += 1;
    const previous = this.active;
    if (previous !== null) previous.container.show = false;

    let staging: SpatialPrimitiveContainer | null = null;
    let acquired: AcquiredAssets | null = null;
    try {
      const activeRenderDescriptor = renderDescriptorForHeight(
        input.outlineLods,
        this.runtime.getCameraHeight(),
      );
      const childRenderDescriptor = renderDescriptorForHeight(
        input.childrenLods,
        this.runtime.getCameraHeight(),
      );
      const pickDescriptor = preferredChildDescriptor(input);
      if (
        activeRenderDescriptor === null
        && childRenderDescriptor === null
        && pickDescriptor === null
      ) {
        throw new Error("Spatial presentation has no renderable descriptor.");
      }
      acquired = await this.acquireAssets(
        activeRenderDescriptor,
        childRenderDescriptor,
        pickDescriptor,
        controller.signal,
      );
      this.assertPresentationCurrent(generation, controller.signal);
      const build = await this.buildPrimitives({
        activeAsset: acquired.activeAsset,
        childRenderAsset: acquired.childRenderAsset,
        childPickAsset: acquired.childPickAsset,
        stateRevision,
        includePickSurface: true,
        signal: controller.signal,
        onChunk: (chunk) => this.recordBuildChunk(chunk.durationMs),
      });
      this.assertPresentationCurrent(generation, controller.signal);

      staging = this.runtime.createContainer();
      // PrimitiveCollection skips update entirely while hidden. Keep the
      // collection updating so Cesium can compile its children, while each
      // primitive remains hidden until the generation-safe swap below.
      staging.show = true;
      for (const primitive of [...build.renderPrimitives, ...build.pickPrimitives]) {
        primitive.show = false;
        staging.add(primitive);
      }
      this.runtime.mount(staging);
      this.staging.set(staging, staging.primitives.length);
      this.updateHighWater();
      await this.waitUntilReady(
        [...build.renderPrimitives, ...build.pickPrimitives],
        controller.signal,
        () => this.generation === generation,
      );
      this.assertPresentationCurrent(generation, controller.signal);
      for (const primitive of [...build.renderPrimitives, ...build.pickPrimitives]) {
        primitive.show = true;
      }
      staging.show = true;
      if (previous !== null && this.active === previous) {
        this.runtime.unmount(previous.container);
      }
      this.staging.delete(staging);
      this.active = {
        container: staging,
        input,
        stateRevision,
        pickPrimitives: build.pickPrimitives,
        renderPrimitives: build.renderPrimitives,
        activeRenderAssetId: activeRenderDescriptor?.assetId ?? null,
        childRenderAssetId: childRenderDescriptor?.assetId ?? null,
      };
      this.updateHighWater();
      staging = null;
      this.runtime.flyToBoundingSphere(
        build.cameraPositions,
        this.prefersReducedMotion() ? 0 : 1.2,
      );
      this.removeCameraListener = this.runtime.onCameraMoveEnd(() => {
        void this.swapCameraLod().catch(() => undefined);
      });
    } catch (error: unknown) {
      if (staging !== null) {
        staging.show = false;
        this.staging.delete(staging);
        this.runtime.unmount(staging);
      }
      if (
        this.generation === generation
        && previous !== null
        && this.active === previous
      ) {
        this.runtime.unmount(previous.container);
        this.active = null;
      }
      throw error;
    } finally {
      acquired?.release();
      detachCaller();
      if (this.presentationController === controller) {
        this.presentationController = null;
      }
    }
  }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    this.generation += 1;
    this.lodGeneration += 1;
    this.presentationController?.abort();
    this.presentationController = null;
    this.lodController?.abort();
    this.lodController = null;
    this.removeCameraListener?.();
    this.removeCameraListener = null;
    if (this.active !== null) {
      this.runtime.unmount(this.active.container);
      this.active = null;
    }
    this.staging.clear();
    this.runtime.dispose();
  }

  diagnostics(): CesiumSpatialScopeDiagnostics {
    return Object.freeze({
      activeContainers: this.active === null ? 0 : 1,
      buildChunks: this.buildChunks,
      cameraListeners: this.removeCameraListener === null ? 0 : 1,
      disposed: this.disposed,
      highWaterContainers: this.highWaterContainers,
      highWaterPrimitives: this.highWaterPrimitives,
      maxBuildChunkDurationMs: this.maxBuildChunkDurationMs,
      over50MsBuildChunks: this.over50MsBuildChunks,
      postRenderChecks: this.postRenderChecks,
      postRenderWaiters: this.postRenderWaiters,
      primitiveCount: this.currentPrimitiveCount(),
      readyPrimitiveCount: this.currentReadyPrimitiveCount(),
      stagingContainers: this.staging.size,
    });
  }

  private async swapCameraLod(): Promise<void> {
    const active = this.active;
    if (this.disposed || active === null) return;
    const activeRenderDescriptor = renderDescriptorForHeight(
      active.input.outlineLods,
      this.runtime.getCameraHeight(),
    );
    const childRenderDescriptor = renderDescriptorForHeight(
      active.input.childrenLods,
      this.runtime.getCameraHeight(),
    );
    if (activeRenderDescriptor === null && childRenderDescriptor === null) return;
    if (
      (activeRenderDescriptor?.assetId ?? null) === active.activeRenderAssetId
      && (childRenderDescriptor?.assetId ?? null) === active.childRenderAssetId
    ) return;
    this.lodController?.abort();
    const controller = new AbortController();
    this.lodController = controller;
    const lodGeneration = ++this.lodGeneration;
    let acquired: AcquiredAssets | null = null;
    let staged: readonly ScopePrimitiveHandle[] = [];
    try {
      acquired = await this.acquireAssets(
        activeRenderDescriptor,
        childRenderDescriptor,
        null,
        controller.signal,
      );
      this.assertLodCurrent(active, lodGeneration, controller.signal);
      const build = await this.buildPrimitives({
        activeAsset: acquired.activeAsset,
        childRenderAsset: acquired.childRenderAsset,
        childPickAsset: null,
        stateRevision: active.stateRevision,
        includePickSurface: false,
        signal: controller.signal,
        onChunk: (chunk) => this.recordBuildChunk(chunk.durationMs),
      });
      this.assertLodCurrent(active, lodGeneration, controller.signal);
      staged = build.renderPrimitives;
      for (const primitive of staged) {
        primitive.show = false;
        active.container.add(primitive);
      }
      this.updateHighWater();
      await this.waitUntilReady(
        staged,
        controller.signal,
        () => this.active === active && this.lodGeneration === lodGeneration,
      );
      this.assertLodCurrent(active, lodGeneration, controller.signal);
      for (const primitive of staged) primitive.show = true;
      for (const primitive of active.renderPrimitives) active.container.remove(primitive);
      active.renderPrimitives = staged;
      active.activeRenderAssetId = activeRenderDescriptor?.assetId ?? null;
      active.childRenderAssetId = childRenderDescriptor?.assetId ?? null;
      staged = [];
      this.updateHighWater();
    } catch (error: unknown) {
      for (const primitive of staged) active.container.remove(primitive);
      if (!isAbortError(error)) throw error;
    } finally {
      acquired?.release();
      if (this.lodController === controller) this.lodController = null;
    }
  }

  private async acquireAssets(
    activeRenderDescriptor: RenderAssetDescriptor | null,
    childRenderDescriptor: RenderAssetDescriptor | null,
    childPickDescriptor: RenderAssetDescriptor | null,
    signal: AbortSignal,
  ): Promise<AcquiredAssets> {
    const leases = new Map<string, BoundaryAssetLease>();
    try {
      for (const descriptor of [
        activeRenderDescriptor,
        childRenderDescriptor,
        childPickDescriptor,
      ]) {
        if (descriptor === null || leases.has(descriptor.assetId)) continue;
        leases.set(descriptor.assetId, await this.assets.acquire(descriptor, signal));
      }
      if (signal.aborted) throw abortError();
      const activeAsset = activeRenderDescriptor === null
        ? null
        : leases.get(activeRenderDescriptor.assetId)?.asset ?? null;
      const childRenderValue = childRenderDescriptor === null
        ? null
        : leases.get(childRenderDescriptor.assetId)?.asset ?? null;
      const childPickValue = childPickDescriptor === null
        ? null
        : leases.get(childPickDescriptor.assetId)?.asset ?? null;
      const childRenderAsset = childRenderValue === null || childRenderDescriptor === null
        ? null
        : asBoundaryPack(childRenderValue, childRenderDescriptor);
      const childPickAsset = childPickValue === null || childPickDescriptor === null
        ? null
        : asBoundaryPack(childPickValue, childPickDescriptor);
      return {
        activeAsset,
        childRenderAsset,
        childPickAsset,
        release: () => {
          for (const lease of leases.values()) lease.release();
        },
      };
    } catch (error: unknown) {
      for (const lease of leases.values()) lease.release();
      throw error;
    }
  }

  private waitUntilReady(
    primitives: readonly ScopePrimitiveHandle[],
    signal: AbortSignal,
    isCurrent: () => boolean,
  ): Promise<void> {
    if (signal.aborted || !isCurrent()) return Promise.reject(abortError());
    if (primitives.every((primitive) => primitive.ready)) return Promise.resolve();
    return new Promise<void>((resolve, reject) => {
      let settled = false;
      let removePostRender: () => void = () => undefined;
      this.postRenderWaiters += 1;
      const finish = (callback: () => void) => {
        if (settled) return;
        settled = true;
        this.postRenderWaiters -= 1;
        signal.removeEventListener("abort", onAbort);
        removePostRender();
        callback();
      };
      const onAbort = () => finish(() => reject(abortError()));
      const check = () => {
        this.postRenderChecks += 1;
        if (signal.aborted || !isCurrent()) {
          onAbort();
        } else if (primitives.every((primitive) => primitive.ready)) {
          finish(resolve);
        }
      };
      signal.addEventListener("abort", onAbort, { once: true });
      removePostRender = this.runtime.onPostRender(check);
      check();
    });
  }

  private assertPresentationCurrent(
    generation: number,
    signal: AbortSignal,
  ): void {
    if (this.disposed || signal.aborted || this.generation !== generation) {
      throw abortError();
    }
  }

  private assertLodCurrent(
    active: ActivePresentation,
    lodGeneration: number,
    signal: AbortSignal,
  ): void {
    if (
      this.disposed
      || signal.aborted
      || this.active !== active
      || this.lodGeneration !== lodGeneration
    ) {
      throw abortError();
    }
  }

  private forwardAbort(source: AbortSignal, destination: AbortController): () => void {
    const abort = () => destination.abort();
    if (source.aborted) destination.abort();
    else source.addEventListener("abort", abort, { once: true });
    return () => source.removeEventListener("abort", abort);
  }

  private currentPrimitiveCount(): number {
    return (this.active?.container.primitives.length ?? 0)
      + [...this.staging.values()].reduce((total, count) => total + count, 0);
  }

  private recordBuildChunk(durationMs: number): void {
    this.buildChunks += 1;
    this.maxBuildChunkDurationMs = Math.max(
      this.maxBuildChunkDurationMs,
      durationMs,
    );
    if (durationMs > 50) this.over50MsBuildChunks += 1;
  }

  private currentReadyPrimitiveCount(): number {
    const active = this.active?.container.primitives ?? [];
    const staging = [...this.staging.keys()].flatMap(
      (container) => [...container.primitives],
    );
    return [...active, ...staging].filter((primitive) => primitive.ready).length;
  }

  private updateHighWater(): void {
    this.highWaterContainers = Math.max(
      this.highWaterContainers,
      (this.active === null ? 0 : 1) + this.staging.size,
    );
    this.highWaterPrimitives = Math.max(
      this.highWaterPrimitives,
      this.currentPrimitiveCount(),
    );
  }
}

export function createCesiumSpatialScopeAdapter(
  viewer: Cesium.Viewer,
  assets: BoundaryAssetProvider,
): CesiumSpatialScopeAdapter {
  return new CesiumSpatialScopeAdapter({
    assets,
    runtime: new ViewerSpatialCesiumRuntime(viewer),
  });
}
