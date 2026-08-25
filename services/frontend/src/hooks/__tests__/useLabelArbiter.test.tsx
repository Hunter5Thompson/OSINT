import { act, renderHook } from "@testing-library/react";
import * as Cesium from "cesium";
import { describe, expect, it } from "vitest";

import { labelBudgetFor } from "../../lib/labelBudget";
import {
  useLabelArbiter,
  type LabelArbiterApi,
  type LabelArbiterViewer,
  type LabelProjector,
  type LabelRequest,
} from "../useLabelArbiter";

const DENSITY = 50;
const GLOBE_HEIGHT_M = 15_000_000;
const STREET_HEIGHT_M = 10_000;

const flush = async (): Promise<void> => {
  await act(async () => {
    await Promise.resolve();
  });
};

function overflowCount(): number {
  return labelBudgetFor(STREET_HEIGHT_M, DENSITY) + 10;
}

function spreadProjector(position: Cesium.Cartesian3): { x: number; y: number } {
  return { x: position.x * 200, y: 40 };
}

function makeRequests(prefix: string, count: number, originX = 0): LabelRequest[] {
  const requests: LabelRequest[] = [];
  for (let i = 0; i < count; i++) {
    requests.push({
      key: `${prefix}-${i}`,
      position: new Cesium.Cartesian3(originX + i, 0, 0),
      text: `${prefix}-${i}`,
      fontSizePx: 12,
      pixelOffsetY: 0,
      priority: count - i,
    });
  }
  return requests;
}

function keysOf(requests: readonly LabelRequest[]): string[] {
  return requests.map((request) => request.key);
}

function countSelected(api: LabelArbiterApi, keys: readonly string[]): number {
  let n = 0;
  for (const key of keys) {
    if (api.isSelected(key)) n += 1;
  }
  return n;
}

function createFakeViewer(initialHeight = GLOBE_HEIGHT_M): {
  viewer: LabelArbiterViewer;
  setHeight: (height: number) => void;
  fireMoveEnd: () => void;
  listenerCount: () => number;
} {
  const listeners: Array<() => void> = [];
  const positionCartographic = { height: initialHeight };
  const viewer: LabelArbiterViewer = {
    isDestroyed: () => false,
    scene: {
      canvas: { clientWidth: 800, clientHeight: 600 },
    },
    camera: {
      positionCartographic,
      moveEnd: {
        addEventListener(fn: () => void): () => void {
          listeners.push(fn);
          return () => {
            const idx = listeners.indexOf(fn);
            if (idx >= 0) listeners.splice(idx, 1);
          };
        },
      },
    },
  };
  return {
    viewer,
    setHeight(height: number) {
      positionCartographic.height = height;
    },
    fireMoveEnd() {
      for (const fn of [...listeners]) fn();
    },
    listenerCount() {
      return listeners.length;
    },
  };
}

