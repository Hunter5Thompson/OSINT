import { expect, it, vi } from "vitest";
import { watchViewerHealth } from "./viewerHealth";

function fixture() {
  const listeners = new Set<() => void>();
  const viewer = {
    canvas: document.createElement("canvas"), useDefaultRenderLoop: true,
    isDestroyed: () => false,
    scene: { renderError: { addEventListener(fn: () => void) {
      listeners.add(fn); return () => { listeners.delete(fn); };
    } } },
  };
  return { viewer, listeners };
}

it("stops the loop on context loss, permits restoration and reports one terminal failure", () => {
  const { viewer, listeners } = fixture(); const report = vi.fn();
  const dispose = watchViewerHealth(viewer, report);
  const event = new Event("webglcontextlost", { cancelable: true });
  viewer.canvas.dispatchEvent(event);
  expect(event.defaultPrevented).toBe(true);
  expect(viewer.useDefaultRenderLoop).toBe(false);
  for (const listener of listeners) listener();
  expect(report).toHaveBeenCalledExactlyOnceWith("context-lost");
  dispose();
});

it("reports unexpected render errors and removes both subscriptions on teardown", () => {
  const { viewer, listeners } = fixture(); const report = vi.fn();
  const dispose = watchViewerHealth(viewer, report);
  const late = [...listeners][0]!; late();
  expect(report).toHaveBeenCalledExactlyOnceWith("render-error");
  expect(viewer.useDefaultRenderLoop).toBe(false);
  dispose(); dispose();
  expect(listeners.size).toBe(0);
  viewer.useDefaultRenderLoop = true;
  late(); viewer.canvas.dispatchEvent(new Event("webglcontextlost"));
  expect(report).toHaveBeenCalledOnce();
  expect(viewer.useDefaultRenderLoop).toBe(true);
});

it("does not touch an already destroyed viewer", () => {
  const { viewer, listeners } = fixture(); viewer.isDestroyed = () => true;
  const report = vi.fn(); const dispose = watchViewerHealth(viewer, report);
  for (const listener of listeners) listener();
  viewer.canvas.dispatchEvent(new Event("webglcontextlost"));
  expect(report).not.toHaveBeenCalled(); dispose();
});
