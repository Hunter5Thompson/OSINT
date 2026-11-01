import { act, render, screen } from "@testing-library/react";
import type { Viewer } from "cesium";
import { afterEach, expect, it, vi } from "vitest";
import { PerformanceGuard, usePerformance } from "./PerformanceGuard";

function event() {
  const listeners = new Set<() => void>();
  return { listeners, addEventListener(callback: () => void) {
    listeners.add(callback); return () => { listeners.delete(callback); };
  }, fire() { listeners.forEach(fn => fn()); } };
}
function Output() {
  const state = usePerformance();
  return <output>{state.fps}/{state.degradation}</output>;
}
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });

it("counts scene events and detaches all subscriptions when the viewer is replaced", () => {
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "performance"] });
  vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
  const postRender = event(), moveStart = event(), moveEnd = event();
  const viewer = { isDestroyed: () => false, scene: { postRender, requestRenderMode: false },
    camera: { moveStart, moveEnd } } as unknown as Viewer;
  const view = render(<PerformanceGuard viewer={viewer}><Output /></PerformanceGuard>);
  act(() => { for (let i = 0; i < 12; i++) postRender.fire(); vi.advanceTimersByTime(1000); });
  expect(screen.getByRole("status")).toHaveTextContent("12/0");
  act(() => { vi.advanceTimersByTime(2000); });
  expect(screen.getByRole("status")).toHaveTextContent("0/1");
  view.rerender(<PerformanceGuard viewer={null}><Output /></PerformanceGuard>);
  expect(postRender.listeners.size).toBe(0);
  expect(moveStart.listeners.size).toBe(0);
  expect(moveEnd.listeners.size).toBe(0);
  expect(vi.getTimerCount()).toBe(0);
});
