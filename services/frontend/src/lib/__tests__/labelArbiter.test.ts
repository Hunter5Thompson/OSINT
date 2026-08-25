import { describe, it, expect } from "vitest";
import {
  LABEL_ARBITER_TIMING,
  LABEL_CELL_SIZE_PX,
  LABEL_COLLISION_PADDING_PX,
  LabelArbiter,
  LabelSpatialHash,
  estimateLabelRect,
  rectsOverlap,
  type LabelCandidate,
  type ScreenRect,
} from "../labelArbiter";

function rect(x: number, y = 0, w = 40, h = 12): ScreenRect {
  return { x, y, w, h };
}

function candidate(
  key: string,
  layerId: string,
  x: number,
  priority: number,
  y = 0,
): LabelCandidate {
  return { key, layerId, rect: rect(x, y), priority };
}

function spread(
  layerId: string,
  count: number,
  xOffset = 0,
  priorityBase = 100,
): LabelCandidate[] {
  const out: LabelCandidate[] = [];
  for (let i = 0; i < count; i++) {
    out.push(candidate(`${layerId}:${i}`, layerId, xOffset + i * 100, priorityBase - i));
  }
  return out;
}

describe("rectsOverlap", () => {
  it("reports overlap versus clear separation", () => {
    expect(rectsOverlap(rect(0), rect(10))).toBe(true);
    expect(rectsOverlap(rect(0), rect(100, 100))).toBe(false);
  });

  it("uses a 4px gutter: 42 collides, 45 does not; padding 0 disables", () => {
    const a = rect(0, 0, 40, 12);
    expect(rectsOverlap(a, rect(42, 0))).toBe(true);
    expect(rectsOverlap(a, rect(45, 0))).toBe(false);
    expect(rectsOverlap(a, rect(42, 0), 0)).toBe(false);
  });
});

describe("constants", () => {
  it("pins the cell size at 32 and collision padding at 4", () => {
    expect(LABEL_CELL_SIZE_PX).toBe(32);
    expect(LABEL_COLLISION_PADDING_PX).toBe(4);
  });
});

describe("estimateLabelRect", () => {
  it("makes longer text wider", () => {
    const short = estimateLabelRect(0, 0, "A", 12);
    const longer = estimateLabelRect(0, 0, "AAAAAA", 12);
    expect(longer.w).toBeGreaterThan(short.w);
  });

  it("keeps height at least the font size", () => {
    const box = estimateLabelRect(0, 0, "M6.2", 11);
    expect(box.h).toBeGreaterThanOrEqual(11);
  });

  it("centres the box on the anchor", () => {
    const box = estimateLabelRect(100, 200, "ABCD", 10);
    expect(box.x + box.w / 2).toBe(100);
    expect(box.y + box.h / 2).toBe(200);
  });

  it("still returns positive size for empty text", () => {
    const box = estimateLabelRect(50, 50, "", 10);
    expect(box.w).toBeGreaterThan(0);
    expect(box.h).toBeGreaterThan(0);
  });
});

describe("LabelSpatialHash", () => {
  it("does not collide when empty", () => {
    const hash = new LabelSpatialHash();
    expect(hash.collides(rect(0))).toBe(false);
  });

  it("collides after insert", () => {
    const hash = new LabelSpatialHash();
    hash.insert(rect(10, 10));
    expect(hash.collides(rect(12, 10))).toBe(true);
  });

  it("detects a collision that crosses a 32px cell boundary", () => {
    const hash = new LabelSpatialHash();
    hash.insert(rect(28, 0));
    expect(hash.collides(rect(60, 0))).toBe(true);
  });

  it("clear forgets inserted rectangles", () => {
    const hash = new LabelSpatialHash();
    hash.insert(rect(10, 10));
    hash.clear();
    expect(hash.collides(rect(12, 10))).toBe(false);
  });

  it("does not throw on extreme or NaN inserts", () => {
    const hash = new LabelSpatialHash();
    expect(() => {
      hash.insert(rect(1e9, 1e9));
      hash.insert({ x: Number.NaN, y: Number.NaN, w: 40, h: 12 });
    }).not.toThrow();
  });

  it("does not report a collision at the origin after a NaN insert", () => {
    const hash = new LabelSpatialHash();
    hash.insert({ x: Number.NaN, y: Number.NaN, w: 40, h: 12 });
    expect(hash.collides(rect(0, 0))).toBe(false);
  });
});

