import { describe, it, expect } from "vitest";
import {
  ALLOCATION_STRATEGIES,
  LAYER_LABEL_WEIGHTS,
  allocateLayerQuotas,
  normalizeAllocationStrategy,
} from "../labelQuota";

function sumQuotas(q: Map<string, number>): number {
  return [...q.values()].reduce((a, b) => a + b, 0);
}

describe("normalizeAllocationStrategy", () => {
  it('maps "weighted" to WEIGHTED (case-insensitive)', () => {
    expect(normalizeAllocationStrategy("weighted")).toBe("WEIGHTED");
  });

  it('maps "ELASTIC" to ELASTIC', () => {
    expect(normalizeAllocationStrategy("ELASTIC")).toBe("ELASTIC");
  });

  it("defaults undefined to ELASTIC", () => {
    expect(normalizeAllocationStrategy(undefined)).toBe("ELASTIC");
  });

  it("defaults unknown input to ELASTIC", () => {
    expect(normalizeAllocationStrategy("nonsense")).toBe("ELASTIC");
  });

  it("uses explicit fallback for unknown input", () => {
    expect(normalizeAllocationStrategy("nonsense", "WEIGHTED")).toBe("WEIGHTED");
  });
});

describe("ALLOCATION_STRATEGIES", () => {
  it("is exactly ELASTIC then WEIGHTED", () => {
    expect(ALLOCATION_STRATEGIES).toEqual(["ELASTIC", "WEIGHTED"]);
  });
});

describe.each(ALLOCATION_STRATEGIES)("allocateLayerQuotas (%s) invariants", (strategy) => {
  it("never exceeds capacity", () => {
    const q = allocateLayerQuotas(
      new Map([
        ["a", 100],
        ["b", 100],
        ["c", 100],
      ]),
      20,
      strategy,
    );
    expect(sumQuotas(q)).toBe(20);
  });

  it("never exceeds a layer's demand", () => {
    const q = allocateLayerQuotas(
      new Map([
        ["a", 2],
        ["b", 100],
      ]),
      40,
      strategy,
    );
    expect(q.get("a") ?? 0).toBeLessThanOrEqual(2);
  });

  it("is work-conserving when one layer saturates", () => {
    const q = allocateLayerQuotas(
      new Map([
        ["a", 2],
        ["b", 100],
      ]),
      40,
      strategy,
    );
    expect(sumQuotas(q)).toBe(40);
    expect(q.get("b")).toBe(38);
  });

  it("clamps capacity to total demand", () => {
    const q = allocateLayerQuotas(
      new Map([
        ["a", 3],
        ["b", 4],
      ]),
      999,
      strategy,
    );
    expect(sumQuotas(q)).toBe(7);
  });

  it("returns all zeros at zero capacity", () => {
    const q = allocateLayerQuotas(
      new Map([
        ["a", 10],
        ["b", 10],
      ]),
      0,
      strategy,
    );
    expect([...q.values()].every((n) => n === 0)).toBe(true);
  });

  it("ignores zero-demand layers", () => {
    const q = allocateLayerQuotas(
      new Map([
        ["a", 0],
        ["b", 10],
      ]),
      5,
      strategy,
    );
    expect(q.get("a") ?? 0).toBe(0);
    expect(q.has("a")).toBe(false);
    expect(q.get("b")).toBe(5);
  });

  it("is deterministic across repeated calls", () => {
    const demand = new Map([
      ["z", 50],
      ["a", 50],
      ["m", 50],
    ]);
    const first = allocateLayerQuotas(demand, 17, strategy);
    const second = allocateLayerQuotas(demand, 17, strategy);
    expect([...second.entries()]).toEqual([...first.entries()]);
  });

  it("gives every demanding layer at least 1 when capacity >= layerCount", () => {
    const q = allocateLayerQuotas(
      new Map([
        ["a", 500],
        ["b", 500],
        ["c", 1],
        ["d", 1],
      ]),
      8,
      strategy,
    );
    for (const id of ["a", "b", "c", "d"]) {
      expect(q.get(id)).toBeGreaterThanOrEqual(1);
    }
  });

  it("returns an empty map for empty demand", () => {
    const q = allocateLayerQuotas(new Map(), 10, strategy);
    expect(q.size).toBe(0);
  });
});

