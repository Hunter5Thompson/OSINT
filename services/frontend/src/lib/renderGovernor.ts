/**
 * Adapted from God's Eye View, commit 880a672b5e16ad3e41d318801d3a5203f9201923
 * Copyright (c) 2026 Bilawal Sidhu. MIT License — full text in
 * LICENSES/gods-eye-view-MIT.txt. See THIRD_PARTY_NOTICES.md.
 */

/**
 * Idle render governor.
 *
 * ⚠ POLARITY: `requestRenderMode === true` means EXPLICIT rendering — Cesium
 * stops repainting on its own. So idle ⇒ true, continuous ⇒ false, the inverse
 * of "holds are active". `applyMode()` is the ONLY place that writes the flag.
 *
 * Holds are identity-keyed (a Set of owner ids), NOT a counter — a module that
 * double-holds or double-releases cannot corrupt the mode. That is what makes
 * this safe under React StrictMode's double-invoked effects.
 */

export interface GovernedScene {
  requestRenderMode: boolean;
  maximumRenderTimeChange: number;
  requestRender(): void;
}
export interface GovernedViewer { readonly scene: GovernedScene }
export interface RenderGovernorRequest { readonly reason: string; readonly at: number }
export interface RenderGovernorDiagnostics {
  readonly installed: boolean;
  readonly mode: "continuous" | "idle";
  readonly holds: string[];
  readonly recentRequests: RenderGovernorRequest[];
}

const RECENT_REQUEST_CAP = 16;

let viewerRef: GovernedViewer | null = null;
let installed = false;
const holds = new Set<string>();
const recentRequests: RenderGovernorRequest[] = [];

const isIdle = (): boolean => holds.size === 0;

/** `force` skips the no-op guard so install always lands flag + settling frame. */
function applyMode(force = false): void {
  if (!installed || !viewerRef) return;
  const scene = viewerRef.scene;
  const idle = isIdle();
  if (!force && scene.requestRenderMode === idle) return;
  scene.requestRenderMode = idle;
  // Entering idle: one settling frame so the last continuous frame's mutations
  // reach the screen before the loop stops.
  if (idle) scene.requestRender();
}

export function installRenderGovernor(viewer: GovernedViewer): void {
  viewerRef = viewer;
  installed = true;
  // Never let Cesium re-render on simulation-time deltas behind our back.
  viewer.scene.maximumRenderTimeChange = Number.POSITIVE_INFINITY;
  applyMode(true);
}

export function uninstallRenderGovernor(): void {
  viewerRef = null;
  installed = false;
  holds.clear();
  recentRequests.length = 0;
}

export function holdContinuousRender(ownerId: string): void {
  if (!ownerId) return;
  holds.add(ownerId);
  applyMode();
}

export function releaseContinuousRender(ownerId: string): void {
  if (!ownerId) return;
  holds.delete(ownerId);
  applyMode();
}

/**
 * One-shot request for a discrete scene mutation. Always forwards — in
 * continuous mode that is a harmless flag set, and forwarding closes the
 * request-then-last-release race. Only idle requests are recorded.
 */
export function governorRequestRender(reason = "unspecified"): void {
  if (!installed || !viewerRef) return;
  if (isIdle()) {
    recentRequests.push({ reason, at: Date.now() });
    if (recentRequests.length > RECENT_REQUEST_CAP) recentRequests.shift();
  }
  viewerRef.scene.requestRender();
}

export function getRenderGovernorDiagnostics(): RenderGovernorDiagnostics {
  return {
    installed,
    mode: isIdle() ? "idle" : "continuous",
    holds: [...holds].sort(),
    recentRequests: [...recentRequests],
  };
}
