# WorldView Globe Declutter — P0 Quick-Win Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the WorldView globe legible again by adding a shared camera-altitude/viewport-culling core and applying distance attenuation + viewport culling + count caps to the dense layers that are actually on screen (FIRMS, Earthquakes), plus low-risk weight reductions for Satellites and Mil-air.

**Architecture:** Introduce one pure, fully-tested module `src/lib/lod.ts` (altitude bands, date-line-aware viewport bounds, a generic cull+cap selector, and shared `NearFarScalar` factories). Layers consume it: render through a `renderVisible` callback that culls to the viewport and caps the count, re-running on `camera.moveEnd` (the existing ShipLayer pattern), and attach `scaleByDistance` / `translucencyByDistance` to billboards so distant markers fade. No clustering, no heatmap, no color-system change — those are P1 (see TASK-114).

**Tech Stack:** React 19 + TypeScript, CesiumJS 1.132 (imperative `BillboardCollection` / `PointPrimitiveCollection` / `PolylineCollection` — **no Entity API for bulk**, per CLAUDE.md), Vitest 4 + @testing-library/react.

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
} from "../lod";

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

The FIRMS glow billboards dominate the view: `frpToSize` returns up to 22px and dots render at `scale: 1.0`. Shrink the ceiling and base scale so hotspots read as markers, not blobs. Pure change — only the size function + render scale.

**Files:**
- Modify: `services/frontend/src/components/layers/FIRMSLayer.tsx:5-7` (frpToSize) and the dot `bc.add({ scale })` call
- Test: `services/frontend/src/components/layers/__tests__/FIRMSLayer.test.tsx:26-30`

- [ ] **Step 1: Update the failing test for the new size ceiling**

In `__tests__/FIRMSLayer.test.tsx`, replace the `frpToSize` test (lines 26-30) with:

```ts
  it("frpToSize clamps between 4 and 14", () => {
    expect(frpToSize(0)).toBe(4);
    expect(frpToSize(40)).toBeCloseTo(11);
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

And in the render loop, change the dot's `scale` (currently `scale: 1.0` in the `bc.add` for the dot) to:

```ts
        scale: 0.7,
```

(Leave the explosion ring `bc.add` scale as-is; it is gated on `possible_explosion` and is rare.)

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

Refactor `FIRMSLayer` to the ShipLayer culling pattern: render through a `renderVisible` callback that culls to the viewport and caps to 400 hotspots (ranked by FRP), re-rendering on `camera.moveEnd`, and attach distance attenuation to each billboard. This is the canonical per-layer transform reused in later tasks.

**Files:**
- Modify: `services/frontend/src/components/layers/FIRMSLayer.tsx` (imports, refs, render effect → callback, add moveEnd effect)
- Test: `services/frontend/src/components/layers/__tests__/FIRMSLayer.test.tsx` (extend fake viewer with a camera)

- [ ] **Step 1: Extend the test's fake viewer with a camera + assert no-throw on move**

In `__tests__/FIRMSLayer.test.tsx`, replace `fakeViewer()` (lines 7-23) with:

```ts
function fakeViewer(): Cesium.Viewer {
  const primitives = {
    add: vi.fn((p: unknown) => p),
    remove: vi.fn(),
  };
  const canvas = document.createElement("canvas");
  const moveEndListeners: Array<() => void> = [];
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
      computeViewRectangle: vi.fn(() => Cesium.Rectangle.fromDegrees(-180, -85, 180, 85)),
      moveEnd: {
        addEventListener: vi.fn((cb: () => void) => {
          moveEndListeners.push(cb);
        }),
        removeEventListener: vi.fn(),
      },
    },
    canvas,
    isDestroyed: () => false,
    // test helper: fire all registered moveEnd listeners
    _fireMoveEnd: () => moveEndListeners.forEach((cb) => cb()),
  } as unknown as Cesium.Viewer & { _fireMoveEnd: () => void };
}
```

Add a test at the end of the `FIRMSLayer component` describe block:

```ts
  it("re-renders on camera move without throwing", () => {
    const viewer = fakeViewer() as Cesium.Viewer & { _fireMoveEnd: () => void };
    render(
      <FIRMSLayer
        viewer={viewer}
        hotspots={[baseHotspot({ id: "a" }), baseHotspot({ id: "b" })]}
        visible={true}
      />,
    );
    expect(() => viewer._fireMoveEnd()).not.toThrow();
  });
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `npm run test -- FIRMSLayer`
Expected: FAIL — `viewer.camera.moveEnd.addEventListener` is never called yet, so `_fireMoveEnd()` fires nothing AND the new render path is not wired; specifically the test for move re-render passes trivially today, so first make the imports/refactor below; if green prematurely, that is acceptable — proceed.