describe("LabelArbiter budget", () => {
  it("never selects more than capacity", () => {
    const selected = new LabelArbiter().solve(spread("earthquakes", 50), {
      capacity: 10,
      now: 0,
    });
    expect(selected.size).toBe(10);
  });

  it("WEIGHTED split keeps a sparse alert layer in the cohort", () => {
    const selected = new LabelArbiter().solve(
      [...spread("firms", 400), ...spread("gdacs", 4, 1e6)],
      { capacity: 20, strategy: "WEIGHTED", now: 0 },
    );
    const gdacsKept = [...selected].filter((key) => key.startsWith("gdacs:")).length;
    expect(gdacsKept).toBeGreaterThanOrEqual(1);
  });

  it("prefers higher priority within a layer at capacity 1", () => {
    const selected = new LabelArbiter().solve(
      [
        candidate("low", "earthquakes", 0, 1),
        candidate("high", "earthquakes", 200, 9),
      ],
      { capacity: 1, now: 0 },
    );
    expect([...selected]).toEqual(["high"]);
  });

  it("returns empty for capacity 0 and for no candidates", () => {
    expect(new LabelArbiter().solve(spread("earthquakes", 5), { capacity: 0, now: 0 }).size).toBe(
      0,
    );
    expect(new LabelArbiter().solve([], { capacity: 10, now: 0 }).size).toBe(0);
  });
});

describe("LabelArbiter normalisation", () => {
  it("NORMALISES priority so raw scale does not decide a contested slot", () => {
    // capacity 1 forces a genuine cross-layer contest. Both layers offer their
    // own best candidate. Under raw comparison 'fires-top' (480) always beats
    // 'quakes-top' (7.1); under normalised rank both are 0 and the tie breaks
    // deterministically on key — so the assertion is that the OUTCOME does not
    // depend on the magnitude of the numbers.
    const solve = (fireTop: number, quakeTop: number) =>
      new LabelArbiter().solve(
        [
          { key: "a-quake", layerId: "quakes", rect: { x: 100, y: 100, w: 40, h: 12 }, priority: quakeTop },
          { key: "b-fire", layerId: "fires", rect: { x: 105, y: 100, w: 40, h: 12 }, priority: fireTop },
        ],
        { capacity: 1, now: 0 },
      );
    // Same winner whether the fire scores 480 or 0.5 — that is normalisation.
    expect([...solve(480, 7.1)]).toEqual([...solve(0.5, 7.1)]);
  });

  it("handles a single-candidate layer without dividing by zero", () => {
    expect(
      new LabelArbiter()
        .solve([{ key: "only", layerId: "solo", rect: { x: 0, y: 0, w: 40, h: 12 }, priority: 42 }],
               { capacity: 5, now: 0 })
        .has("only"),
    ).toBe(true);
  });
});

describe("LabelArbiter collision", () => {
  it("keeps the higher-priority of an overlapping pair and records the drop", () => {
    const arbiter = new LabelArbiter();
    const selected = arbiter.solve(
      [
        candidate("low", "layer", 100, 1, 100),
        candidate("high", "layer", 105, 10, 100),
      ],
      { capacity: 2, now: 0 },
    );
    expect(selected.has("high")).toBe(true);
    expect(selected.has("low")).toBe(false);
    expect(arbiter.diagnostics()?.droppedToCollision).toBe(1);
  });

  it("keeps both when they sit far apart", () => {
    const selected = new LabelArbiter().solve(
      [
        candidate("a", "layer", 0, 1),
        candidate("b", "layer", 400, 1),
      ],
      { capacity: 2, now: 0 },
    );
    expect(selected.size).toBe(2);
  });
});

describe("LabelArbiter lending", () => {
  it("lends unused quota so a stacked layer does not starve the scene", () => {
    const stacked: LabelCandidate[] = [];
    for (let i = 0; i < 5; i++) {
      stacked.push({
        key: `blocked:${i}`,
        layerId: "blocked",
        rect: rect(0, 0),
        priority: 5 - i,
      });
    }
    const open = spread("open", 20, 500000);
    const arbiter = new LabelArbiter();
    const selected = arbiter.solve([...stacked, ...open], { capacity: 12, now: 0 });
    expect(selected.size).toBe(12);
    expect([...selected].filter((key) => key.startsWith("blocked:")).length).toBe(1);
    expect(arbiter.diagnostics()?.lentSlots).toBeGreaterThan(0);
  });

  it("never lets lending exceed capacity", () => {
    const stacked: LabelCandidate[] = [];
    for (let i = 0; i < 8; i++) {
      stacked.push({
        key: `blocked:${i}`,
        layerId: "blocked",
        rect: rect(0, 0),
        priority: 8 - i,
      });
    }
    const selected = new LabelArbiter().solve([...stacked, ...spread("open", 40, 500000)], {
      capacity: 5,
      now: 0,
    });
    expect(selected.size).toBeLessThanOrEqual(5);
    expect(selected.size).toBe(5);
  });
});