describe("allocateLayerQuotas ELASTIC", () => {
  it("splits evenly across three layers at capacity 9", () => {
    const q = allocateLayerQuotas(
      new Map([
        ["a", 100],
        ["b", 100],
        ["c", 100],
      ]),
      9,
      "ELASTIC",
    );
    expect(q.get("a")).toBe(3);
    expect(q.get("b")).toBe(3);
    expect(q.get("c")).toBe(3);
  });

  it("does not lose the indivisible remainder at capacity 10", () => {
    const q = allocateLayerQuotas(
      new Map([
        ["a", 100],
        ["b", 100],
        ["c", 100],
      ]),
      10,
      "ELASTIC",
    );
    expect(sumQuotas(q)).toBe(10);
    const values = [q.get("a")!, q.get("b")!, q.get("c")!].sort((x, y) => x - y);
    expect(values).toEqual([3, 3, 4]);
  });
});

describe("allocateLayerQuotas WEIGHTED", () => {
  it("sqrt-damps dense layers so sparse still gets room", () => {
    const q = allocateLayerQuotas(
      new Map([
        ["dense", 4000],
        ["sparse", 4],
      ]),
      20,
      "WEIGHTED",
    );
    expect(q.get("sparse") ?? 0).toBeGreaterThanOrEqual(2);
    expect(q.get("dense") ?? 0).toBeGreaterThan(q.get("sparse") ?? 0);
  });

  it("lets semantic weight beat raw count at equal counts", () => {
    const q = allocateLayerQuotas(
      new Map([
        ["boring", 100],
        ["urgent", 100],
      ]),
      20,
      "WEIGHTED",
      { boring: 0.5, urgent: 2 },
    );
    expect(q.get("urgent") ?? 0).toBeGreaterThan(q.get("boring") ?? 0);
  });

  it("floors zero/negative weight to MIN_SEMANTIC_WEIGHT instead of zeroing", () => {
    const q = allocateLayerQuotas(
      new Map([
        ["a", 50],
        ["b", 50],
      ]),
      10,
      "WEIGHTED",
      { a: 0, b: 1 },
    );
    expect(q.get("a") ?? 0).toBeGreaterThanOrEqual(1);
  });

  it("STAYS WEIGHTED after a layer saturates", () => {
    // 'tiny' saturates at 1. The 9 remaining slots must split by weight between
    // 'heavy' and 'light' (sqrt 20 : sqrt 5 = 4:1), NOT round-robin (~5:4),
    // which would quietly turn this into an elastic allocation.
    const q = allocateLayerQuotas(
      new Map([
        ["tiny", 1],
        ["heavy", 400],
        ["light", 25],
      ]),
      10,
      "WEIGHTED",
      { tiny: 1, heavy: 1, light: 1 },
    );
    expect(q.get("tiny")).toBe(1);
    expect(sumQuotas(q)).toBe(10);
    expect(q.get("heavy")).toBeGreaterThanOrEqual(6);
    expect(q.get("light")).toBeLessThanOrEqual(3);
  });
});

describe("LAYER_LABEL_WEIGHTS", () => {
  const expectedIds = [
    "events",
    "gdacs",
    "earthquakes",
    "eonet",
    "refineries",
    "datacenters",
    "pipelines",
    "cables",
  ] as const;

  it("covers all eight label layers with positive weights", () => {
    expect(Object.keys(LAYER_LABEL_WEIGHTS).sort()).toEqual([...expectedIds].sort());
    for (const id of expectedIds) {
      expect(LAYER_LABEL_WEIGHTS[id]).toBeGreaterThan(0);
    }
  });

  it("ranks alert layers above static infrastructure", () => {
    expect(LAYER_LABEL_WEIGHTS.events).toBeGreaterThan(LAYER_LABEL_WEIGHTS.cables);
    expect(LAYER_LABEL_WEIGHTS.gdacs).toBeGreaterThan(LAYER_LABEL_WEIGHTS.pipelines);
  });
});