> Note: this is an integration smoke test (the cull/cap *logic* is unit-tested in Task 1). Its value is catching a thrown error from the new camera wiring.

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

(b) Inside `FIRMSLayer`, add refs for the latest props (after the existing `onSelectRef`):

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

(Keep the setup effect at lines 75-104 and the pulse-animation effect at 138-158 unchanged. The `scale: 0.7` already applied in Task 2 stays.)

- [ ] **Step 4: Run the tests**

Run: `npm run test -- FIRMSLayer`
Expected: PASS (both the existing render test and the new move test).

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

Apply the same transform to `EarthquakeLayer` (rank by magnitude, cap 250) and add a distance gate to the magnitude labels so they stop stacking at globe scale. The pulse loop reads `pulsesRef`, which `renderVisible` rebuilds — preserved.

**Files:**
- Modify: `services/frontend/src/components/layers/EarthquakeLayer.tsx`
- Test: `services/frontend/src/components/layers/__tests__/EarthquakeLayer.test.tsx` (new)

- [ ] **Step 1: Write the failing integration test**

Create `services/frontend/src/components/layers/__tests__/EarthquakeLayer.test.tsx`:

```ts
import { describe, it, expect, vi } from "vitest";
import { render } from "@testing-library/react";
import * as Cesium from "cesium";
import { EarthquakeLayer } from "../EarthquakeLayer";
import type { Earthquake } from "../../../types";

function fakeViewer(): Cesium.Viewer & { _fireMoveEnd: () => void } {
  const primitives = { add: vi.fn((p: unknown) => p), remove: vi.fn() };
  const moveEndListeners: Array<() => void> = [];
  return {
    scene: {
      primitives,
      requestRender: vi.fn(),
      frameState: { mode: Cesium.SceneMode.SCENE3D },
      globe: { ellipsoid: Cesium.Ellipsoid.WGS84 },
    },
    camera: {
      positionCartographic: { height: 3_000_000 },
      computeViewRectangle: vi.fn(() => Cesium.Rectangle.fromDegrees(-180, -85, 180, 85)),
      moveEnd: {
        addEventListener: vi.fn((cb: () => void) => { moveEndListeners.push(cb); }),
        removeEventListener: vi.fn(),
      },
    },
    canvas: document.createElement("canvas"),
    isDestroyed: () => false,
    _fireMoveEnd: () => moveEndListeners.forEach((cb) => cb()),
  } as unknown as Cesium.Viewer & { _fireMoveEnd: () => void };
}

const quake = (over: Partial<Earthquake>): Earthquake => ({
  id: over.id ?? "q",
  latitude: 45, longitude: 37, magnitude: 5.2, depth_km: 10,
  place: "x", time: "2026-06-06T12:00:00Z", url: "https://example/",
  ...over,
});

describe("EarthquakeLayer", () => {
  it("renders and re-renders on camera move without throwing", () => {
    const viewer = fakeViewer();
    render(
      <EarthquakeLayer
        viewer={viewer}
        earthquakes={[quake({ id: "a", magnitude: 6.1 }), quake({ id: "b", magnitude: 4.5 })]}
        visible={true}
      />,
    );
    expect(() => viewer._fireMoveEnd()).not.toThrow();
  });
});
```

> If the real `Earthquake` type differs from the fields above, open `src/types/index.ts`, find `Earthquake`, and adjust the `quake()` factory to match (the test must compile).

- [ ] **Step 2: Run the test to verify it fails**

Run: `npm run test -- EarthquakeLayer`
Expected: FAIL — `viewer.camera.computeViewRectangle` is never called by the current layer, and (once wired) confirms no throw.

- [ ] **Step 3: Refactor `EarthquakeLayer`**

In `EarthquakeLayer.tsx`:

(a) Imports + constant:

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

- [ ] **Step 4: Run the test + full suite to verify no regression**

Run: `npm run test -- EarthquakeLayer`
Expected: PASS.

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

`SatelliteLayer` hard-codes `8_000_000` (mega-constellation cutoff) and `45_000_000` (orbit LOD) as local literals. Point them at the shared constants so `lib/lod.ts` is the single source of altitude thresholds. Behavior is identical — this is a consistency/maintainability change that makes the P1 satellite-thinning work land cleanly.

**Files:**
- Modify: `services/frontend/src/components/layers/SatelliteLayer.tsx:41` and `:146`

- [ ] **Step 1: Run the existing satellite tests (baseline)**

Run: `npm run test -- SatelliteLayer`
Expected: PASS (record the count).

- [ ] **Step 2: Replace the local literals with shared constants**

In `SatelliteLayer.tsx`:

(a) Add to imports (top of file, after the `usePerformance` import):

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

- [ ] **Step 3: Run the satellite tests to verify no behavior change**

Run: `npm run test -- SatelliteLayer`
Expected: PASS (same count as Step 1).

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

