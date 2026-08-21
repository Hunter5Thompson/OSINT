import type { ScopeKey } from "./contracts";

export interface PrefetchScheduleResult {
  readonly outcome: "completed" | "cancelled";
}

export interface PrefetchSchedulerDiagnostics {
  readonly active: number;
  readonly cancelled: number;
  readonly completed: number;
  readonly disposed: boolean;
  readonly failed: number;
  readonly highWaterActive: number;
  readonly maxConcurrency: number;
  readonly queued: number;
  readonly replaced: number;
}

export interface BoundedPrefetchSchedulerOptions {
  readonly maxConcurrency?: number;
}

type ScheduledPrefetch = (signal: AbortSignal) => Promise<void>;

interface PrefetchJob {
  readonly controller: AbortController;
  readonly detachCallerSignal: () => void;
  readonly reject: (error: unknown) => void;
  readonly resolve: (result: PrefetchScheduleResult) => void;
  readonly run: ScheduledPrefetch;
  settled: boolean;
  started: boolean;
}

function abortError(): DOMException {
  return new DOMException("The operation was aborted.", "AbortError");
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

export class BoundedPrefetchScheduler {
  private readonly maxConcurrency: number;
  private readonly active = new Set<PrefetchJob>();
  private queued: PrefetchJob | null = null;
  private cancelled = 0;
  private completed = 0;
  private failed = 0;
  private highWaterActive = 0;
  private replaced = 0;
  private disposed = false;

  constructor(options: BoundedPrefetchSchedulerOptions = {}) {
    this.maxConcurrency = options.maxConcurrency ?? 2;
    if (
      !Number.isSafeInteger(this.maxConcurrency)
      || this.maxConcurrency < 1
      || this.maxConcurrency > 8
    ) {
      throw new RangeError("maxConcurrency must be an integer between 1 and 8");
    }
  }

  schedule(
    run: ScheduledPrefetch,
    callerSignal?: AbortSignal,
  ): Promise<PrefetchScheduleResult> {
    if (this.disposed || callerSignal?.aborted === true) {
      this.cancelled += 1;
      return Promise.resolve({ outcome: "cancelled" });
    }

    let job: PrefetchJob;
    const result = new Promise<PrefetchScheduleResult>((resolve, reject) => {
      const controller = new AbortController();
      const abort = () => this.cancel(job);
      if (callerSignal !== undefined) {
        callerSignal.addEventListener("abort", abort, { once: true });
      }
      job = {
        controller,
        detachCallerSignal: () => callerSignal?.removeEventListener("abort", abort),
        reject,
        resolve,
        run,
        settled: false,
        started: false,
      };
    });

    if (this.active.size < this.maxConcurrency) {
      this.start(job!);
    } else {
      if (this.queued !== null) {
        this.replaced += 1;
        this.settleCancelled(this.queued);
      }
      this.queued = job!;
    }
    return result;
  }

  diagnostics(): PrefetchSchedulerDiagnostics {
    return Object.freeze({
      active: this.active.size,
      cancelled: this.cancelled,
      completed: this.completed,
      disposed: this.disposed,
      failed: this.failed,
      highWaterActive: this.highWaterActive,
      maxConcurrency: this.maxConcurrency,
      queued: this.queued === null ? 0 : 1,
      replaced: this.replaced,
    });
  }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    this.cancelAll();
  }

  cancelAll(): void {
    if (this.queued !== null) {
      const queued = this.queued;
      this.queued = null;
      this.settleCancelled(queued);
    }
    for (const job of this.active) job.controller.abort(abortError());
  }

  private start(job: PrefetchJob): void {
    if (job.settled) return;
    if (this.disposed) {
      this.settleCancelled(job);
      return;
    }
    job.started = true;
    this.active.add(job);
    this.highWaterActive = Math.max(this.highWaterActive, this.active.size);
    void Promise.resolve()
      .then(() => {
        if (job.controller.signal.aborted) throw abortError();
        return job.run(job.controller.signal);
      })
      .then(
        () => {
          if (job.controller.signal.aborted) this.settleCancelled(job);
          else this.settleCompleted(job);
        },
        (error: unknown) => {
          if (job.controller.signal.aborted || isAbortError(error)) {
            this.settleCancelled(job);
          } else {
            this.settleFailed(job, error);
          }
        },
      )
      .finally(() => {
        this.active.delete(job);
        this.pump();
      });
  }

  private cancel(job: PrefetchJob): void {
    if (job.settled) return;
    job.controller.abort(abortError());
    if (!job.started) {
      if (this.queued === job) this.queued = null;
      this.settleCancelled(job);
      this.pump();
    }
  }

  private settleCompleted(job: PrefetchJob): void {
    if (job.settled) return;
    job.settled = true;
    this.completed += 1;
    job.detachCallerSignal();
    job.resolve({ outcome: "completed" });
  }

  private settleCancelled(job: PrefetchJob): void {
    if (job.settled) return;
    job.settled = true;
    job.controller.abort(abortError());
    this.cancelled += 1;
    job.detachCallerSignal();
    job.resolve({ outcome: "cancelled" });
  }

  private settleFailed(job: PrefetchJob, error: unknown): void {
    if (job.settled) return;
    job.settled = true;
    this.failed += 1;
    job.detachCallerSignal();
    job.reject(error);
  }

  private pump(): void {
    if (
      this.disposed
      || this.queued === null
      || this.active.size >= this.maxConcurrency
    ) {
      return;
    }
    const next = this.queued;
    this.queued = null;
    this.start(next);
  }
}

