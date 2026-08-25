import { describe, it, expect, beforeEach } from "vitest";
import {
  installRenderGovernor, uninstallRenderGovernor, holdContinuousRender,
  releaseContinuousRender, governorRequestRender, getRenderGovernorDiagnostics,
  type GovernedViewer,
} from "../renderGovernor";

interface FakeScene {
  requestRenderMode: boolean;
  maximumRenderTimeChange: number;
  renderCount: number;
  requestRender(): void;
}

function fakeViewer(): GovernedViewer & { scene: FakeScene } {
  const scene: FakeScene = {
    requestRenderMode: false,
    maximumRenderTimeChange: 0,
    renderCount: 0,
    requestRender() { this.renderCount++; },
  };
  return { scene };
}

describe("renderGovernor", () => {
  beforeEach(() => { uninstallRenderGovernor(); });

  it("ENTERS IDLE when installed with no holds", () => {
    // The single most important assertion here. requestRenderMode TRUE means
    // EXPLICIT rendering — Cesium stops repainting. So idle ⇒ true, which is
    // the inverse of "holds are active". Getting this backwards inverts the
    // whole feature while every other test still passes.
    const v = fakeViewer();
    installRenderGovernor(v);
    expect(v.scene.requestRenderMode).toBe(true);
    expect(getRenderGovernorDiagnostics().mode).toBe("idle");
  });

  it("STAYS CONTINUOUS when installed while a hold is already registered", () => {
    holdContinuousRender("early");
    const v = fakeViewer();
    installRenderGovernor(v);
    expect(v.scene.requestRenderMode).toBe(false);
    expect(getRenderGovernorDiagnostics().mode).toBe("continuous");
  });

  it("stops Cesium re-rendering on simulation-time deltas", () => {
    const v = fakeViewer();
    installRenderGovernor(v);
    expect(v.scene.maximumRenderTimeChange).toBe(Number.POSITIVE_INFINITY);
  });

  it("renders one settling frame entering idle, none entering continuous", () => {
    const a = fakeViewer();
    installRenderGovernor(a);
    expect(a.scene.renderCount).toBe(1);
    uninstallRenderGovernor();
    holdContinuousRender("early");
    const b = fakeViewer();
    installRenderGovernor(b);
    expect(b.scene.renderCount).toBe(0);
  });

  it("switches to continuous on hold and back to idle on release", () => {
    const v = fakeViewer();
    installRenderGovernor(v);
    holdContinuousRender("flights");
    expect(v.scene.requestRenderMode).toBe(false);
    releaseContinuousRender("flights");
    expect(v.scene.requestRenderMode).toBe(true);
  });

  it("is idempotent per owner so double-hold cannot corrupt the mode", () => {
    const v = fakeViewer();
    installRenderGovernor(v);
    holdContinuousRender("flights");
    holdContinuousRender("flights");
    releaseContinuousRender("flights");
    expect(v.scene.requestRenderMode).toBe(true);
    expect(getRenderGovernorDiagnostics().holds).toEqual([]);
  });

  it("tolerates releasing a hold never taken", () => {
    const v = fakeViewer();
    installRenderGovernor(v);
    expect(() => releaseContinuousRender("never-held")).not.toThrow();
    expect(v.scene.requestRenderMode).toBe(true);
  });

  it("stays continuous until the last of several holds is released", () => {
    const v = fakeViewer();
    installRenderGovernor(v);
    holdContinuousRender("firms-pulse");
    holdContinuousRender("spotlight-fade");
    releaseContinuousRender("firms-pulse");
    expect(v.scene.requestRenderMode).toBe(false);
    releaseContinuousRender("spotlight-fade");
    expect(v.scene.requestRenderMode).toBe(true);
  });

  it("records diagnostics for idle-mode requests only, forwards always", () => {
    const v = fakeViewer();
    installRenderGovernor(v);
    governorRequestRender("layer-visibility");
    holdContinuousRender("flights");
    const before = v.scene.renderCount;
    governorRequestRender("while-continuous");
    expect(v.scene.renderCount).toBe(before + 1);
    expect(getRenderGovernorDiagnostics().recentRequests.map((e) => e.reason))
      .toEqual(["layer-visibility"]);
  });

  it("is a safe no-op before install", () => {
    expect(() => governorRequestRender("no-viewer")).not.toThrow();
    expect(() => holdContinuousRender("x")).not.toThrow();
    expect(getRenderGovernorDiagnostics().installed).toBe(false);
  });

  it("drops all holds on uninstall so a new viewer starts clean", () => {
    const a = fakeViewer();
    installRenderGovernor(a);
    holdContinuousRender("flights");
    uninstallRenderGovernor();
    const b = fakeViewer();
    installRenderGovernor(b);
    expect(b.scene.requestRenderMode).toBe(true);
  });
});
