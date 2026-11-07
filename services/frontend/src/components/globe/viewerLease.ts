import type { Viewer } from "cesium";

export interface ViewerResource {
  token: string;
  viewer: Viewer;
  host: HTMLDivElement;
  dispose: () => void;
}

// Keep at most one detached, paused native context for the application's map.
// Repeated route changes otherwise allocate browser-side WebGL state even after
// Cesium's JS/terrain caches have been released. This bounds normal navigation
// to one viewer; it does not claim to repair Chromium's context disposal.
let parked: { resource: ViewerResource; lost: boolean; unwatch: () => void } | null = null;

export function disposeParkedViewer(): void {
  const previous = parked;
  parked = null;
  if (previous) {
    previous.unwatch();
    previous.resource.dispose();
  }
}

export function acquireViewer(token: string, create: () => ViewerResource): ViewerResource {
  if (parked && parked.resource.token === token && !parked.lost && !parked.resource.viewer.isDestroyed()) {
    const previous = parked;
    parked = null;
    previous.unwatch();
    return previous.resource;
  }
  disposeParkedViewer();
  return create();
}

export function parkViewer(resource: ViewerResource, reusable: boolean): void {
  resource.host.remove();
  if (!resource.viewer.isDestroyed()) {
    resource.viewer.useDefaultRenderLoop = false;
    resource.viewer.clock.shouldAnimate = false;
  }
  disposeParkedViewer();
  if (!reusable || resource.viewer.isDestroyed()) {
    resource.dispose();
    return;
  }
  const idle = { resource, lost: false, unwatch: () => {} };
  const lost = () => { idle.lost = true; };
  resource.viewer.scene.canvas?.addEventListener("webglcontextlost", lost);
  idle.unwatch = () => resource.viewer.scene.canvas?.removeEventListener("webglcontextlost", lost);
  parked = idle;
}