export interface SpatialPrefetchCapabilities {
  readonly coarsePointer: boolean;
  readonly hover: boolean;
  readonly saveData: boolean;
}

export function allowsSpatialHoverPrefetch(
  capabilities: SpatialPrefetchCapabilities,
): boolean {
  return capabilities.hover && !capabilities.coarsePointer && !capabilities.saveData;
}

interface NavigatorWithConnection extends Navigator {
  readonly connection?: { readonly saveData?: boolean };
}

export function readSpatialPrefetchCapabilities(): SpatialPrefetchCapabilities {
  const media = globalThis.matchMedia;
  const navigatorValue = globalThis.navigator as NavigatorWithConnection | undefined;
  return Object.freeze({
    coarsePointer: media?.("(pointer: coarse)").matches ?? true,
    hover: media?.("(hover: hover)").matches ?? false,
    saveData: navigatorValue?.connection?.saveData === true,
  });
}

export interface HoverPrefetchRuntime {
  requestFrame(callback: () => void): number;
  cancelFrame(id: number): void;
  setTimer(callback: () => void, milliseconds: number): number;
  clearTimer(id: number): void;
}

const browserHoverRuntime: HoverPrefetchRuntime = {
  requestFrame: (callback) => globalThis.requestAnimationFrame(callback),
  cancelFrame: (id) => globalThis.cancelAnimationFrame(id),
  setTimer: (callback, milliseconds) => window.setTimeout(callback, milliseconds),
  clearTimer: (id) => window.clearTimeout(id),
};

export interface SpatialHoverPrefetchControllerOptions<TPosition> {
  readonly dwellMilliseconds?: number;
  readonly prefetch: (target: ScopeKey, signal: AbortSignal) => Promise<unknown>;
  readonly resolveTarget: (position: TPosition) => ScopeKey | null;
  readonly runtime?: HoverPrefetchRuntime;
}

export class SpatialHoverPrefetchController<TPosition> {
  private readonly dwellMilliseconds: number;
  private readonly prefetch: (target: ScopeKey, signal: AbortSignal) => Promise<unknown>;
  private readonly resolveTarget: (position: TPosition) => ScopeKey | null;
  private readonly runtime: HoverPrefetchRuntime;
  private pendingPosition: { readonly value: TPosition } | null = null;
  private frameId: number | null = null;
  private dwellTimerId: number | null = null;
  private target: ScopeKey | null = null;
  private targetController: AbortController | null = null;
  private disposed = false;

  constructor(options: SpatialHoverPrefetchControllerOptions<TPosition>) {
    this.dwellMilliseconds = options.dwellMilliseconds ?? 200;
    if (
      !Number.isSafeInteger(this.dwellMilliseconds)
      || this.dwellMilliseconds < 0
      || this.dwellMilliseconds > 5_000
    ) {
      throw new RangeError("dwellMilliseconds must be between 0 and 5000");
    }
    this.prefetch = options.prefetch;
    this.resolveTarget = options.resolveTarget;
    this.runtime = options.runtime ?? browserHoverRuntime;
  }

  move(position: TPosition): void {
    if (this.disposed) return;
    this.pendingPosition = { value: position };
    if (this.frameId !== null) return;
    this.frameId = this.runtime.requestFrame(() => this.evaluateFrame());
  }

  leave(): void {
    this.pendingPosition = null;
    if (this.frameId !== null) {
      this.runtime.cancelFrame(this.frameId);
      this.frameId = null;
    }
    this.resetTarget();
  }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    this.leave();
  }

  private evaluateFrame(): void {
    this.frameId = null;
    const pending = this.pendingPosition;
    this.pendingPosition = null;
    if (this.disposed || pending === null) return;
    const nextTarget = this.resolveTarget(pending.value);
    if (nextTarget === this.target) return;
    this.resetTarget();
    if (nextTarget === null) return;

    const controller = new AbortController();
    this.target = nextTarget;
    this.targetController = controller;
    this.dwellTimerId = this.runtime.setTimer(() => {
      this.dwellTimerId = null;
      if (
        this.disposed
        || controller.signal.aborted
        || this.target !== nextTarget
      ) {
        return;
      }
      void this.prefetch(nextTarget, controller.signal).catch(() => undefined);
    }, this.dwellMilliseconds);
  }

  private resetTarget(): void {
    if (this.dwellTimerId !== null) {
      this.runtime.clearTimer(this.dwellTimerId);
      this.dwellTimerId = null;
    }
    this.targetController?.abort(abortError());
    this.targetController = null;
    this.target = null;
  }
}
