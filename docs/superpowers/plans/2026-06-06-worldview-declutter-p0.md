# WorldView Globe Declutter — P0 Quick-Win Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the WorldView globe legible again by adding a shared camera-altitude/viewport-culling core and applying distance attenuation + viewport culling + count caps to the dense layers that are actually on screen (FIRMS, Earthquakes), plus low-risk weight reductions for Satellites and Mil-air.

**Architecture:** Introduce one pure, fully-tested module `src/lib/lod.ts` (altitude bands, date-line-aware viewport bounds, a generic cull+cap selector, and shared `NearFarScalar` factories). Layers consume it: render through a `renderVisible` callback that culls to the viewport and caps the count, re-running on `camera.moveEnd` (the existing ShipLayer pattern), and attach `scaleByDistance` / `translucencyByDistance` to billboards so distant markers fade. No clustering, no heatmap, no color-system change — those are P1 (see TASK-114).

**Tech Stack:** React 19 + TypeScript, CesiumJS 1.132 (imperative `BillboardCollection` / `PointPrimitiveCollection` / `PolylineCollection` — **no Entity API for bulk**, per CLAUDE.md), Vitest 4 + @testing-library/react.

**Testing note — behavioral assertions, not smoke tests:** The cull/cap logic is unit-tested pure in `lib/lod.ts` (Task 1). The *layer* tests then assert real behavior by spying on the relevant Cesium collection prototype (`vi.spyOn(Cesium.BillboardCollection.prototype, "add")` etc., which **calls through** by default so the real layer still runs): the cap actually bites (N capped to the limit), out-of-viewport markers are dropped, distance attenuation is attached, and a `moveEnd` re-render re-queries the viewport. Each such test is RED against today's code (which renders everything, never culls, and registers no `moveEnd` listener) and GREEN after the task. `usePerformance()` has a safe context default (`{fps:60, degradation:0}`), so layers that call it render in tests without a provider.

**Scope (read before starting):**
- **In P0 (this plan):** `lib/lod.ts` + tests; FIRMS (dial-down + cull/cap/moveEnd/NearFar); Earthquakes (cull/cap/moveEnd/NearFar + label distance gate); Satellites (consolidate magic altitudes into `lib/lod.ts`, no behavior change); Mil-air (cosmetic polyline weight reduction only).
- **Deferred to P0.2 fast-follow (separate plan, trivial once `lib/lod.ts` exists):** apply the exact FIRMS/Earthquake pattern to GDACS, EONET, EventLayer — they were OFF in the trigger screenshot, so they do not block the quick-win.
- **Deferred to P1 (TASK-114):** spatial clustering, FIRMS density/heatmap surface, Hlíðskjalf-Noir color-token module, salience encoding, edge-bundling. Mil-air *track* declutter is temporal windowing → belongs to temporal-tracking Slice 0.

**Pre-flight:** Work in the worktree `.claude/worktrees/feat+worldview-declutter-p0` (already created, off clean `main`). All commands run from `services/frontend/`. Baseline is green: `npm run type-check` (0 errors) and `npm run test` (275 passing).

---

### Task 1: Shared LOD / culling core (`lib/lod.ts`)

**Files:**
- Create: `services/frontend/src/lib/lod.ts`
- Test: `services/frontend/src/lib/__tests__/lod.test.ts`

- [ ] **Step 1: Write the failing test**

Create `services/frontend/src/lib/__tests__/lod.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import {
  bandForHeight,
  inViewBounds,
  selectVisible,
  GLOBE_ALTITUDE_M,
  LOCAL_ALTITUDE_M,
  ORBIT_LOD_ALTITUDE_M,
} from "../lod";

describe("altitude constants", () => {
  it("pin the shared thresholds (Task 5 sources these to replace local literals)", () => {
    expect(GLOBE_ALTITUDE_M).toBe(8_000_000);
    expect(LOCAL_ALTITUDE_M).toBe(1_000_000);
    expect(ORBIT_LOD_ALTITUDE_M).toBe(45_000_000);
  });
});

describe("bandForHeight", () => {
  it("classifies GLOBE / REGIONAL / LOCAL by camera height", () => {
    expect(bandForHeight(GLOBE_ALTITUDE_M + 1)).toBe("GLOBE");
    expect(bandForHeight(GLOBE_ALTITUDE_M)).toBe("GLOBE");
    expect(bandForHeight(3_000_000)).toBe("REGIONAL");
    expect(bandForHeight(LOCAL_ALTITUDE_M)).toBe("REGIONAL");
    expect(bandForHeight(LOCAL_ALTITUDE_M - 1)).toBe("LOCAL");
  });
});

describe("inViewBounds", () => {
  const box = { south: 40, north: 50, west: 30, east: 50 };
  it("keeps points inside, rejects points outside", () => {
    expect(inViewBounds(37, 45, box)).toBe(true);
    expect(inViewBounds(60, 45, box)).toBe(false); // east of box
    expect(inViewBounds(37, 60, box)).toBe(false); // north of box
  });
  it("returns true when bounds is null (globe fills view)", () => {
    expect(inViewBounds(123, -80, null)).toBe(true);
  });
  it("handles anti-meridian wrap (west > east)", () => {
    const wrap = { south: -10, north: 10, west: 170, east: -170 };
    expect(inViewBounds(175, 0, wrap)).toBe(true);
    expect(inViewBounds(-175, 0, wrap)).toBe(true);
    expect(inViewBounds(0, 0, wrap)).toBe(false);
  });
});

describe("selectVisible", () => {
  const ll = (p: { lon: number; lat: number }) => [p.lon, p.lat] as const;
  const box = { south: 0, north: 10, west: 0, east: 10 };
  it("culls out-of-view items", () => {
    const items = [
      { lon: 5, lat: 5, id: "in" },
      { lon: 50, lat: 50, id: "out" },
    ];
    expect(selectVisible(items, ll, box, { cap: 100 }).map((i) => i.id)).toEqual(["in"]);
  });
  it("caps to N keeping the highest rank", () => {
    const items = [
      { lon: 1, lat: 1, r: 1 },
      { lon: 2, lat: 2, r: 9 },
      { lon: 3, lat: 3, r: 5 },
    ];
    const r = selectVisible(items, ll, box, { cap: 2, rank: (i) => i.r });
    expect(r.map((i) => i.r)).toEqual([9, 5]);
  });
  it("skips items whose accessor returns null", () => {
    const items = [{ lon: 5, lat: 5 }, { lon: null, lat: null }];
    const r = selectVisible(
      items,
      (i) => (i.lon == null ? null : ([i.lon, i.lat] as const)),
      box,
      { cap: 10 },
    );
    expect(r.length).toBe(1);
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `npm run test -- lod`
Expected: FAIL — `Cannot find module '../lod'`.

- [ ] **Step 3: Write the minimal implementation**

Create `services/frontend/src/lib/lod.ts`:

```ts
import * as Cesium from "cesium";

