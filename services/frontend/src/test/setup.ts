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
import { vi } from "vitest";

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