describe("useLabelArbiter", () => {
  it("null viewer: isSelected is false and submit/remove do not throw", () => {
    const { result } = renderHook(() => useLabelArbiter(null, DENSITY, spreadProjector));
    expect(result.current.isSelected("earthquakes-0")).toBe(false);
    expect(() => result.current.submit("earthquakes", makeRequests("earthquakes", 3))).not.toThrow();
    expect(() => result.current.remove("earthquakes")).not.toThrow();
  });

  it("selection count matches labelBudgetFor at current height", async () => {
    const harness = createFakeViewer();
    const requests = makeRequests("earthquakes", overflowCount());
    const { result } = renderHook(() =>
      useLabelArbiter(harness.viewer, DENSITY, spreadProjector),
    );

    act(() => {
      result.current.submit("earthquakes", requests);
    });
    await flush();

    expect(countSelected(result.current, keysOf(requests))).toBe(
      labelBudgetFor(GLOBE_HEIGHT_M, DENSITY),
    );
  });

  it("two submits in the same tick coalesce to one version bump", async () => {
    const harness = createFakeViewer();
    const { result } = renderHook(() =>
      useLabelArbiter(harness.viewer, DENSITY, spreadProjector),
    );
    const before = result.current.version;

    act(() => {
      result.current.submit("earthquakes", makeRequests("earthquakes", overflowCount()));
      result.current.submit("gdacs", makeRequests("gdacs", overflowCount(), 1_000));
    });
    await flush();

    expect(result.current.version).toBe(before + 1);
  });

  it("two layers share one budget and both are represented", async () => {
    const harness = createFakeViewer();
    const earthquakes = makeRequests("earthquakes", overflowCount());
    const gdacs = makeRequests("gdacs", overflowCount(), 1_000);
    const { result } = renderHook(() =>
      useLabelArbiter(harness.viewer, DENSITY, spreadProjector),
    );

    act(() => {
      result.current.submit("earthquakes", earthquakes);
      result.current.submit("gdacs", gdacs);
    });
    await flush();

    const eqCount = countSelected(result.current, keysOf(earthquakes));
    const gdacsCount = countSelected(result.current, keysOf(gdacs));
    expect(eqCount).toBeGreaterThan(0);
    expect(gdacsCount).toBeGreaterThan(0);
    expect(eqCount + gdacsCount).toBe(labelBudgetFor(GLOBE_HEIGHT_M, DENSITY));
  });

  it("remove frees quota so the remaining layer gets the full budget", async () => {
    const harness = createFakeViewer();
    const earthquakes = makeRequests("earthquakes", overflowCount());
    const gdacs = makeRequests("gdacs", overflowCount(), 1_000);
    const { result } = renderHook(() =>
      useLabelArbiter(harness.viewer, DENSITY, spreadProjector),
    );

    act(() => {
      result.current.submit("earthquakes", earthquakes);
      result.current.submit("gdacs", gdacs);
    });
    await flush();

    act(() => {
      result.current.remove("gdacs");
    });
    await flush();

    expect(countSelected(result.current, keysOf(gdacs))).toBe(0);
    expect(countSelected(result.current, keysOf(earthquakes))).toBe(
      labelBudgetFor(GLOBE_HEIGHT_M, DENSITY),
    );
  });

  it("moveEnd after height change re-solves against the new budget", async () => {
    const harness = createFakeViewer();
    const requests = makeRequests("earthquakes", overflowCount());
    const { result } = renderHook(() =>
      useLabelArbiter(harness.viewer, DENSITY, spreadProjector),
    );

    act(() => {
      result.current.submit("earthquakes", requests);
    });
    await flush();
    expect(countSelected(result.current, keysOf(requests))).toBe(
      labelBudgetFor(GLOBE_HEIGHT_M, DENSITY),
    );

    act(() => {
      harness.setHeight(STREET_HEIGHT_M);
      harness.fireMoveEnd();
    });
    await flush();

    expect(countSelected(result.current, keysOf(requests))).toBe(
      labelBudgetFor(STREET_HEIGHT_M, DENSITY),
    );
  });

  it("re-submitting an identical set does not bump version", async () => {
    const harness = createFakeViewer();
    const requests = makeRequests("earthquakes", overflowCount());
    const { result } = renderHook(() =>
      useLabelArbiter(harness.viewer, DENSITY, spreadProjector),
    );

    act(() => {
      result.current.submit("earthquakes", requests);
    });
    await flush();
    const version = result.current.version;

    act(() => {
      result.current.submit("earthquakes", requests);
    });
    await flush();

    expect(result.current.version).toBe(version);
  });

  it("unmount removes the moveEnd listener", () => {
    const harness = createFakeViewer();
    const { unmount } = renderHook(() =>
      useLabelArbiter(harness.viewer, DENSITY, spreadProjector),
    );
    expect(harness.listenerCount()).toBe(1);
    unmount();
    expect(harness.listenerCount()).toBe(0);
  });

  it("projector returning null does not throw and those keys are not selected", async () => {
    const harness = createFakeViewer();
    const requests = makeRequests("earthquakes", 5);
    const projector: LabelProjector = () => null;
    const { result } = renderHook(() => useLabelArbiter(harness.viewer, DENSITY, projector));

    expect(() => {
      act(() => {
        result.current.submit("earthquakes", requests);
      });
    }).not.toThrow();
    await flush();

    expect(countSelected(result.current, keysOf(requests))).toBe(0);
  });

  it("pixelOffsetY shifts the collision rect so stacked anchors do not collide", async () => {
    const harness = createFakeViewer();
    const position = new Cesium.Cartesian3(0, 0, 0);
    const projector: LabelProjector = () => ({ x: 100, y: 100 });
    const requests: LabelRequest[] = [
      {
        key: "low",
        position,
        text: "LOW",
        fontSizePx: 12,
        pixelOffsetY: 0,
        priority: 10,
      },
      {
        key: "high",
        position,
        text: "HIGH",
        fontSizePx: 12,
        pixelOffsetY: 200,
        priority: 9,
      },
    ];
    const { result } = renderHook(() => useLabelArbiter(harness.viewer, DENSITY, projector));

    act(() => {
      result.current.submit("earthquakes", requests);
    });
    await flush();

    expect(result.current.isSelected("low")).toBe(true);
    expect(result.current.isSelected("high")).toBe(true);
  });

  it("DROPS off-canvas candidates so they cannot consume quota", async () => {
    const harness = createFakeViewer();
    const keyByPosition = new WeakMap<Cesium.Cartesian3, string>();
    const requests: LabelRequest[] = [];
    for (let i = 0; i < 6; i++) {
      const position = new Cesium.Cartesian3(i, 0, 0);
      const key = `gdacs-${i}`;
      keyByPosition.set(position, key);
      requests.push({
        key,
        position,
        text: key,
        fontSizePx: 12,
        pixelOffsetY: 0,
        priority: 10 - i,
      });
    }
    const offCanvas = new Set(["gdacs-0", "gdacs-1", "gdacs-2"]);
    const projector: LabelProjector = (position) => {
      const key = keyByPosition.get(position);
      if (key !== undefined && offCanvas.has(key)) return null;
      return { x: position.x * 200, y: 40 };
    };
    const { result } = renderHook(() => useLabelArbiter(harness.viewer, DENSITY, projector));

    act(() => {
      result.current.submit("gdacs", requests);
    });
    await flush();

    expect(result.current.isSelected("gdacs-0")).toBe(false);
    expect(result.current.isSelected("gdacs-1")).toBe(false);
    expect(result.current.isSelected("gdacs-2")).toBe(false);
    expect(result.current.isSelected("gdacs-3")).toBe(true);
    expect(result.current.isSelected("gdacs-4")).toBe(true);
    expect(result.current.isSelected("gdacs-5")).toBe(true);
  });
});
