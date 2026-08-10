import type { BoundaryAssetLease } from "./catalog";
import {
  freezeSpatialValue,
  type ContainmentAssetDescriptor,
  type ContainmentSnapshot,
  type ScopeKind,
  type SpatialContainmentPort,
} from "./contracts";
import {
  assertWgs84Point,
  createBoundaryGeometryIndex,
} from "./geometry";

export interface SpatialContainmentAssetPort {
  acquire(
    descriptor: ContainmentAssetDescriptor,
    signal: AbortSignal,
  ): Promise<BoundaryAssetLease>;
}

export interface SpatialContainmentCommit {
  readonly scopeKind: ScopeKind;
  readonly descriptor: ContainmentAssetDescriptor | null;
  readonly stateRevision: number;
}

export interface SpatialContainmentLifecyclePort {
  commit(input: SpatialContainmentCommit): void;
  reset(stateRevision: number): void;
}

export interface OwnedSpatialContainmentPort
  extends SpatialContainmentPort, SpatialContainmentLifecyclePort {
  dispose(): void;
}

export interface CreateSpatialContainmentControllerOptions {
  readonly assets: SpatialContainmentAssetPort;
}

const INITIAL_CONTAINMENT_SNAPSHOT = freezeSpatialValue({
  phase: "unavailable",
  stateRevision: 0,
} satisfies ContainmentSnapshot);

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

class SpatialContainmentController implements OwnedSpatialContainmentPort {
  private readonly assets: SpatialContainmentAssetPort;
  private readonly listeners = new Set<() => void>();
  private snapshot: ContainmentSnapshot = INITIAL_CONTAINMENT_SNAPSHOT;
  private loadController: AbortController | null = null;
  private currentLease: BoundaryAssetLease | null = null;
  private generation = 0;
  private disposed = false;

  constructor(options: CreateSpatialContainmentControllerOptions) {
    this.assets = options.assets;
  }

  getSnapshot = (): ContainmentSnapshot => this.snapshot;

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  commit(input: SpatialContainmentCommit): void {
    if (this.disposed) throw new Error("Spatial containment has been disposed.");
    const generation = this.invalidateCurrent();

    if (input.scopeKind === "world") {
      this.publish(freezeSpatialValue({
        phase: "building",
        stateRevision: input.stateRevision,
      } satisfies ContainmentSnapshot));
      queueMicrotask(() => {
        if (this.disposed || this.generation !== generation) return;
        this.publish(freezeSpatialValue({
          phase: "ready",
          stateRevision: input.stateRevision,
          contains(longitude: number, latitude: number) {
            assertWgs84Point(longitude, latitude);
            return "inside" as const;
          },
        } satisfies ContainmentSnapshot));
      });
      return;
    }

    if (input.descriptor === null) {
      this.publish(freezeSpatialValue({
        phase: "unavailable",
        stateRevision: input.stateRevision,
      } satisfies ContainmentSnapshot));
      return;
    }

    this.publish(freezeSpatialValue({
      phase: "building",
      stateRevision: input.stateRevision,
    } satisfies ContainmentSnapshot));
    const controller = new AbortController();
    this.loadController = controller;
    void this.buildIndex(
      { ...input, descriptor: input.descriptor },
      generation,
      controller,
    );
  }

  reset(stateRevision: number): void {
    if (this.disposed) return;
    this.invalidateCurrent();
    this.publish(freezeSpatialValue({
      phase: "unavailable",
      stateRevision,
    } satisfies ContainmentSnapshot));
  }

  dispose(): void {
    if (this.disposed) return;
    this.invalidateCurrent();
    this.disposed = true;
    this.snapshot = INITIAL_CONTAINMENT_SNAPSHOT;
    this.listeners.clear();
  }

  private invalidateCurrent(): number {
    this.generation += 1;
    this.loadController?.abort();
    this.loadController = null;
    this.currentLease?.release();
    this.currentLease = null;
    return this.generation;
  }

  private async buildIndex(
    input: SpatialContainmentCommit & {
      readonly descriptor: ContainmentAssetDescriptor;
    },
    generation: number,
    controller: AbortController,
  ): Promise<void> {
    let lease: BoundaryAssetLease | null = null;
    try {
      lease = await this.assets.acquire(input.descriptor, controller.signal);
      if (!this.isCurrent(generation, controller)) {
        lease.release();
        return;
      }
      if (!("geometryType" in lease.asset)) {
        lease.release();
        lease = null;
        this.publishUnavailable(input.stateRevision, generation, controller);
        return;
      }

      const index = createBoundaryGeometryIndex([
        { value: true, geometry: lease.asset },
      ]);
      const maxErrorMeters = input.descriptor.maxErrorMeters;
      this.currentLease = lease;
      lease = null;
      this.loadController = null;
      this.publish(freezeSpatialValue({
        phase: "ready",
        stateRevision: input.stateRevision,
        contains(longitude: number, latitude: number) {
          const hit = index.query(longitude, latitude, maxErrorMeters)[0];
          return hit?.containment ?? "outside";
        },
      } satisfies ContainmentSnapshot));
    } catch (error: unknown) {
      lease?.release();
      if (!isAbortError(error)) {
        this.publishUnavailable(input.stateRevision, generation, controller);
      }
    }
  }

  private publishUnavailable(
    stateRevision: number,
    generation: number,
    controller: AbortController,
  ): void {
    if (!this.isCurrent(generation, controller)) return;
    this.loadController = null;
    this.publish(freezeSpatialValue({
      phase: "unavailable",
      stateRevision,
    } satisfies ContainmentSnapshot));
  }

  private isCurrent(generation: number, controller: AbortController): boolean {
    return !this.disposed
      && !controller.signal.aborted
      && this.generation === generation
      && this.loadController === controller;
  }

  private publish(snapshot: ContainmentSnapshot): void {
    this.snapshot = snapshot;
    for (const listener of [...this.listeners]) listener();
  }
}

export function createSpatialContainmentController(
  options: CreateSpatialContainmentControllerOptions,
): OwnedSpatialContainmentPort {
  return new SpatialContainmentController(options);
}
