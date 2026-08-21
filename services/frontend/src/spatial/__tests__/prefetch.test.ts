import { afterEach, describe, expect, it, vi } from "vitest";

import { parseScopeKeyCandidate, type ScopeKey } from "../contracts";
import {
  BoundedPrefetchScheduler,
  SpatialHoverPrefetchController,
  allowsSpatialHoverPrefetch,
  type HoverPrefetchRuntime,
} from "../prefetch";

interface Deferred {
  readonly promise: Promise<void>;
  resolve(): void;
}

function deferred(): Deferred {
  let resolvePromise: () => void = () => undefined;
  const promise = new Promise<void>((resolve) => {
    resolvePromise = resolve;
  });
  return { promise, resolve: resolvePromise };
}

function abortable(gate: Deferred, signal: AbortSignal): Promise<void> {
  if (signal.aborted) return Promise.reject(new DOMException("Aborted", "AbortError"));
  return new Promise<void>((resolve, reject) => {
    const onAbort = () => reject(new DOMException("Aborted", "AbortError"));
    signal.addEventListener("abort", onAbort, { once: true });
    gate.promise.then(resolve).finally(() => signal.removeEventListener("abort", onAbort));
  });
}

class FakeHoverRuntime implements HoverPrefetchRuntime {
  private nextFrameId = 0;
  private readonly frames = new Map<number, () => void>();

  requestFrame(callback: () => void): number {
    const id = ++this.nextFrameId;
    this.frames.set(id, callback);
    return id;
  }

  cancelFrame(id: number): void {
    this.frames.delete(id);
  }

  setTimer(callback: () => void, milliseconds: number): number {
    return window.setTimeout(callback, milliseconds);
  }

  clearTimer(id: number): void {
    window.clearTimeout(id);
  }

  flushFrame(): void {
    const callbacks = [...this.frames.values()];
    this.frames.clear();
    callbacks.forEach((callback) => callback());
  }
}

afterEach(() => {
  vi.useRealTimers();
});

describe("BoundedPrefetchScheduler", () => {
  it("runs at most two jobs and replaces the stale queued hover", async () => {
    const scheduler = new BoundedPrefetchScheduler({ maxConcurrency: 2 });
    const gates = [deferred(), deferred(), deferred(), deferred()];
    const started: number[] = [];
    let active = 0;
    let highWater = 0;
    const schedule = (index: number) => scheduler.schedule(async (signal) => {
      started.push(index);
      active += 1;
      highWater = Math.max(highWater, active);
      try {
        await abortable(gates[index]!, signal);
      } finally {
        active -= 1;
      }
    });

    const first = schedule(0);
    const second = schedule(1);
    const replaced = schedule(2);
    const latest = schedule(3);

    await expect(replaced).resolves.toEqual({ outcome: "cancelled" });
    expect(started).toEqual([0, 1]);
    expect(scheduler.diagnostics()).toMatchObject({
      active: 2,
      queued: 1,
      highWaterActive: 2,
      replaced: 1,
    });

    gates[0]?.resolve();
    await vi.waitFor(() => expect(started).toEqual([0, 1, 3]));
    gates[1]?.resolve();
    gates[3]?.resolve();

    await expect(first).resolves.toEqual({ outcome: "completed" });
    await expect(second).resolves.toEqual({ outcome: "completed" });
    await expect(latest).resolves.toEqual({ outcome: "completed" });
    expect(highWater).toBe(2);
    expect(scheduler.diagnostics()).toMatchObject({ active: 0, queued: 0 });
  });

  it("cancels only its consumer after a job has started", async () => {
    const scheduler = new BoundedPrefetchScheduler({ maxConcurrency: 2 });
    const caller = new AbortController();
    const gate = deferred();
    const observedSignals: AbortSignal[] = [];
    const scheduled = scheduler.schedule(async (signal) => {
      observedSignals.push(signal);
      await abortable(gate, signal);
    }, caller.signal);

    await vi.waitFor(() => expect(observedSignals).toHaveLength(1));
    caller.abort();

    await expect(scheduled).resolves.toEqual({ outcome: "cancelled" });
    expect(observedSignals[0]?.aborted).toBe(true);
    expect(scheduler.diagnostics()).toMatchObject({ active: 0, cancelled: 1 });
  });

  it("does not invoke a runner cancelled before its start microtask", async () => {
    const scheduler = new BoundedPrefetchScheduler({ maxConcurrency: 2 });
    const caller = new AbortController();
    const run = vi.fn(async () => undefined);

    const scheduled = scheduler.schedule(run, caller.signal);
    caller.abort();

    await expect(scheduled).resolves.toEqual({ outcome: "cancelled" });
    expect(run).not.toHaveBeenCalled();
    expect(scheduler.diagnostics()).toMatchObject({
      active: 0,
      cancelled: 1,
      completed: 0,
    });
  });
});

describe("SpatialHoverPrefetchController", () => {
  const UKRAINE = parseScopeKeyCandidate("country:UKR");
  const POLAND = parseScopeKeyCandidate("country:POL");

  it("samples the latest move once per frame and waits for a stable 200 ms dwell", async () => {
    vi.useFakeTimers();
    const runtime = new FakeHoverRuntime();
    const resolved: number[] = [];
    const prefetched: ScopeKey[] = [];
    const controller = new SpatialHoverPrefetchController<number>({
      runtime,
      resolveTarget: (position) => {
        resolved.push(position);
        return position === 2 ? UKRAINE : null;
      },
      prefetch: async (target) => {
        prefetched.push(target);
      },
    });

    controller.move(1);
    controller.move(2);
    expect(resolved).toEqual([]);
    runtime.flushFrame();
    expect(resolved).toEqual([2]);

    await vi.advanceTimersByTimeAsync(199);
    expect(prefetched).toEqual([]);
    await vi.advanceTimersByTimeAsync(1);
    expect(prefetched).toEqual([UKRAINE]);
  });

  it("cancels before or after start when the pointer leaves or changes target", async () => {
    vi.useFakeTimers();
    const runtime = new FakeHoverRuntime();
    const calls: Array<{ readonly target: ScopeKey; readonly signal: AbortSignal }> = [];
    const controller = new SpatialHoverPrefetchController<ScopeKey | null>({
      runtime,
      resolveTarget: (target) => target,
      prefetch: async (target, signal) => {
        calls.push({ target, signal });
      },
    });

    controller.move(UKRAINE);
    runtime.flushFrame();
    controller.leave();
    await vi.advanceTimersByTimeAsync(200);
    expect(calls).toEqual([]);

    controller.move(UKRAINE);
    runtime.flushFrame();
    await vi.advanceTimersByTimeAsync(200);
    expect(calls).toHaveLength(1);
    expect(calls[0]?.signal.aborted).toBe(false);

    controller.move(POLAND);
    runtime.flushFrame();
    expect(calls[0]?.signal.aborted).toBe(true);
    await vi.advanceTimersByTimeAsync(200);
    expect(calls.map((call) => call.target)).toEqual([UKRAINE, POLAND]);
    controller.leave();
    expect(calls[1]?.signal.aborted).toBe(true);
  });
});

describe("spatial hover capability policy", () => {
  it.each([
    [{ hover: true, coarsePointer: false, saveData: false }, true],
    [{ hover: false, coarsePointer: true, saveData: false }, false],
    [{ hover: true, coarsePointer: true, saveData: false }, false],
    [{ hover: true, coarsePointer: false, saveData: true }, false],
  ])("evaluates %o without entering semantic state", (capabilities, expected) => {
    expect(allowsSpatialHoverPrefetch(capabilities)).toBe(expected);
  });
});