describe("LabelArbiter hysteresis", () => {
  it("pins timings at 2500 / 1200", () => {
    expect(LABEL_ARBITER_TIMING.minimumLifetimeMs).toBe(2500);
    expect(LABEL_ARBITER_TIMING.cooldownMs).toBe(1200);
    expect(Object.isFrozen(LABEL_ARBITER_TIMING)).toBe(true);
  });

  it("holds an incumbent through its lifetime against a higher-priority newcomer", () => {
    const arbiter = new LabelArbiter();
    const incumbent = candidate("old", "quakes", 100, 1, 100);
    const newcomer = candidate("new", "quakes", 105, 99, 100);
    arbiter.solve([incumbent], { capacity: 1, now: 0 });
    const held = arbiter.solve([incumbent, newcomer], { capacity: 1, now: 1000 });
    expect(held.has("old")).toBe(true);
    expect(held.has("new")).toBe(false);
    expect(arbiter.diagnostics()?.heldByLifetime).toBe(1);
  });

  it("releases the incumbent after minimumLifetimeMs+1 and selects the newcomer", () => {
    const arbiter = new LabelArbiter();
    const incumbent = candidate("old", "quakes", 100, 1, 100);
    const newcomer = candidate("new", "quakes", 105, 99, 100);
    arbiter.solve([incumbent], { capacity: 1, now: 0 });
    arbiter.solve([incumbent, newcomer], { capacity: 1, now: 1000 });
    const released = arbiter.solve([incumbent, newcomer], {
      capacity: 1,
      now: LABEL_ARBITER_TIMING.minimumLifetimeMs + 1,
    });
    expect(released.has("new")).toBe(true);
    expect(released.has("old")).toBe(false);
  });

  it("blocks a recently dropped label during cooldown and admits it after", () => {
    const arbiter = new LabelArbiter();
    const keep = candidate("keep", "layer", 0, 10);
    const drop = candidate("drop", "layer", 400, 1);
    arbiter.solve([keep, drop], { capacity: 2, now: 0 });
    expect(arbiter.isSelected("keep")).toBe(true);
    expect(arbiter.isSelected("drop")).toBe(true);

    const evictedAt = LABEL_ARBITER_TIMING.minimumLifetimeMs + 1;
    arbiter.solve([keep, drop], { capacity: 1, now: evictedAt });
    expect(arbiter.isSelected("keep")).toBe(true);
    expect(arbiter.isSelected("drop")).toBe(false);

    arbiter.solve([keep, drop], { capacity: 2, now: evictedAt + 100 });
    expect(arbiter.isSelected("drop")).toBe(false);
    expect(arbiter.diagnostics()?.blockedByCooldown).toBe(1);

    arbiter.solve([keep, drop], {
      capacity: 2,
      now: evictedAt + LABEL_ARBITER_TIMING.cooldownMs + 200,
    });
    expect(arbiter.isSelected("drop")).toBe(true);
  });

  it("is stable across identical solves", () => {
    const arbiter = new LabelArbiter();
    const cohort = spread("earthquakes", 12);
    const first = [...arbiter.solve(cohort, { capacity: 8, now: 0 })].sort();
    const second = [...arbiter.solve(cohort, { capacity: 8, now: 0 })].sort();
    expect(second).toEqual(first);
  });

  it("clear() forgets incumbents so a newcomer can win immediately", () => {
    const arbiter = new LabelArbiter();
    const incumbent = candidate("old", "quakes", 100, 1, 100);
    const newcomer = candidate("new", "quakes", 105, 99, 100);
    arbiter.solve([incumbent], { capacity: 1, now: 0 });
    arbiter.clear();
    expect(arbiter.isSelected("old")).toBe(false);
    expect(arbiter.diagnostics()).toBeNull();
    const selected = arbiter.solve([incumbent, newcomer], { capacity: 1, now: 1 });
    expect(selected.has("new")).toBe(true);
    expect(selected.has("old")).toBe(false);
  });

  it("drops withdrawn candidates and their hysteresis state", () => {
    const arbiter = new LabelArbiter();
    const keep = candidate("keep", "layer", 0, 10);
    const gone = candidate("gone", "layer", 400, 9);
    arbiter.solve([keep, gone], { capacity: 2, now: 0 });
    expect(arbiter.isSelected("gone")).toBe(true);

    arbiter.solve([keep], { capacity: 2, now: 100 });
    expect(arbiter.isSelected("gone")).toBe(false);

    const usurper = candidate("usurper", "layer", 400, 1);
    arbiter.solve([keep, usurper], { capacity: 2, now: 200 });
    expect(arbiter.isSelected("usurper")).toBe(true);
  });
});