/** Camera-altitude bands shared by all globe layers (single source of truth). */
export type AltitudeBand = "GLOBE" | "REGIONAL" | "LOCAL";

/** At/above this camera height (m) we are at globe scale (mega-constellations hidden, aggregates only). */
export const GLOBE_ALTITUDE_M = 8_000_000;
/** Below this camera height (m) we are at local scale (labels + fine detail). */
export const LOCAL_ALTITUDE_M = 1_000_000;
/** Orbit arcs / space polylines stay visible up to this camera height (LEO..GEO). */
export const ORBIT_LOD_ALTITUDE_M = 45_000_000;

export function bandForHeight(height: number): AltitudeBand {
  if (height >= GLOBE_ALTITUDE_M) return "GLOBE";
  if (height < LOCAL_ALTITUDE_M) return "LOCAL";
  return "REGIONAL";
}

export interface ViewBounds {
  south: number;
  north: number;
  west: number;
  east: number;
}

/** Current viewport bounds in degrees, or null if the globe fills the view (→ no culling). */
export function getViewBounds(viewer: Cesium.Viewer): ViewBounds | null {
  const rect = viewer.camera.computeViewRectangle(viewer.scene.globe.ellipsoid);
  if (!rect) return null;
  return {
    south: Cesium.Math.toDegrees(rect.south),
    north: Cesium.Math.toDegrees(rect.north),
    west: Cesium.Math.toDegrees(rect.west),
    east: Cesium.Math.toDegrees(rect.east),
  };
}

/** True if (lon,lat) lies within bounds. Handles anti-meridian wrap (west > east). */
export function inViewBounds(lon: number, lat: number, bounds: ViewBounds | null): boolean {
  if (!bounds) return true;
  if (lat < bounds.south || lat > bounds.north) return false;
  if (bounds.west <= bounds.east) {
    return lon >= bounds.west && lon <= bounds.east;
  }
  // viewport crosses the date line
  return lon >= bounds.west || lon <= bounds.east;
}

export interface SelectOptions<T> {
  cap: number;
  /** Higher rank = kept first when the cap bites. Omit to keep input order. */
  rank?: (item: T) => number;
}

/**
 * Cull items to the viewport, then cap the count keeping the highest-ranked.
 * Pure (no Cesium) → fully unit-testable. Layers call this once per render.
 */
export function selectVisible<T>(
  items: readonly T[],
  getLonLat: (item: T) => readonly [number, number] | null,
  bounds: ViewBounds | null,
  opts: SelectOptions<T>,
): T[] {
  const inView: T[] = [];
  for (const item of items) {
    const ll = getLonLat(item);
    if (!ll) continue;
    if (inViewBounds(ll[0], ll[1], bounds)) inView.push(item);
  }
  if (opts.rank) {
    const rank = opts.rank;
    inView.sort((a, b) => rank(b) - rank(a));
  }
  return inView.length > opts.cap ? inView.slice(0, opts.cap) : inView;
}

