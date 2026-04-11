/**
 * Vitest setup file.
 *
 * Shims `globalThis.jest` with a minimal adapter over `vi` so that
 * `@testing-library/dom`'s `waitFor` detects vitest fake timers (it only
 * checks for Jest) and advances them via `jest.advanceTimersByTime`.
 *
 * Without this shim, `waitFor` + `vi.useFakeTimers()` hangs: testing-library
 * sees no fake-timer environment, falls back to real-setTimeout polling, but
 * React state updates don't flush inside the polled callback on React 19 +
 * jsdom. See https://github.com/testing-library/react-testing-library/issues/1197
 */
import { afterEach, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";

// With `globals: false` in vite.config.ts, @testing-library/react's automatic
// cleanup (which hooks into the global `afterEach`) does not run. Register it
// explicitly so DOM nodes from previous tests don't leak into the next test.
afterEach(() => {
  cleanup();
});

// jsdom doesn't implement HTMLCanvasElement.getContext('2d'). Install a minimal
// no-op stub so layer code (and tests that assert the context is non-null) can
// exercise canvas drawing paths without bundling the heavy `canvas` package.
const canvasProto = globalThis.HTMLCanvasElement?.prototype;
if (canvasProto && !("__odinCanvasStubbed" in canvasProto)) {
  const noop = () => {};
  const stub2d = {
    canvas: null as HTMLCanvasElement | null,
    fillStyle: "",
    strokeStyle: "",
    lineWidth: 1,
    globalAlpha: 1,
    translate: noop,
    scale: noop,
    rotate: noop,
    save: noop,
    restore: noop,
    beginPath: noop,
    closePath: noop,
    moveTo: noop,
    lineTo: noop,
    arc: noop,
    rect: noop,
    fill: noop,
    stroke: noop,
    clip: noop,
    fillRect: noop,
    clearRect: noop,
    strokeRect: noop,
    drawImage: noop,
    createLinearGradient: () => ({ addColorStop: noop }),
    createRadialGradient: () => ({ addColorStop: noop }),
    getImageData: () => ({ data: new Uint8ClampedArray(4) }),
    putImageData: noop,
    measureText: () => ({ width: 0 }),
    fillText: noop,
    strokeText: noop,
  };
  (canvasProto as unknown as { getContext: (kind: string) => unknown }).getContext = function getContext(
    kind: string,
  ) {
    if (kind === "2d") {
      return { ...stub2d, canvas: this as unknown as HTMLCanvasElement };
    }
    return null;
  };
  (canvasProto as unknown as { __odinCanvasStubbed: boolean }).__odinCanvasStubbed = true;
}

// Cesium's Material introspection references the DOM `ImageBitmap` type even
// when no image uniforms are used. jsdom doesn't define it, so provide a stub
// constructor to satisfy the `instanceof` / typeof checks.
if (typeof (globalThis as { ImageBitmap?: unknown }).ImageBitmap === "undefined") {
  (globalThis as { ImageBitmap: unknown }).ImageBitmap = class {};
}
if (typeof (globalThis as { OffscreenCanvas?: unknown }).OffscreenCanvas === "undefined") {
  (globalThis as { OffscreenCanvas: unknown }).OffscreenCanvas = class {};
}

const jestShim = {
  advanceTimersByTime: (ms: number) => vi.advanceTimersByTime(ms),
  runAllTicks: () => vi.runAllTicks(),
  runAllTimers: () => vi.runAllTimers(),
  runOnlyPendingTimers: () => vi.runOnlyPendingTimers(),
  useFakeTimers: (...args: unknown[]) =>
    (vi.useFakeTimers as (...a: unknown[]) => unknown)(...args),
  useRealTimers: () => vi.useRealTimers(),
};

(globalThis as unknown as { jest: typeof jestShim }).jest = jestShim;
