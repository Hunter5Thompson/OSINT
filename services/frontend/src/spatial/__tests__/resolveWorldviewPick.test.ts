import { describe, expect, it, vi } from "vitest";

import {
  isSpatialChildPickId,
  resolveWorldviewPick,
  type DrillPickScene,
} from "../cesium/resolveWorldviewPick";

function sceneWith(hits: readonly unknown[]): DrillPickScene<{ x: number; y: number }> {
  return { drillPick: vi.fn(() => hits) };
}

function tagged(odinKind: string, extra: Record<string, unknown> = {}): unknown {
  return { id: { odinKind, ...extra } };
}

describe("resolveWorldviewPick", () => {
  const position = { x: 12, y: 34 };

  it("prioritizes an operational primitive over a spatial child surface", () => {
    const scene = sceneWith([
      tagged("spatial-child", {
        scopeKey: "country:UKR",
        stateRevision: 7,
      }),
      tagged("operational"),
    ]);

    expect(
      resolveWorldviewPick(scene, position, {
        stateRevision: 7,
        spatialEnabled: true,
      }).kind,
    ).toBe("operational");
  });

  it("prioritizes a current child over terrain and ignores a stale generation", () => {
    const current = tagged("spatial-child", {
      scopeKey: "country:odin:kosovo",
      stateRevision: 7,
    });
    const terrain = tagged("terrain");

    expect(
      resolveWorldviewPick(sceneWith([terrain, current]), position, {
        stateRevision: 7,
        spatialEnabled: true,
      }),
    ).toMatchObject({
      kind: "spatial-child",
      id: { scopeKey: "country:odin:kosovo", stateRevision: 7 },
    });
    expect(
      resolveWorldviewPick(sceneWith([current, terrain]), position, {
        stateRevision: 8,
        spatialEnabled: true,
      }).kind,
    ).toBe("terrain");
  });

  it("never accepts the legacy Kosovo XKX alias as a catalog pick ID", () => {
    expect(
      isSpatialChildPickId({
        odinKind: "spatial-child",
        scopeKey: "country:XKX",
        stateRevision: 1,
      }),
    ).toBe(false);
    expect(
      resolveWorldviewPick(
        sceneWith([
          tagged("spatial-child", {
            scopeKey: "country:XKX",
            stateRevision: 1,
          }),
        ]),
        position,
        { stateRevision: 1, spatialEnabled: true },
      ).kind,
    ).toBe("blank");
  });

  it("allows a legacy surface only when the spatial build flag is off", () => {
    const legacy = tagged("legacy-country");

    expect(
      resolveWorldviewPick(sceneWith([legacy]), position, {
        stateRevision: 1,
        spatialEnabled: false,
      }).kind,
    ).toBe("legacy-country");
    expect(
      resolveWorldviewPick(sceneWith([legacy]), position, {
        stateRevision: 1,
        spatialEnabled: true,
      }).kind,
    ).toBe("blank");
  });

  it("returns blank for an empty drill pick", () => {
    expect(
      resolveWorldviewPick(sceneWith([]), position, {
        stateRevision: 1,
        spatialEnabled: true,
      }),
    ).toEqual({ kind: "blank" });
  });

  it("drill-picks once with the fixed cap and reports exact saturation", () => {
    const hits = Array.from({ length: 16 }, () => tagged("terrain"));
    const scene = sceneWith(hits);
    const onSaturated = vi.fn();

    resolveWorldviewPick(scene, position, {
      stateRevision: 1,
      spatialEnabled: true,
      onSaturated,
    });

    expect(scene.drillPick).toHaveBeenCalledTimes(1);
    expect(scene.drillPick).toHaveBeenCalledWith(position, 16);
    expect(onSaturated).toHaveBeenCalledTimes(1);
  });
});