/** Shared distance attenuation for bulk billboards — full size/opacity near, faded far. */
export function bulkScaleByDistance(): Cesium.NearFarScalar {
  return new Cesium.NearFarScalar(100_000, 1.0, 12_000_000, 0.45);
}
export function bulkTranslucencyByDistance(): Cesium.NearFarScalar {
  return new Cesium.NearFarScalar(100_000, 1.0, 14_000_000, 0.35);
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `npm run test -- lod`
Expected: PASS (all `lod` describe blocks green).

- [ ] **Step 5: Type-check**

Run: `npm run type-check`
Expected: 0 errors.

- [ ] **Step 6: Commit**

```bash
git add src/lib/lod.ts src/lib/__tests__/lod.test.ts
git commit -m "feat(frontend): add shared LOD/viewport-cull core (lib/lod.ts)"
```

---

### Task 2: FIRMS dial-down (kill the "thermal blobs")

The FIRMS glow billboards dominate the view: `frpToSize` returns up to 22px and dots render at `scale: 1.0`. Shrink the ceiling and base scale so hotspots read as markers, not blobs. (The component test file is fully rewritten in Task 3; here we change only `frpToSize` and its existing assertion + the dot render scale.)

**Files:**
- Modify: `services/frontend/src/components/layers/FIRMSLayer.tsx:5-7` (frpToSize) and the dot `bc.add({ scale })` call
- Test: `services/frontend/src/components/layers/__tests__/FIRMSLayer.test.tsx:26-30`

- [ ] **Step 1: Update the failing test for the new size ceiling**

In `__tests__/FIRMSLayer.test.tsx`, replace the `frpToSize` test (lines 26-30) with:

```ts
  it("frpToSize clamps between 4 and 14", () => {
    expect(frpToSize(0)).toBe(4);
    expect(frpToSize(35)).toBeCloseTo(11);
    expect(frpToSize(500)).toBe(14);
  });
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `npm run test -- FIRMSLayer`
Expected: FAIL — current `frpToSize(0)` is 6, not 4.

- [ ] **Step 3: Update `frpToSize` and the dot scale**

In `FIRMSLayer.tsx`, replace `frpToSize` (lines 5-7):

```ts
export function frpToSize(frp: number): number {
  return Math.min(14, 4 + Math.min(frp / 5, 10));
}
```

And in the render loop, change the dot's `scale` (currently `scale: 1.0` in the `bc.add` for the dot) to `scale: 0.7`. (Leave the explosion ring `bc.add` scale as-is.)

- [ ] **Step 4: Run the test to verify it passes**

Run: `npm run test -- FIRMSLayer`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/components/layers/FIRMSLayer.tsx src/components/layers/__tests__/FIRMSLayer.test.tsx
git commit -m "fix(frontend): shrink FIRMS hotspot glyphs to markers, not blobs"
```

---

### Task 3: FIRMS — viewport cull + cap + moveEnd + distance fade (reference application)

Refactor `FIRMSLayer` to the ShipLayer culling pattern: render through a `renderVisible` callback that culls to the viewport and caps to 400 hotspots (ranked by FRP), re-rendering on `camera.moveEnd`, with distance attenuation on every billboard. Tests assert the cap actually bites, out-of-view markers drop, NearFar is attached, and a move re-queries the viewport.

**Files:**
- Modify: `services/frontend/src/components/layers/FIRMSLayer.tsx`
- Test (full rewrite): `services/frontend/src/components/layers/__tests__/FIRMSLayer.test.tsx`

- [ ] **Step 1: Replace the whole test file with behavioral tests**

Overwrite `services/frontend/src/components/layers/__tests__/FIRMSLayer.test.tsx` with:

```ts
import { describe, it, expect, vi, afterEach } from "vitest";
import { render } from "@testing-library/react";
import * as Cesium from "cesium";
import { FIRMSLayer, createFIRMSDot, frpToSize, frpToColor } from "../FIRMSLayer";
import type { FIRMSHotspot } from "../../../types";

afterEach(() => vi.restoreAllMocks());

function fakeViewer(
  rect: Cesium.Rectangle = Cesium.Rectangle.fromDegrees(-180, -85, 180, 85),
): Cesium.Viewer & { _fireMoveEnd: () => void; _computeViewRectangle: ReturnType<typeof vi.fn> } {
  const primitives = { add: vi.fn((p: unknown) => p), remove: vi.fn() };
  const moveEndListeners: Array<() => void> = [];
  const computeViewRectangle = vi.fn(() => rect);
  return {
    scene: {
      primitives,
      requestRender: vi.fn(),
      frameState: { mode: Cesium.SceneMode.SCENE3D },
      pick: vi.fn(() => undefined),
      globe: { ellipsoid: Cesium.Ellipsoid.WGS84 },
    },
    camera: {
      positionCartographic: { height: 3_000_000 },
      computeViewRectangle,
      moveEnd: {
        addEventListener: vi.fn((cb: () => void) => { moveEndListeners.push(cb); }),
        removeEventListener: vi.fn(),
      },
    },
    canvas: document.createElement("canvas"),
    isDestroyed: () => false,
    _fireMoveEnd: () => moveEndListeners.forEach((cb) => cb()),
    _computeViewRectangle: computeViewRectangle,
  } as unknown as Cesium.Viewer & { _fireMoveEnd: () => void; _computeViewRectangle: ReturnType<typeof vi.fn> };
}

describe("FIRMS canvas helpers", () => {
  it("frpToSize clamps between 4 and 14", () => {
    expect(frpToSize(0)).toBe(4);
    expect(frpToSize(35)).toBeCloseTo(11);
    expect(frpToSize(500)).toBe(14);
  });

  it("frpToColor interpolates yellow → orange → red", () => {
    const cold = frpToColor(0);
    const hot = frpToColor(100);
    expect(cold.red).toBeGreaterThan(0.9);
    expect(cold.green).toBeGreaterThan(0.8);
    expect(hot.red).toBeGreaterThan(0.9);
    expect(hot.green).toBeLessThan(0.3);
  });

  it("createFIRMSDot returns a canvas of non-zero size", () => {
    const c = createFIRMSDot(10, Cesium.Color.RED);
    expect(c.width).toBeGreaterThan(0);
    expect(c.height).toBeGreaterThan(0);
  });
});

describe("FIRMSLayer component", () => {
  const baseHotspot = (over: Partial<FIRMSHotspot>): FIRMSHotspot => ({
    id: over.id ?? "h",
    latitude: 48, longitude: 37,
    frp: 20, brightness: 370, confidence: "n",
    acq_date: "2026-04-11", acq_time: "1200",
    satellite: "VIIRS_SNPP_NRT", bbox_name: "ukraine",
    possible_explosion: false,
    firms_map_url: "https://example/",
    ...over,
  });

  const manyHotspots = (n: number, lon: number, lat: number): FIRMSHotspot[] =>
    Array.from({ length: n }, (_, i) => baseHotspot({ id: `h${i}`, longitude: lon, latitude: lat, frp: i }));

  it("caps rendered hotspots at 400 and attaches distance attenuation", () => {
    const addSpy = vi.spyOn(Cesium.BillboardCollection.prototype, "add");
    const viewer = fakeViewer();
    render(<FIRMSLayer viewer={viewer} hotspots={manyHotspots(600, 37, 48)} visible={true} />);
    // non-explosion hotspots → exactly one dot billboard each
    expect(addSpy.mock.calls.length).toBe(400);
    const opts = addSpy.mock.calls[0]![0] as Record<string, unknown>;
    expect(opts.scaleByDistance).toBeInstanceOf(Cesium.NearFarScalar);
    expect(opts.translucencyByDistance).toBeInstanceOf(Cesium.NearFarScalar);
  });

  it("culls hotspots outside the viewport", () => {
    const addSpy = vi.spyOn(Cesium.BillboardCollection.prototype, "add");
    const viewer = fakeViewer(Cesium.Rectangle.fromDegrees(30, 40, 45, 50)); // Black Sea box
    render(
      <FIRMSLayer
        viewer={viewer}
        hotspots={[
          baseHotspot({ id: "in", longitude: 37, latitude: 45 }),
          baseHotspot({ id: "out", longitude: -120, latitude: 35 }),
        ]}
        visible={true}
      />,
    );
    expect(addSpy.mock.calls.length).toBe(1);
  });

  it("re-renders on camera move (re-queries the viewport)", () => {
    const viewer = fakeViewer();
    render(<FIRMSLayer viewer={viewer} hotspots={[baseHotspot({ id: "a" })]} visible={true} />);
    const before = viewer._computeViewRectangle.mock.calls.length;
    viewer._fireMoveEnd();
    expect(viewer._computeViewRectangle.mock.calls.length).toBeGreaterThan(before);
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `npm run test -- FIRMSLayer`
Expected: FAIL — today's layer renders all 600 (cap test expects 400), renders both in/out hotspots (cull test expects 1), and registers no `moveEnd` listener (move test: `computeViewRectangle` count does not grow).

- [ ] **Step 3: Refactor `FIRMSLayer` to cull + cap + moveEnd + distance fade**

In `FIRMSLayer.tsx`:

(a) Update imports at the top:

```ts
import { useEffect, useRef, useCallback } from "react";
import * as Cesium from "cesium";
import type { FIRMSHotspot } from "../../types";
import {
  getViewBounds,
  selectVisible,
  bulkScaleByDistance,
  bulkTranslucencyByDistance,
} from "../../lib/lod";

const MAX_FIRMS = 400;
```

(b) Inside `FIRMSLayer`, add prop refs (after the existing `onSelectRef`):

```ts
  const hotspotsRef = useRef(hotspots);
  hotspotsRef.current = hotspots;
  const visibleRef = useRef(visible);
  visibleRef.current = visible;
```

(c) Replace the render effect (current lines 106-136) with a `renderVisible` callback + two effects:

```ts
  const renderVisible = useCallback(() => {
    const bc = collectionRef.current;
    if (!bc || !viewer || viewer.isDestroyed()) return;

    bc.removeAll();
    idMapRef.current.clear();
    pulsesRef.current = [];
    if (!visibleRef.current) return;

    const bounds = getViewBounds(viewer);
    const shown = selectVisible(
      hotspotsRef.current,
      (h) => [h.longitude, h.latitude] as const,
      bounds,
      { cap: MAX_FIRMS, rank: (h) => h.frp },
    );

    const scaleByDistance = bulkScaleByDistance();
    const translucencyByDistance = bulkTranslucencyByDistance();

    for (const h of shown) {
      const position = Cesium.Cartesian3.fromDegrees(h.longitude, h.latitude, 0);
      const size = frpToSize(h.frp);
      const color = frpToColor(h.frp);
      const dot = bc.add({
        position,
        image: createFIRMSDot(size, color),
        scale: 0.7,
        eyeOffset: new Cesium.Cartesian3(0, 0, -45),
        scaleByDistance,
        translucencyByDistance,
      });
      idMapRef.current.set(dot as unknown as object, h);
      if (h.possible_explosion) {
        const ring = bc.add({
          position,
          image: createFIRMSRing(size * 1.5, color),
          scale: 1.0,
          eyeOffset: new Cesium.Cartesian3(0, 0, -44),
          translucencyByDistance,
        });
        idMapRef.current.set(ring as unknown as object, h);
        pulsesRef.current.push({ ring, color });
      }
    }
  }, [viewer]);

  // Re-render on data / visibility change
  useEffect(() => {
    renderVisible();
  }, [hotspots, visible, renderVisible]);

  // Re-render on camera move (viewport culling)
  useEffect(() => {
    if (!viewer || viewer.isDestroyed()) return;
    const onMoveEnd = () => renderVisible();
    viewer.camera.moveEnd.addEventListener(onMoveEnd);
    return () => {
      if (!viewer.isDestroyed()) viewer.camera.moveEnd.removeEventListener(onMoveEnd);
    };
  }, [viewer, renderVisible]);
```

(Keep the setup effect at lines 75-104 and the pulse-animation effect at 138-158 unchanged.)

- [ ] **Step 4: Run the tests**

Run: `npm run test -- FIRMSLayer`
Expected: PASS (cap=400, cull=1, move re-queries, helpers green).

- [ ] **Step 5: Type-check**

Run: `npm run type-check`
Expected: 0 errors.

- [ ] **Step 6: Commit**

```bash
git add src/components/layers/FIRMSLayer.tsx src/components/layers/__tests__/FIRMSLayer.test.tsx
git commit -m "feat(frontend): FIRMS viewport cull + 400 cap + distance fade"
```

---

### Task 4: Earthquakes — viewport cull + cap + moveEnd + distance fade + label gate

Apply the same transform to `EarthquakeLayer` (rank by magnitude, cap 250) + a distance gate on the magnitude labels. Each quake renders exactly one label → spy `LabelCollection.prototype.add` to assert the cap/cull; spy `BillboardCollection.prototype.add` to assert distance attenuation. The pulse loop reads `pulsesRef`, which `renderVisible` rebuilds.

**Files:**
- Modify: `services/frontend/src/components/layers/EarthquakeLayer.tsx`
- Test: `services/frontend/src/components/layers/__tests__/EarthquakeLayer.test.tsx` (new)

- [ ] **Step 1: Write the failing behavioral test**

Create `services/frontend/src/components/layers/__tests__/EarthquakeLayer.test.tsx` (the `Earthquake` type requires `tsunami: boolean` and `url: string | null` — both in the factory):

```ts
import { describe, it, expect, vi, afterEach } from "vitest";
import { render } from "@testing-library/react";
import * as Cesium from "cesium";
import { EarthquakeLayer } from "../EarthquakeLayer";
import type { Earthquake } from "../../../types";

afterEach(() => vi.restoreAllMocks());

function fakeViewer(
  rect: Cesium.Rectangle = Cesium.Rectangle.fromDegrees(-180, -85, 180, 85),
): Cesium.Viewer & { _fireMoveEnd: () => void; _computeViewRectangle: ReturnType<typeof vi.fn> } {
  const primitives = { add: vi.fn((p: unknown) => p), remove: vi.fn() };
  const moveEndListeners: Array<() => void> = [];
  const computeViewRectangle = vi.fn(() => rect);
  return {
    scene: {
      primitives,
      requestRender: vi.fn(),
      frameState: { mode: Cesium.SceneMode.SCENE3D },
      globe: { ellipsoid: Cesium.Ellipsoid.WGS84 },
    },
    camera: {
      positionCartographic: { height: 3_000_000 },
      computeViewRectangle,
      moveEnd: {
        addEventListener: vi.fn((cb: () => void) => { moveEndListeners.push(cb); }),
        removeEventListener: vi.fn(),
      },
    },
    canvas: document.createElement("canvas"),
    isDestroyed: () => false,
    _fireMoveEnd: () => moveEndListeners.forEach((cb) => cb()),
    _computeViewRectangle: computeViewRectangle,
  } as unknown as Cesium.Viewer & { _fireMoveEnd: () => void; _computeViewRectangle: ReturnType<typeof vi.fn> };
}

const quake = (over: Partial<Earthquake>): Earthquake => ({
  id: over.id ?? "q",
  latitude: 45,
  longitude: 37,
  depth_km: 10,
  magnitude: 5.2,
  place: "x",
  time: "2026-06-06T12:00:00Z",
  tsunami: false,
  url: "https://example/",
  ...over,
});

const manyQuakes = (n: number, lon: number, lat: number): Earthquake[] =>
  Array.from({ length: n }, (_, i) => quake({ id: `q${i}`, longitude: lon, latitude: lat, magnitude: 3 + (i % 50) / 10 }));

describe("EarthquakeLayer", () => {
  it("caps rendered quakes at 250 (one label each)", () => {
    const labelAdd = vi.spyOn(Cesium.LabelCollection.prototype, "add");
    const viewer = fakeViewer();
    render(<EarthquakeLayer viewer={viewer} earthquakes={manyQuakes(600, 37, 45)} visible={true} />);
    expect(labelAdd.mock.calls.length).toBe(250);
  });

  it("attaches distance attenuation to the quake billboards", () => {
    const billboardAdd = vi.spyOn(Cesium.BillboardCollection.prototype, "add");
    const viewer = fakeViewer();
    render(<EarthquakeLayer viewer={viewer} earthquakes={[quake({ id: "a" })]} visible={true} />);
    const opts = billboardAdd.mock.calls[0]![0] as Record<string, unknown>;
    expect(opts.scaleByDistance).toBeInstanceOf(Cesium.NearFarScalar);
    expect(opts.translucencyByDistance).toBeInstanceOf(Cesium.NearFarScalar);
  });

  it("culls quakes outside the viewport", () => {
    const labelAdd = vi.spyOn(Cesium.LabelCollection.prototype, "add");
    const viewer = fakeViewer(Cesium.Rectangle.fromDegrees(30, 40, 45, 50));
    render(
      <EarthquakeLayer
        viewer={viewer}
        earthquakes={[
          quake({ id: "in", longitude: 37, latitude: 45 }),
          quake({ id: "out", longitude: -120, latitude: 35 }),
        ]}
        visible={true}
      />,
    );
    expect(labelAdd.mock.calls.length).toBe(1);
  });

  it("re-renders on camera move", () => {
    const viewer = fakeViewer();
    render(<EarthquakeLayer viewer={viewer} earthquakes={[quake({ id: "a" })]} visible={true} />);
    const before = viewer._computeViewRectangle.mock.calls.length;
    viewer._fireMoveEnd();
    expect(viewer._computeViewRectangle.mock.calls.length).toBeGreaterThan(before);
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `npm run test -- EarthquakeLayer`
Expected: FAIL — today's layer renders all 600 labels (cap test expects 250), adds billboards without `scaleByDistance` (attenuation test), renders both in/out (cull test expects 1), and registers no `moveEnd` listener (move test).

- [ ] **Step 3: Refactor `EarthquakeLayer`**

In `EarthquakeLayer.tsx`:

(a) Imports + constants:

```ts
import { useEffect, useRef, useCallback } from "react";
import * as Cesium from "cesium";
import type { Earthquake } from "../../types";
import { glyphColor } from "./glyphTokens";
import { usePerformance } from "../globe/PerformanceGuard";
import {
  getViewBounds,
  selectVisible,
  bulkScaleByDistance,
  bulkTranslucencyByDistance,
} from "../../lib/lod";

const MAX_QUAKES = 250;
const QUAKE_LABEL_ALTITUDE_M = 5_000_000;
```

(b) After the existing `degradationRef`, add prop refs:

```ts
  const earthquakesRef = useRef(earthquakes);
  earthquakesRef.current = earthquakes;
  const visibleRef = useRef(visible);
  visibleRef.current = visible;
```

(c) Replace the render effect (current lines 72-126) with a `renderVisible` callback + two effects:

```ts
  const renderVisible = useCallback(() => {
    const bc = collectionRef.current;
    const lc = labelCollectionRef.current;
    if (!bc || !lc || !viewer || viewer.isDestroyed()) return;

    bc.removeAll();
    lc.removeAll();
    pulsesRef.current = [];
    if (!visibleRef.current) return;

    const bounds = getViewBounds(viewer);
    const shown = selectVisible(
      earthquakesRef.current,
      (q) => [q.longitude, q.latitude] as const,
      bounds,
      { cap: MAX_QUAKES, rank: (q) => q.magnitude },
    );

    const scaleByDistance = bulkScaleByDistance();
    const translucencyByDistance = bulkTranslucencyByDistance();

    for (const quake of shown) {
      const position = Cesium.Cartesian3.fromDegrees(quake.longitude, quake.latitude, 0);
      const color = magnitudeToColor(quake.magnitude);
      const size = magnitudeToSize(quake.magnitude);

      const billboard = bc.add({
        position,
        image: createQuakeDot(size * 0.4, color),
        scale: 1.0,
        eyeOffset: new Cesium.Cartesian3(0, 0, -50),
        scaleByDistance,
        translucencyByDistance,
      });

      const ringBillboard = bc.add({
        position,
        image: createQuakeRing(size, color),
        scale: 1.0,
        eyeOffset: new Cesium.Cartesian3(0, 0, -49),
        translucencyByDistance,
      });

      lc.add({
        position,
        text: `M${quake.magnitude.toFixed(1)}`,
        font: "11px monospace",
        fillColor: color,
        outlineColor: Cesium.Color.BLACK,
        outlineWidth: 2,
        style: Cesium.LabelStyle.FILL_AND_OUTLINE,
        pixelOffset: new Cesium.Cartesian2(0, -size - 5),
        eyeOffset: new Cesium.Cartesian3(0, 0, -50),
        distanceDisplayCondition: new Cesium.DistanceDisplayCondition(0, QUAKE_LABEL_ALTITUDE_M),
      });

      pulsesRef.current.push({
        billboard,
        ringBillboard,
        magnitude: quake.magnitude,
        eventTimeMs: new Date(quake.time).getTime(),
        baseSize: size,
        color,
      });
    }
  }, [viewer]);

  // Re-render on data / visibility change
  useEffect(() => {
    renderVisible();
  }, [earthquakes, visible, renderVisible]);

  // Re-render on camera move (viewport culling)
  useEffect(() => {
    if (!viewer || viewer.isDestroyed()) return;
    const onMoveEnd = () => renderVisible();
    viewer.camera.moveEnd.addEventListener(onMoveEnd);
    return () => {
      if (!viewer.isDestroyed()) viewer.camera.moveEnd.removeEventListener(onMoveEnd);
    };
  }, [viewer, renderVisible]);
```

(Keep the setup effect at 48-70 and the pulse-animation effect at 128-182 unchanged.)

- [ ] **Step 4: Run the test**

Run: `npm run test -- EarthquakeLayer`
Expected: PASS (cap=250, attenuation set, cull=1, move re-queries).

- [ ] **Step 5: Type-check**

Run: `npm run type-check`
Expected: 0 errors.

- [ ] **Step 6: Commit**

```bash
git add src/components/layers/EarthquakeLayer.tsx src/components/layers/__tests__/EarthquakeLayer.test.tsx
git commit -m "feat(frontend): earthquake viewport cull + 250 cap + distance fade + label gate"
```

---

### Task 5: Satellites — consolidate magic altitudes into `lib/lod.ts` (no behavior change)

`SatelliteLayer` hard-codes `8_000_000` (mega-constellation cutoff) and `45_000_000` (orbit LOD) as local literals. Point them at the shared constants so `lib/lod.ts` is the single source of altitude thresholds. **Provably value-identical:** Task 1's `lod.test.ts` pins `GLOBE_ALTITUDE_M === 8_000_000` and `ORBIT_LOD_ALTITUDE_M === 45_000_000`, and the existing `SatelliteLayer.test.tsx` exercises `shouldShowOrbits` across the 45M boundary (`shouldShowOrbits(0, 35_786_000) === true`, `shouldShowOrbits(0, 60_000_000) === false`) — so any drift in the orbit-LOD constant breaks a test.

**Files:**
- Modify: `services/frontend/src/components/layers/SatelliteLayer.tsx:41` and `:146`

- [ ] **Step 1: Run the existing satellite tests (baseline)**

Run: `npm run test -- SatelliteLayer`
Expected: PASS (`shouldShowOrbits` + satData-guard suites green). Record the count.

- [ ] **Step 2: Replace the local literals with shared constants**

In `SatelliteLayer.tsx`:

(a) Add to imports (after the `usePerformance` import):

```ts
import { GLOBE_ALTITUDE_M, ORBIT_LOD_ALTITUDE_M } from "../../lib/lod";
```

(b) Replace the local orbit-LOD constant (line 41):

```ts
const ORBIT_LOD_ALTITUDE = ORBIT_LOD_ALTITUDE_M; // keep orbits visible across LEO..GEO globe-scale zoom
```

(c) Replace the mega-constellation cutoff (line 146):

```ts
    const showMegaConstellations = cameraAlt < GLOBE_ALTITUDE_M;
```

- [ ] **Step 3: Run the satellite tests + the lod constant-pin test to verify no behavior change**

Run: `npm run test -- SatelliteLayer lod`
Expected: PASS (same satellite count as Step 1; `lod` constant-pin green — guarantees the swapped literals are identical).

- [ ] **Step 4: Type-check**

Run: `npm run type-check`
Expected: 0 errors.

- [ ] **Step 5: Commit**

```bash
git add src/components/layers/SatelliteLayer.tsx
git commit -m "refactor(frontend): source satellite altitude thresholds from lib/lod"
```

---

### Task 6: Mil-air — cosmetic polyline weight reduction (low-risk only)

The white/cyan track "gewirr" needs *temporal* declutter (only show recent track segments) — that is temporal-tracking Slice 0, which will restructure this file. To avoid churn that conflicts with Slice 0, P0 makes a **cosmetic-only** change: thinner, more translucent track polylines. We assert the rendered polyline's `width` and material color alpha by spying on `PolylineCollection.prototype.add`.

**Files:**
- Modify: `services/frontend/src/components/layers/MilAircraftLayer.tsx:119-127` (the track polyline `pc.add`)
- Test: `services/frontend/src/components/layers/__tests__/MilAircraftLayer.test.tsx` (add one behavioral test)

- [ ] **Step 1: Add the failing test**

In `__tests__/MilAircraftLayer.test.tsx`, add `afterEach(() => vi.restoreAllMocks());` after the imports, and add this test inside the existing `describe("MilAircraftLayer component", ...)` block (it reuses the file's existing `fakeViewer()` and `track()` helpers):

```ts
  it("renders track polylines thin and translucent (cosmetic declutter)", () => {
    const polyAdd = vi.spyOn(Cesium.PolylineCollection.prototype, "add");
    const viewer = fakeViewer();
    render(<MilAircraftLayer viewer={viewer} tracks={[track("a", 5)]} visible={true} onSelect={vi.fn()} />);
    const opts = polyAdd.mock.calls[0]![0] as { width: number; material: { uniforms: { color: Cesium.Color } } };
    expect(opts.width).toBe(1.0);
    expect(opts.material.uniforms.color.alpha).toBeCloseTo(0.3);
  });
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `npm run test -- MilAircraftLayer`
Expected: FAIL — the track polyline is currently added with `width: 1.5` and `color.withAlpha(0.6)`.

- [ ] **Step 3: Reduce polyline width + alpha**

In `MilAircraftLayer.tsx`, change the track polyline `pc.add` (currently `width: 1.5`, `color.withAlpha(0.6)`) to:

```ts
        const poly = pc.add({
          positions,
          width: 1.0,
          material: Cesium.Material.fromType("Color", { color: color.withAlpha(0.3) }),
        });
```

(Leave the jet-icon billboard untouched — heads stay crisp; only the trailing lines recede.)

- [ ] **Step 4: Run the test + type-check**

Run: `npm run test -- MilAircraftLayer`
Expected: PASS.
Run: `npm run type-check`
Expected: 0 errors.

- [ ] **Step 5: Commit**

```bash
git add src/components/layers/MilAircraftLayer.tsx src/components/layers/__tests__/MilAircraftLayer.test.tsx
git commit -m "fix(frontend): soften mil-air track polylines (cosmetic, pre-Slice0)"
```

---

### Task 7: Verify the whole slice (tests + types + lint + visual)

**Files:** none (verification only)

- [ ] **Step 1: Full test suite**

Run: `npm run test`
Expected: all pass, 0 failures. New/changed vs the 275 baseline: `lib/__tests__/lod.test.ts` (+1 file), `EarthquakeLayer.test.tsx` (+1 file), strengthened FIRMS + Mil-air component tests. Confirm the new behavioral tests (FIRMS cap/cull/move, Earthquake cap/cull/attenuation/move, mil-air width/alpha, lod) are all green.

- [ ] **Step 2: Type-check + lint**

Run: `npm run type-check && npm run lint`
Expected: 0 type errors; lint clean (no new warnings in touched files).

- [ ] **Step 3: Visual check (the real acceptance test)**

Run: `npm run dev`, open the app → WORLDVIEW, enable **FIRMS Hotspots + Earthquakes + Satellites + Mil-air**, navigate to the Black Sea / Caucasus (the trigger screenshot). Confirm:
- FIRMS hotspots are small markers, not large overlapping blobs.
- At regional zoom the periphery markers visibly fade (distance attenuation).
- Zooming out caps the on-screen FIRMS/quake count (no unbounded dot field); panning re-culls to the viewport.
- Mil-air tracks read as faint trails; jet heads still crisp.
- Basemap is legible again.

Capture a before/after note for the PR description.

- [ ] **Step 4: Finish the branch**

Use the **superpowers:finishing-a-development-branch** skill to open the PR (base `main`). Title: `feat(frontend): WorldView globe declutter P0 (LOD core + FIRMS/quake cull + fades)`. Body: link TASK-114, list P0 scope done + P0.2/P1 deferred, include the before/after visual note.

---

## Self-Review

**Spec coverage (vs TASK-114 P0 bullets):**
- "translucencyByDistance + scaleByDistance on all bulk layers" → `bulkScaleByDistance`/`bulkTranslucencyByDistance` (Task 1), applied + asserted on FIRMS (T3) and Earthquakes (T4). EventLayer already had it; GDACS/EONET get it in the P0.2 fast-follow (off-screen, documented deferral).
- "ONE shared LOD module (3 bands, camera.moveEnd height)" → `lib/lod.ts` `bandForHeight` + `getViewBounds` (T1); SatelliteLayer thresholds consolidated into it (T5).
- "Viewport culling on GDACS/EONET/Earthquakes/Events" → Earthquakes done + asserted (T4); FIRMS culling added + asserted (T3, the reference); GDACS/EONET/Events deferred to P0.2 (off-screen).
- "Max-count caps" → FIRMS 400 (T3), Earthquakes 250 (T4) via `selectVisible`, both asserted by spying on the rendered-marker count.
- Mil-air: cosmetic only (width/alpha asserted via spy); structural track declutter explicitly routed to Slice 0.

**Placeholder scan:** No "TBD"/"similar to Task N"; every code step shows full code. No trivially-green tests: each layer test asserts cap count, viewport culling, distance attenuation, or a moveEnd re-query, and is RED against current code (verified by the "Expected: FAIL" rationale in each Step 2).

**Type consistency:** `selectVisible` / `inViewBounds` / `getViewBounds` / `bulkScaleByDistance` / `bulkTranslucencyByDistance` / `bandForHeight` / `GLOBE_ALTITUDE_M` / `ORBIT_LOD_ALTITUDE_M` defined in Task 1, consumed with matching signatures in T3/T4/T5. Accessor returns `readonly [number, number] | null`. Test factories match the real types in `src/types/index.ts` (`Earthquake` includes `tsunami: boolean`, `url: string | null`; `FIRMSHotspot` and `AircraftTrack` fields verified).

**Scope check:** Single subsystem (frontend globe layers); one coherent plan. Off-screen layers and heavier techniques explicitly deferred with rationale.