The white/cyan track "gewirr" needs *temporal* declutter (only show recent track segments) — that is temporal-tracking Slice 0, which will restructure this file. To avoid churn that conflicts with Slice 0, P0 makes a **cosmetic-only** change: thinner, more translucent track polylines so the tangle recedes. No structural / data-flow change.

**Files:**
- Modify: `services/frontend/src/components/layers/MilAircraftLayer.tsx:121-125` (the track polyline `pc.add`)

- [ ] **Step 1: Reduce polyline width + alpha**

In `MilAircraftLayer.tsx`, change the track polyline `pc.add` (currently width `1.5`, `color.withAlpha(0.6)`) to:

```ts
        const poly = pc.add({
          positions,
          width: 1.0,
          material: Cesium.Material.fromType("Color", { color: color.withAlpha(0.3) }),
        });
```

(Leave the jet-icon billboard untouched — heads stay crisp; only the trailing lines recede.)

- [ ] **Step 2: Run mil-air tests + type-check**

Run: `npm run test -- MilAircraftLayer`
Expected: PASS (existing tests assert structure/colors, not alpha — confirm green; if a test asserts the old alpha, update it to 0.3).
Run: `npm run type-check`
Expected: 0 errors.

- [ ] **Step 3: Commit**

```bash
git add src/components/layers/MilAircraftLayer.tsx
git commit -m "fix(frontend): soften mil-air track polylines (cosmetic, pre-Slice0)"
```

---

### Task 7: Verify the whole slice (tests + types + lint + visual)

**Files:** none (verification only)

- [ ] **Step 1: Full test suite**

Run: `npm run test`
Expected: all pass, ≥ 277 tests (275 baseline + new lod + EarthquakeLayer; FIRMS unchanged count). 0 failures.

- [ ] **Step 2: Type-check + lint**

Run: `npm run type-check && npm run lint`
Expected: 0 type errors; lint clean (no new warnings in touched files).

- [ ] **Step 3: Visual check (the real acceptance test)**

Run: `npm run dev`, open the app, go to WORLDVIEW, enable **FIRMS Hotspots + Earthquakes + Satellites + Mil-air**, and navigate to the Black Sea / Caucasus (the trigger screenshot). Confirm:
- FIRMS hotspots are small markers, not large overlapping blobs.
- At regional zoom the periphery markers visibly fade (distance attenuation).
- Zooming out caps the on-screen FIRMS/quake count (no unbounded dot field); panning re-culls.
- Mil-air tracks read as faint trails, jet heads still crisp.
- Basemap is legible again.

Capture a before/after note in the PR description.

- [ ] **Step 4: Finish the branch**

Use the **superpowers:finishing-a-development-branch** skill to open the PR (base `main`). Title: `feat(frontend): WorldView globe declutter P0 (LOD core + FIRMS/quake cull + fades)`. Body: link TASK-114, list P0 scope done + P0.2/P1 deferred, include the before/after visual note.

---

## Self-Review

**Spec coverage (vs TASK-114 P0 bullets):**
- "translucencyByDistance + scaleByDistance on all bulk layers" → `bulkNearFar` factories in Task 1, applied to FIRMS (T3) + Earthquakes (T4). EventLayer already had it; GDACS/EONET get it in the P0.2 fast-follow (documented deferral — they were OFF on screen).
- "ONE shared LOD module (3 bands, camera.moveEnd height)" → `lib/lod.ts` `bandForHeight` + `getViewBounds` (T1); SatelliteLayer thresholds consolidated into it (T5).
- "Viewport culling on GDACS/EONET/Earthquakes/Events" → Earthquakes done (T4); GDACS/EONET/Events deferred to P0.2 (off-screen). FIRMS culling added (T3) as the reference.
- "Max-count caps" → FIRMS 400 (T3), Earthquakes 250 (T4) via `selectVisible`.
- Mil-air: cosmetic only, structural declutter explicitly routed to Slice 0 (T6).

**Placeholder scan:** No "TBD"/"similar to Task N"; every code step shows full code. The two `> Note:` callouts flag (a) a possibly-trivially-green smoke test and (b) verifying the real `Earthquake` type — both are verification instructions, not missing content.

**Type consistency:** `selectVisible` / `inViewBounds` / `getViewBounds` / `bulkScaleByDistance` / `bulkTranslucencyByDistance` / `bandForHeight` / `GLOBE_ALTITUDE_M` / `ORBIT_LOD_ALTITUDE_M` are defined in Task 1 and consumed with matching signatures in T3/T4/T5. Accessor returns `readonly [number, number] | null` consistently. Caps are module constants per layer.

**Scope check:** Single subsystem (frontend globe layers); one coherent plan. Off-screen layers and heavier techniques explicitly deferred with rationale.
