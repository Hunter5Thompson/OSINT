import type { Viewer } from "cesium";
import { afterEach, describe, expect, it, vi } from "vitest";
import { acquireViewer, disposeParkedViewer, parkViewer, type ViewerResource } from "./viewerLease";

function resource(token = ""): ViewerResource {
  const viewer = { useDefaultRenderLoop: true, clock: { shouldAnimate: true },
    isDestroyed: () => false, scene: { canvas: document.createElement("canvas") } } as unknown as Viewer;
  return { token, viewer, host: document.createElement("div"), dispose: vi.fn() };
}

afterEach(disposeParkedViewer);

describe("bounded viewer ownership across routes", () => {
  it("reuses one paused detached viewer without constructing a new native context", () => {
    const first = resource();
    document.body.append(first.host);
    parkViewer(first, true);
    expect(first.host.isConnected).toBe(false);
    expect(first.viewer.useDefaultRenderLoop).toBe(false);
    expect(first.viewer.clock.shouldAnimate).toBe(false);
    const create = vi.fn(() => resource());
    expect(acquireViewer("", create)).toBe(first);
    expect(create).not.toHaveBeenCalled();
    parkViewer(first, true);
    disposeParkedViewer();
    expect(first.dispose).toHaveBeenCalledOnce();
  });

  it("disposes an incompatible token or failed owner instead of reusing it", () => {
    const first = resource("previous");
    parkViewer(first, true);
    const next = resource("next");
    expect(acquireViewer("next", () => next)).toBe(next);
    expect(first.dispose).toHaveBeenCalledOnce();
    parkViewer(next, false);
    expect(next.dispose).toHaveBeenCalledOnce();
    const replacement = resource("next");
    expect(acquireViewer("next", () => replacement)).toBe(replacement);
    parkViewer(replacement, true);
  });

  it("does not reuse a context lost while its route was inactive", () => {
    const first = resource();
    parkViewer(first, true);
    first.viewer.scene.canvas.dispatchEvent(new Event("webglcontextlost"));
    const replacement = resource();
    expect(acquireViewer("", () => replacement)).toBe(replacement);
    expect(first.dispose).toHaveBeenCalledOnce();
    parkViewer(replacement, true);
  });
});
