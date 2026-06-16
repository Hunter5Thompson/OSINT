# WorldView UX-Politur Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix seven reported WorldView UX defects across the Cesium globe, the CHRONIK timeslider, the Briefing Room, and the War Room.

**Architecture:** Pure frontend (`services/frontend`) plus one static data file. Three clusters: A) Globe/map (pick-through fix, border visibility, full capital dataset, cartouche occlusion), B) full timeslider transport (signed-speed reverse + steps), C) Briefing delete + Munin readability. Logic that is awkward to test through Cesium is extracted into small pure helpers and unit-tested directly.

**Tech Stack:** React 19 + TypeScript + Vite 6 + CesiumJS; Vitest + @testing-library/react (jsdom). Test entry: `npm run test` (= `vitest run`). Lint: `npm run lint`. Types: `npm run type-check`. Build: `npm run build`. All commands run from `services/frontend`.

**Conventions (verified):** Tests live in `__tests__/` next to the unit or co-located as `*.test.tsx`. Cesium imports work in tests (see `src/components/time/__tests__/ScrubberMount.test.tsx`, `src/state/__tests__/TimeContext.test.tsx`). The `fakeClockViewer()` pattern in `ScrubberMount.test.tsx` is the template for clock assertions.

---

## Cluster A — Globe / Karte

### Task 1: `isPhotorealSurfacePick` helper (P3, pure)

**Files:**
- Create: `services/frontend/src/components/globe/isPhotorealSurfacePick.ts`
- Test: `services/frontend/src/components/globe/__tests__/isPhotorealSurfacePick.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
// services/frontend/src/components/globe/__tests__/isPhotorealSurfacePick.test.ts
import { describe, it, expect } from "vitest";
import type * as Cesium from "cesium";
import { isPhotorealSurfacePick } from "../isPhotorealSurfacePick";

// Plain objects stand in for picks/tilesets — no real Cesium viewer needed.
const photoreal = { _odinPhotoreal: true } as unknown as Cesium.Cesium3DTileset;

describe("isPhotorealSurfacePick", () => {
  it("returns false for empty-space picks (null/undefined)", () => {
    expect(isPhotorealSurfacePick(undefined, null)).toBe(false);
    expect(isPhotorealSurfacePick(null, null)).toBe(false);
  });

  it("returns true when the pick belongs to the photoreal tileset (by reference)", () => {
    expect(isPhotorealSurfacePick({ primitive: photoreal }, photoreal)).toBe(true);
    expect(isPhotorealSurfacePick({ tileset: photoreal }, photoreal)).toBe(true);
    expect(isPhotorealSurfacePick({ content: { tileset: photoreal } }, photoreal)).toBe(true);
  });

  it("returns true via the _odinPhotoreal marker even when the reference is null", () => {
    // A picked tile feature exposes its (marked) owning tileset via .tileset.
    expect(isPhotorealSurfacePick({ tileset: { _odinPhotoreal: true } }, null)).toBe(true);
  });

  it("returns false for a real data-layer primitive (billboard/polyline)", () => {
    const layerPick = { primitive: { id: "flight-billboard" }, id: { name: "Flight 123" } };
    expect(isPhotorealSurfacePick(layerPick, photoreal)).toBe(false);
  });

  it("returns false for an UNmarked, UNreferenced 3D-tileset-like pick (contract guard)", () => {
    // Some other tileset that is neither the photoreal reference nor marked.
    const otherTileset = { isCesium3DTileset: true };
    expect(isPhotorealSurfacePick({ primitive: otherTileset }, photoreal)).toBe(false);
    expect(isPhotorealSurfacePick({ tileset: otherTileset }, photoreal)).toBe(false);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test -- isPhotorealSurfacePick`
Expected: FAIL — `Cannot find module '../isPhotorealSurfacePick'`.

- [ ] **Step 3: Write minimal implementation**

```ts
// services/frontend/src/components/globe/isPhotorealSurfacePick.ts
import type * as Cesium from "cesium";

/**
 * True when a Cesium pick result is THE photorealistic globe surface — the
 * Google 3D Tiles tileset (or its OSM-buildings fallback) created by
 * GlobeViewer — rather than a real UI / data-layer primitive.
 *
 * Used by EntityClickHandler so a click that lands on the 3D surface still
 * falls through to the country hit-test (almanac), instead of being swallowed
 * by the tileset (the "almanac only works on the political/flat map" bug).
 *
 * Contract: classification requires POSITIVE identification of OUR tileset —
 * either reference-equality against the passed `photorealTileset`, OR the
 * `_odinPhotoreal` marker that GlobeViewer stamps on the tileset at creation
 * (the marker is reachable from a picked tile feature via `.tileset` /
 * `.content.tileset`, so it works even before the reference has propagated).
 * We deliberately do NOT treat an arbitrary 3D tileset/feature as photoreal —
 * an unmarked, unreferenced tileset returns false. (No `instanceof` checks: the
 * marker + reference are stronger and keep this helper Cesium-runtime-free and
 * trivially testable.)
 */
export function isPhotorealSurfacePick(
  picked: unknown,
  photorealTileset: Cesium.Cesium3DTileset | null,
): boolean {
  if (!picked) return false;

  const p = picked as {
    primitive?: unknown;
    tileset?: unknown;
    content?: { tileset?: unknown };
  };

  // A picked tile feature exposes its owning tileset via .tileset / .content;
  // a non-feature surface pick exposes it via .primitive.
  const candidates = [p.primitive, p.tileset, p.content?.tileset];
  for (const c of candidates) {
    if (!c) continue;
    if (photorealTileset && c === photorealTileset) return true;
    if ((c as { _odinPhotoreal?: boolean })._odinPhotoreal === true) return true;
  }
  return false;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm run test -- isPhotorealSurfacePick`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add services/frontend/src/components/globe/isPhotorealSurfacePick.ts \
        services/frontend/src/components/globe/__tests__/isPhotorealSurfacePick.test.ts
git commit -m "feat(globe): isPhotorealSurfacePick helper to detect 3D-surface picks (P3)"
```

---

### Task 2: Wire photoreal tileset → EntityClickHandler pick-through (P3)

**Files:**
- Modify: `services/frontend/src/components/globe/GlobeViewer.tsx` (props + `addBuildingsTileset` + cleanup)
- Modify: `services/frontend/src/pages/WorldviewPage.tsx` (tileset state + thread prop through `GlobeChildren` → `EventClickBridge` → `EntityClickHandler`)
- Modify: `services/frontend/src/components/globe/EntityClickHandler.tsx` (new prop + ref + pick-through guard)

- [ ] **Step 1: GlobeViewer — add callback prop + mark tileset + emit on ready/cleanup**

In `GlobeViewer.tsx`, extend the props interface (after line 12 `showCityBuildings: boolean;`):

```ts
interface GlobeViewerProps {
  onViewerReady: (viewer: Cesium.Viewer) => void;
  cesiumToken: string;
  activeShader: ShaderType;
  showCountryBorders: boolean;
  showCityBuildings: boolean;
  onPhotorealTilesetReady?: (tileset: Cesium.Cesium3DTileset | null) => void;
}
```

Add `onPhotorealTilesetReady` to the destructured params (after `showCityBuildings,`).

In `addBuildingsTileset` (currently lines 75–81), mark the tileset and emit it:

```ts
    const addBuildingsTileset = (tileset: Cesium.Cesium3DTileset) => {
      if (viewer.isDestroyed()) return;
      tileset.maximumScreenSpaceError = 2;
      tileset.show = showBuildingsRef.current;
      (tileset as unknown as { _odinPhotoreal?: boolean })._odinPhotoreal = true;
      viewer.scene.primitives.add(tileset);
      buildingsTilesetRef.current = tileset;
      onPhotorealTilesetReady?.(tileset);
    };
```

In the cleanup return (currently lines 163–166), null out the tileset AND notify:

```ts
      if (buildingsTilesetRef.current && viewerRef.current && !viewerRef.current.isDestroyed()) {
        viewerRef.current.scene.primitives.remove(buildingsTilesetRef.current);
        buildingsTilesetRef.current = null;
        onPhotorealTilesetReady?.(null);
      }
```

Add `onPhotorealTilesetReady` to the main effect's dependency array (currently `[cesiumToken, onViewerReady]` at line 183) → `[cesiumToken, onViewerReady, onPhotorealTilesetReady]`.

- [ ] **Step 2: WorldviewPage — hold tileset in state, thread it down**

In `WorldviewPage.tsx`, add state next to the other viewer state (after line 484 `const [viewer, setViewer] = useState<Cesium.Viewer | null>(null);`):

```ts
  const [photorealTileset, setPhotorealTileset] = useState<Cesium.Cesium3DTileset | null>(null);
```

Pass the callback to `<GlobeViewer>` (the render block ~lines 644–650), adding one prop:

```tsx
          <GlobeViewer
            onViewerReady={handleViewerReady}
            cesiumToken={config.cesium_ion_token}
            activeShader={activeShader}
            showCountryBorders={layers.countryBorders}
            showCityBuildings={layers.cityBuildings}
            onPhotorealTilesetReady={setPhotorealTileset}
          />
```

Add `photorealTileset` to `GlobeChildrenProps` (after `viewer: Cesium.Viewer | null;`):

```ts
interface GlobeChildrenProps {
  viewer: Cesium.Viewer | null;
  photorealTileset: Cesium.Cesium3DTileset | null;
  layers: LayerVisibility;
  // ...rest unchanged
}
```

Destructure it in `GlobeChildren({ viewer, photorealTileset, layers, ... })` and pass it to `<GlobeChildren>` at the call site (~line 674):

```tsx
        <GlobeChildren
          viewer={viewer}
          photorealTileset={photorealTileset}
          layers={layers}
          setSelected={setSelected}
          onSelectEvent={setSelectedEventId}
          firmsHotspots={firmsHotspots}
          selectedWindow={selectedWindow}
          datacenterData={datacenterData}
          refineryData={refineryData}
          eonetEvents={eonetEvents}
          gdacsEvents={gdacsEvents}
        />
```

In `GlobeChildren`'s body, `EntityClickHandler` is mounted via `EventClickBridge`. Add `photorealTileset` to `EventClickBridge`'s props type (the inline `{ viewer, onCountrySelect, onSelectEvent }` object at lines 389–397) and forward it:

```tsx
function EventClickBridge({
  viewer,
  photorealTileset,
  onCountrySelect,
  onSelectEvent,
}: {
  viewer: Cesium.Viewer | null;
  photorealTileset: Cesium.Cesium3DTileset | null;
  onCountrySelect: Dispatch<SetStateAction<Selected | null>>;
  onSelectEvent: (id: string) => void;
}) {
```

Return (lines 412–416) gains the prop:

```tsx
    <EntityClickHandler
      viewer={viewer}
      photorealTileset={photorealTileset}
      onCountrySelect={onCountrySelect}
      onEventSelect={handleEventSelect}
```

`GlobeChildren` renders `<EventClickBridge ... />` at line ~275 (inside its `return`, lines 161–281). Add `photorealTileset={photorealTileset}` to that element.

- [ ] **Step 3: EntityClickHandler — accept prop, ref it, and fall through on photoreal picks**

In `EntityClickHandler.tsx`, import the helper (after line 5):

```ts
import { isPhotorealSurfacePick } from "./isPhotorealSurfacePick";
```

Extend props (lines 20–25):

```ts
interface EntityClickHandlerProps {
  viewer: Cesium.Viewer | null;
  photorealTileset?: Cesium.Cesium3DTileset | null;
  onCountrySelect: (sel: Selected | null) => void;
  onEventSelect?: (id: string, timeIso?: string) => void;
}
```

Destructure `photorealTileset` in the component params, and mirror it into a ref so the `[viewer]`-keyed handler reads the latest (next to `onEventSelectRef`, lines 45–46):

```ts
  const photorealTilesetRef = useRef(photorealTileset ?? null);
  photorealTilesetRef.current = photorealTileset ?? null;
```

Change the early-return guard (currently lines 349–351):

```ts
      // A picked primitive that isn't a known data-tag: if it's the photoreal
      // 3D surface, fall through to the country hit-test (almanac works on the
      // 3D/"geographic" map). Only a real UI/layer primitive aborts here.
      if (picked && !isPhotorealSurfacePick(picked, photorealTilesetRef.current)) {
        return;
      }
```

- [ ] **Step 4: Write a focused regression test for the pick-through path**

**Files:** Create `services/frontend/src/components/globe/__tests__/entityClickHandler.pickthrough.test.ts`

This test asserts the decision logic (the helper + guard) at the unit level — full ScreenSpaceEventHandler simulation is out of scope; the helper test (Task 1) plus this guard-truth-table cover the behavior:

```ts
import { describe, it, expect } from "vitest";
import * as Cesium from "cesium";
import { isPhotorealSurfacePick } from "../isPhotorealSurfacePick";

// Mirrors EntityClickHandler's guard: abort ONLY on real UI/layer picks.
function abortsBeforeCountryHitTest(
  picked: unknown,
  tileset: Cesium.Cesium3DTileset | null,
): boolean {
  return Boolean(picked) && !isPhotorealSurfacePick(picked, tileset);
}

describe("EntityClickHandler pick-through guard", () => {
  const tileset = { _odinPhotoreal: true } as unknown as Cesium.Cesium3DTileset;

  it("does NOT abort on a photoreal-surface pick (almanac runs on 3D map)", () => {
    expect(abortsBeforeCountryHitTest({ primitive: tileset }, tileset)).toBe(false);
  });

  it("aborts on a real data-layer pick (preserves the 6 onSelect layers)", () => {
    expect(abortsBeforeCountryHitTest({ primitive: { id: "firms" } }, tileset)).toBe(true);
  });

  it("does NOT abort on empty space (existing void → country path)", () => {
    expect(abortsBeforeCountryHitTest(undefined, tileset)).toBe(false);
  });
});
```

- [ ] **Step 5: Run tests + type-check**

Run: `npm run test -- isPhotorealSurfacePick entityClickHandler && npm run type-check`
Expected: PASS; type-check clean.

- [ ] **Step 6: Commit**

```bash
git add services/frontend/src/components/globe/GlobeViewer.tsx \
        services/frontend/src/pages/WorldviewPage.tsx \
        services/frontend/src/components/globe/EntityClickHandler.tsx \
        services/frontend/src/components/globe/__tests__/entityClickHandler.pickthrough.test.ts
git commit -m "fix(globe): almanac click falls through 3D photoreal tiles to country hit-test (P3)"
```

---

### Task 3: Country borders visible over photoreal tiles (P2)

**Files:**
- Modify: `services/frontend/src/components/globe/visual-layers/CountryBorders.tsx`
- Test: `services/frontend/src/components/globe/visual-layers/__tests__/CountryBorders.style.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
// services/frontend/src/components/globe/visual-layers/__tests__/CountryBorders.style.test.ts
import { describe, it, expect } from "vitest";
import { BORDER_WIDTH, borderPolylineOptions } from "../CountryBorders";

describe("CountryBorders styling", () => {
  it("uses a thicker line so borders read over photoreal terrain", () => {
    expect(BORDER_WIDTH).toBeGreaterThanOrEqual(1.5);
  });

  it("disables depth-test so borders are not occluded by 3D tiles/terrain", () => {
    const opts = borderPolylineOptions([], {} as never);
    expect(opts.width).toBe(BORDER_WIDTH);
    expect(opts.disableDepthTestDistance).toBe(Number.POSITIVE_INFINITY);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test -- CountryBorders.style`
Expected: FAIL — `BORDER_WIDTH`/`borderPolylineOptions` not exported.

- [ ] **Step 3: Implement — export constants + options builder, use them in the loop**

In `CountryBorders.tsx`, add near the top (after the imports, before `interface Props`):

```ts
/** Wider than the old 0.6 so the line reads over Google photoreal terrain. */
export const BORDER_WIDTH = 1.8;

/** Per-polyline options. disableDepthTestDistance=Infinity draws the border on
 *  top of the 3D tiles/terrain instead of being occluded by it. */
export function borderPolylineOptions(
  positions: Cesium.Cartesian3[],
  material: Cesium.Material,
) {
  return {
    positions,
    width: BORDER_WIDTH,
    material,
    disableDepthTestDistance: Number.POSITIVE_INFINITY,
  };
}
```

Change the colour to a brighter neutral (not an accent), and use the options builder. Replace lines 28–47 (the `cssVar`/`stoneColor`/`material` block through the `collection.add(...)` call):

```ts
      const cssVar = getComputedStyle(document.documentElement)
        .getPropertyValue("--bone")
        .trim();
      // Bright neutral (bone), not an accent colour — an accent would read like
      // a data layer. Higher alpha than the old stone@0.7 for legibility.
      const lineColor = Cesium.Color.fromCssColorString(cssVar || "#d4cdc0").withAlpha(0.85);
      const material = Cesium.Material.fromType("Color", { color: lineColor });

      const collection = new Cesium.PolylineCollection();
      for (const f of fc.features) {
        const geom = f.geometry as GeoJSON.Polygon | GeoJSON.MultiPolygon | null;
        if (!geom) continue;

        const polygons = geom.type === "Polygon" ? [geom.coordinates] : geom.coordinates;
        for (const poly of polygons) {
          for (const ring of poly as number[][][]) {
            const positions = ring.map((coord) => {
              const lon = coord[0]!;
              const lat = coord[1]!;
              return Cesium.Cartesian3.fromDegrees(lon, lat);
            });
            collection.add(borderPolylineOptions(positions, material));
          }
        }
      }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm run test -- CountryBorders.style`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add services/frontend/src/components/globe/visual-layers/CountryBorders.tsx \
        services/frontend/src/components/globe/visual-layers/__tests__/CountryBorders.style.test.ts
git commit -m "fix(globe): brighter, depth-test-off country borders readable over 3D tiles (P2)"
```

---

### Task 4: Full capital dataset for all countries (P4)

**Background (verified):** `public/country-endonyms.json` has `_topoIndex` (M.49 → ISO3, 177 keys but only 8 mapped; rest `null`) and `countries` (ISO3 → `{iso3, m49, capital:{name,lat,lon}}`, only 8 entries). The capital pulse renders only for countries whose M.49 resolves to an ISO3 that has a capital. We must fill both maps. Source: **Natural Earth (public domain)**.

**Files:**
- Create: `services/frontend/scripts/gen-capitals.mjs`
- Modify: `services/frontend/public/country-endonyms.json` (generated)
- Test: `services/frontend/src/components/globe/__tests__/capitalCoverage.test.ts`

- [ ] **Step 1: Write the failing completeness test (against real TopoJSON keys)**

```ts
// services/frontend/src/components/globe/__tests__/capitalCoverage.test.ts
import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

// Disputed/de-facto territories in countries-110m.json that have no clean ISO3
// and/or no Natural Earth admin-0 capital. Each is intentionally left unmapped.
const CAPITAL_EXCEPTIONS = new Set<string>(["Somaliland", "N. Cyprus"]);

function load(rel: string) {
  const p = fileURLToPath(new URL(`../../../../public/${rel}`, import.meta.url));
  return JSON.parse(readFileSync(p, "utf8"));
}

describe("capital coverage", () => {
  it("every real countries-110m feature resolves to a capital or is an explicit exception", () => {
    const topo = load("countries-110m.json");
    const endo = load("country-endonyms.json");
    const topoIndex: Record<string, string | null> = endo._topoIndex;
    const countries: Record<string, { capital: { name: string; lat: number; lon: number } | null }> =
      endo.countries;

    // Derive each feature's lookup key EXACTLY like useCountryHitTest does at
    // runtime — f.id ?? properties.name — so this asserts real topo coverage
    // (and catches a missing _topoIndex entry), not the index against itself.
    const geometries: Array<{ id?: string | number; properties?: { name?: string } }> =
      topo.objects.countries.geometries;
    const keys = geometries.map((g) =>
      g.id != null ? String(g.id) : (g.properties?.name ?? ""),
    );

    const missing: string[] = [];
    for (const key of keys) {
      if (CAPITAL_EXCEPTIONS.has(key)) continue;
      const iso3 = topoIndex[key] ?? null; // must be in the index AND mapped to ISO3
      const cap = iso3 ? countries[iso3]?.capital : null;
      const ok =
        !!cap &&
        typeof cap.name === "string" &&
        cap.name.length > 0 &&
        Number.isFinite(cap.lat) &&
        Math.abs(cap.lat) <= 90 &&
        Number.isFinite(cap.lon) &&
        Math.abs(cap.lon) <= 180;
      if (!ok) missing.push(key);
    }
    expect(missing).toEqual([]);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test -- capitalCoverage`
Expected: FAIL — ~167 unmapped M.49 keys listed in `missing`.

- [ ] **Step 3: Write the generator script**

```js
// services/frontend/scripts/gen-capitals.mjs
// Regenerates public/country-endonyms.json capital coverage from Natural Earth
// (public domain). Requires network. Run: node scripts/gen-capitals.mjs
// Preserves the 8 existing curated entries; only fills gaps.
import { readFileSync, writeFileSync } from "node:fs";

const NE = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson";
const COUNTRIES_URL = `${NE}/ne_110m_admin_0_countries.geojson`;
const PLACES_URL = `${NE}/ne_10m_populated_places_simple.geojson`;

// Manual overrides for features whose M.49 key is a name (no f.id in topo) or
// that Natural Earth keys differently. Kosovo has a de-facto capital + XKX code.
const OVERRIDES = {
  // topoIndexKey: { iso3, capital: { name, lat, lon } }
  Kosovo: { iso3: "XKX", capital: { name: "Pristina", lat: 42.6727, lon: 21.1655 } },
};

const endoPath = new URL("../public/country-endonyms.json", import.meta.url);
const endo = JSON.parse(readFileSync(endoPath, "utf8"));

const fetchJson = async (u) => (await fetch(u)).json();
const [countries, places] = await Promise.all([fetchJson(COUNTRIES_URL), fetchJson(PLACES_URL)]);

// CRITICAL: topo f.id and _topoIndex keys are ZERO-PADDED 3-digit M.49 strings
// ("032" Argentina, "004" Afghanistan, "124" Canada). Build the M.49->ISO3 map
// with the SAME padded format or every <100 key misses. ISO_A3 is "-99" for a
// few NE features (FRA, NOR, ...) whose real code lives in ADM0_A3 — pick the
// first non-"-99" code.
const pad3 = (v) => String(parseInt(String(v), 10)).padStart(3, "0");
const pickA3 = (p) =>
  [p.ISO_A3, p.iso_a3, p.ADM0_A3, p.adm0_a3].find((v) => v && v !== "-99");
const iso3ByM49 = {};
for (const f of countries.features) {
  const p = f.properties;
  const raw = p.ISO_N3 ?? p.iso_n3;
  const a3 = pickA3(p);
  if (raw == null || !a3) continue;
  const n3 = pad3(raw); // 32 / "32" / "032" -> "032"
  if (n3 !== "NaN") iso3ByM49[n3] = a3;
}

// ISO3 → capital (prefer "Admin-0 capital", fall back to alt)
const capByIso3 = {};
const rank = (fcla) => (fcla === "Admin-0 capital" ? 0 : fcla?.startsWith("Admin-0 capital") ? 1 : 2);
for (const f of places.features) {
  const p = f.properties;
  if (!String(p.featurecla ?? "").startsWith("Admin-0 capital")) continue;
  const a3 = p.adm0_a3 ?? p.ADM0_A3;
  if (!a3 || a3 === "-99") continue;
  const lat = Number(p.latitude ?? p.LATITUDE ?? f.geometry?.coordinates?.[1]);
  const lon = Number(p.longitude ?? p.LONGITUDE ?? f.geometry?.coordinates?.[0]);
  const name = p.name ?? p.NAME;
  const cand = { name, lat, lon, _r: rank(p.featurecla) };
  if (!capByIso3[a3] || cand._r < capByIso3[a3]._r) capByIso3[a3] = cand;
}

let filled = 0;
for (const [m49, existing] of Object.entries(endo._topoIndex)) {
  if (existing) continue; // keep curated mappings
  let iso3 = iso3ByM49[m49] ?? null;
  let capital = iso3 ? capByIso3[iso3] : null;
  if (OVERRIDES[m49]) {
    iso3 = OVERRIDES[m49].iso3;
    capital = OVERRIDES[m49].capital;
  }
  if (iso3 && capital && Number.isFinite(capital.lat) && Number.isFinite(capital.lon)) {
    endo._topoIndex[m49] = iso3;
    endo.countries[iso3] = {
      iso3,
      m49: /^\d+$/.test(m49) ? m49 : (endo.countries[iso3]?.m49 ?? ""),
      capital: { name: capital.name, lat: capital.lat, lon: capital.lon },
    };
    filled++;
  }
}

writeFileSync(endoPath, JSON.stringify(endo, null, 2) + "\n");
console.log(`filled ${filled} countries; total countries=${Object.keys(endo.countries).length}`);
```

- [ ] **Step 4: Run the generator + verify coverage**

Run:
```bash
cd services/frontend && node scripts/gen-capitals.mjs
npm run test -- capitalCoverage
```
Expected: generator prints `filled ~167 ...`; test PASSES. If a handful of M.49 keys remain in `missing` because Natural Earth lacks a clean ISO3/capital for them (e.g. tiny states, disputed areas), add each to `CAPITAL_EXCEPTIONS` in the test **or** add an `OVERRIDES` entry with a sourced capital — decide per entry, do not blanket-skip. Re-run until green.

- [ ] **Step 5: Sanity-check a few capitals render correctly**

Run: `npm run type-check`
Spot-check the JSON: confirm e.g. `FRA`/`BRA`/`AUS` now have a `capital` with plausible lat/lon (Paris ~48.85, Brasília ~-15.79, Canberra ~-35.28).

- [ ] **Step 6: Commit**

```bash
git add services/frontend/scripts/gen-capitals.mjs \
        services/frontend/public/country-endonyms.json \
        services/frontend/src/components/globe/__tests__/capitalCoverage.test.ts
git commit -m "feat(globe): full country-capital dataset from Natural Earth (P4)"
```

---

### Task 5: Cartouche no longer hidden by the Inspector Panel (P5)

**Decision (from spec):** Move the cartouche left; the Inspector Panel stays right (stable app chrome). The country-name cartouche position lives in CSS, not the TSX.

**Files:**
- Modify: `services/frontend/src/components/worldview/worldviewHudLoader.css` (`.cartouche-country`, mobile rule)

- [ ] **Step 1: Reposition `.cartouche-country` to the left**

In `worldviewHudLoader.css`, replace the `.cartouche-country` rule (line 230):

```css
.cartouche-country { left: 48px; top: 46%; transform: translateY(-50%); text-align: left; color: var(--bone); font-family: "Hanken Grotesk", sans-serif; }
```

(was `right: 36px; ... text-align: right;`). The 96px `.cartouche-title` now grows rightward from the left edge, clear of the Inspector Panel's right zone (`right:16, width:360`).

- [ ] **Step 2: Add a mobile rule so the title doesn't overflow narrow screens**

Append near the other cartouche rules in `worldviewHudLoader.css`:

```css
@media (max-width: 768px) {
  .cartouche-country { left: 16px; top: 38%; }
  .cartouche-title { font-size: 56px; }
}
```

- [ ] **Step 3: Verify build + manual visual check**

Run: `npm run build`
Expected: build succeeds.
Manual: `npm run dev`, open WorldView, click a country (with City Buildings ON), confirm the large country name sits on the left and is fully visible while the Inspector Panel is open on the right. (P5 is layout-only; no unit test — jsdom does not compute stylesheet layout.)

- [ ] **Step 4: Commit**

```bash
git add services/frontend/src/components/worldview/worldviewHudLoader.css
git commit -m "fix(worldview): move country cartouche left so the inspector panel no longer covers it (P5)"
```

---

## Cluster B — Timeslider (P1)

### Task 6: Transport helpers (pure)

**Files:**
- Create: `services/frontend/src/components/time/transport.ts`
- Test: `services/frontend/src/components/time/__tests__/transport.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
// services/frontend/src/components/time/__tests__/transport.test.ts
import { describe, it, expect } from "vitest";
import { signedSpeed, stepTargetMs } from "../transport";

describe("transport helpers", () => {
  it("signedSpeed combines UI magnitude with direction (magnitude is always positive)", () => {
    expect(signedSpeed(5, 1)).toBe(5);
    expect(signedSpeed(5, -1)).toBe(-5);
    expect(signedSpeed(-5, -1)).toBe(-5); // abs() guards a stray negative magnitude
    expect(signedSpeed(0.5, 1)).toBe(0.5);
  });

  it("stepTargetMs advances/retreats by exactly one bucket", () => {
    // span 1000ms over 10 buckets => 100ms per bucket
    expect(stepTargetMs(500, 0, 1000, 10, 1)).toBe(600);
    expect(stepTargetMs(500, 0, 1000, 10, -1)).toBe(400);
  });

  it("stepTargetMs clamps at the window bounds (no wraparound)", () => {
    expect(stepTargetMs(950, 0, 1000, 10, 1)).toBe(1000); // would be 1050 -> clamp
    expect(stepTargetMs(50, 0, 1000, 10, -1)).toBe(0); // would be -50 -> clamp
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test -- transport`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

```ts
// services/frontend/src/components/time/transport.ts

/** Playback direction: +1 forward in time, -1 backward. */
export type Direction = 1 | -1;

/** Effective signed clock multiplier from a UI magnitude + direction.
 *  Magnitude is taken as absolute so the UI never has to track a sign. */
export function signedSpeed(magnitude: number, direction: Direction): number {
  return Math.abs(magnitude) * direction;
}

/** Seek target one bucket away from currentMs, clamped to [start, end].
 *  No wraparound — at a bound the target is the bound. */
export function stepTargetMs(
  currentMs: number,
  rangeStartMs: number,
  rangeEndMs: number,
  bucketCount: number,
  direction: Direction,
): number {
  const span = Math.max(rangeEndMs - rangeStartMs, 1);
  const bucketMs = span / Math.max(bucketCount, 1);
  const next = currentMs + bucketMs * direction;
  return Math.min(rangeEndMs, Math.max(rangeStartMs, next));
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm run test -- transport`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add services/frontend/src/components/time/transport.ts \
        services/frontend/src/components/time/__tests__/transport.test.ts
git commit -m "feat(time): pure transport helpers (signed speed + clamped step) (P1)"
```

---

### Task 7: Full transport UI + wiring (P1)

**Files:**
- Modify: `services/frontend/src/components/time/ChronikTimeline.tsx` (props + button cluster + speed select)
- Modify: `services/frontend/src/components/time/ChronikTimeline.css` (speed select style)
- Modify: `services/frontend/src/components/time/ScrubberMount.tsx` (wire handlers to TimeContext)
- Test: `services/frontend/src/components/time/__tests__/ScrubberMount.test.tsx` (extend)
- Test: `services/frontend/src/components/time/__tests__/ChronikTimeline.test.tsx` (existing `base` must gain the new required props)

- [ ] **Step 1: Extend ChronikTimeline props + render the transport cluster**

In `ChronikTimeline.tsx`, add to `ChronikTimelineProps` (after `onPreset`):

```ts
  speed: number; // signed clock speed (sign = direction, |value| = magnitude)
  onStepBack: () => void;
  onStepForward: () => void;
  onReverse: () => void;
  onForward: () => void;
  onSetSpeedMagnitude: (magnitude: number) => void;
```

Add them to the destructured params in the function signature.

Replace the single play toggle button (lines 95–98) with the transport cluster (keep `onNow`):

```tsx
        <button type="button" className="chronik__btn" aria-label="step back" onClick={onStepBack}>«</button>
        <button
          type="button"
          className={`chronik__btn${playing && speed < 0 ? " chronik__btn--on" : ""}`}
          aria-label="reverse play"
          onClick={onReverse}
        >◀◀</button>
        <button type="button" className="chronik__btn" aria-label="toggle play" onClick={onTogglePlay}>
          {playing ? "⏸" : "▶"}
        </button>
        <button
          type="button"
          className={`chronik__btn${playing && speed > 0 ? " chronik__btn--on" : ""}`}
          aria-label="forward play"
          onClick={onForward}
        >▶▶</button>
        <button type="button" className="chronik__btn" aria-label="step forward" onClick={onStepForward}>»</button>
        <select
          className="chronik__speed"
          aria-label="speed"
          value={Math.abs(speed)}
          onChange={(e) => onSetSpeedMagnitude(Number(e.target.value))}
        >
          <option value={0.5}>0.5×</option>
          <option value={1}>1×</option>
          <option value={5}>5×</option>
          <option value={20}>20×</option>
        </select>
        <button type="button" className="chronik__btn" aria-label="now" onClick={onNow}>⏭ NOW</button>
```

- [ ] **Step 1b: Update the existing ChronikTimeline test so it still compiles**

The new props are **required**, so the existing `base` object in `src/components/time/__tests__/ChronikTimeline.test.tsx` (it renders `<ChronikTimeline {...base} />` in several tests) must provide them. Add to the `base` object (after `onPreset: vi.fn(),`):

```ts
  speed: 1,
  onStepBack: vi.fn(),
  onStepForward: vi.fn(),
  onReverse: vi.fn(),
  onForward: vi.fn(),
  onSetSpeedMagnitude: vi.fn(),
```

Run: `npm run test -- ChronikTimeline && npm run type-check`
Expected: the existing ChronikTimeline tests still PASS and type-check is clean (no missing-prop errors).

- [ ] **Step 2: Style the speed select**

Append to `ChronikTimeline.css`:

```css
.chronik__speed {
  height: 22px;
  background: transparent;
  color: var(--bone, #d4cdc0);
  border: 1px solid var(--briefing-hair, rgba(212, 205, 192, 0.25));
  border-radius: 3px;
  font-family: "Martian Mono", ui-monospace, monospace;
  font-size: 10px;
  padding: 0 4px;
}
```

- [ ] **Step 3: Wire the handlers in ScrubberMount**

In `ScrubberMount.tsx`, extend the `useTime()` destructure (line 33) to add `speed`, `setSpeed`:

```ts
  const { mode, cursorMs, playing, speed, seek, pause, play, setMode, setReplayWindow, setSpeed } = useTime();
```

Add the import (after line 5):

```ts
import { signedSpeed, stepTargetMs, type Direction } from "./transport";
```

Before the `return`, add the handlers:

```ts
  const coarseStartMs = Date.parse(coarse.tStart);
  const coarseEndMs = Date.parse(coarse.tEnd);
  const bucketCount = data?.buckets?.length ?? 120;
  const magnitude = Math.abs(speed) || 1;

  // Reverse/fast playback only has meaning in replay (live clock ignores the
  // multiplier). Entering replay over the current coarse window if needed.
  const ensureReplay = () => {
    if (mode !== "replay") {
      setBrush({ startMs: coarseStartMs, endMs: coarseEndMs });
      setReplayWindow(coarseStartMs, coarseEndMs);
      setMode("replay");
    }
  };

  const stepBy = (dir: Direction) => {
    pause();
    seek(stepTargetMs(cursorMs, coarseStartMs, coarseEndMs, bucketCount, dir));
  };
```

Add the new props to the `<ChronikTimeline ... />` element (alongside the existing ones):

```tsx
      speed={speed}
      onStepBack={() => stepBy(-1)}
      onStepForward={() => stepBy(1)}
      onReverse={() => { ensureReplay(); setSpeed(signedSpeed(magnitude, -1)); play(); }}
      onForward={() => { setSpeed(signedSpeed(magnitude, 1)); play(); }}
      onSetSpeedMagnitude={(m) => setSpeed(signedSpeed(m, speed < 0 ? -1 : 1))}
```

`onForward` ALWAYS sets a positive speed (not just in replay), so a prior Reverse
can never leave `speed < 0` behind — in live the clock ignores the multiplier, but
the `speed` STATE must not stay negative or the UI would keep showing reverse and a
later replay window would inherit a backward multiplier.

Also reset direction to forward wherever forward/live intent is implied. In the
EXISTING `enterReplay` helper (brush-created window plays forward by default):

```tsx
  const enterReplay = (startMs: number, endMs: number, cursorTarget: number) => {
    setBrush({ startMs, endMs });
    setReplayWindow(startMs, endMs);
    setMode("replay");
    setSpeed(Math.abs(speed) || 1); // fresh brush window plays forward
    seek(cursorTarget);
  };
```

And in the EXISTING `onNow` handler (NOW = live + forward), add the reset before `play()`:

```tsx
      onNow={() => {
        setBrush(null);
        seek(Date.now());
        setMode("live");
        setSpeed(Math.abs(speed) || 1); // clear any leftover reverse direction
        play();
      }}
```

- [ ] **Step 4: Extend the ScrubberMount test**

Add these cases to `src/components/time/__tests__/ScrubberMount.test.tsx` (inside the existing `describe`, reusing `fakeClockViewer` + the `HIST`/`api` mocks already in the file):

```ts
  it("reverse-play sets a negative multiplier and animates", () => {
    vi.spyOn(api, "getTimeHistogram").mockResolvedValue(HIST as never);
    const { viewer, clock } = fakeClockViewer();
    const Comp = wrap(viewer, { onSelectEvent: vi.fn(), onTimelineData: vi.fn() });
    render(<Comp />);
    act(() => { fireEvent.click(screen.getByLabelText("reverse play")); });
    expect(clock.multiplier).toBeLessThan(0);
    expect(clock.shouldAnimate).toBe(true);
  });

  it("forward-play after reverse restores a positive multiplier", () => {
    vi.spyOn(api, "getTimeHistogram").mockResolvedValue(HIST as never);
    const { viewer, clock } = fakeClockViewer();
    const Comp = wrap(viewer, { onSelectEvent: vi.fn(), onTimelineData: vi.fn() });
    render(<Comp />);
    act(() => { fireEvent.click(screen.getByLabelText("reverse play")); });
    act(() => { fireEvent.click(screen.getByLabelText("forward play")); });
    expect(clock.multiplier).toBeGreaterThan(0);
  });

  it("step forward pauses and advances the cursor", () => {
    vi.spyOn(api, "getTimeHistogram").mockResolvedValue(HIST as never);
    const { viewer, clock } = fakeClockViewer();
    const before = Cesium.JulianDate.toDate(clock.currentTime).getTime();
    const Comp = wrap(viewer, { onSelectEvent: vi.fn(), onTimelineData: vi.fn() });
    render(<Comp />);
    act(() => { fireEvent.click(screen.getByLabelText("step forward")); });
    expect(clock.shouldAnimate).toBe(false);
    const after = Cesium.JulianDate.toDate(clock.currentTime).getTime();
    expect(after).toBeGreaterThan(before);
  });

  it("NOW after reverse clears the reverse direction (speed back to positive)", () => {
    vi.spyOn(api, "getTimeHistogram").mockResolvedValue(HIST as never);
    const { viewer, clock } = fakeClockViewer();
    const Comp = wrap(viewer, { onSelectEvent: vi.fn(), onTimelineData: vi.fn() });
    render(<Comp />);
    act(() => { fireEvent.click(screen.getByLabelText("reverse play")); });
    act(() => { fireEvent.click(screen.getByLabelText("now")); });
    expect(clock.multiplier).toBeGreaterThan(0); // no stale negative multiplier
  });
```

- [ ] **Step 5: Run tests + type-check**

Run: `npm run test -- ScrubberMount transport && npm run type-check`
Expected: PASS; type-check clean.

- [ ] **Step 6: Commit**

```bash
git add services/frontend/src/components/time/ChronikTimeline.tsx \
        services/frontend/src/components/time/ChronikTimeline.css \
        services/frontend/src/components/time/ScrubberMount.tsx \
        services/frontend/src/components/time/__tests__/ScrubberMount.test.tsx \
        services/frontend/src/components/time/__tests__/ChronikTimeline.test.tsx
git commit -m "feat(time): full timeslider transport — reverse/forward play, steps, speed (P1)"
```

---

## Cluster C — Briefing & War Room

### Task 8: Delete briefings (P6)

**Decision (from spec + review):** Remove from state only after `deleteReport(id)` succeeds; on failure keep the report. If the deleted report was selected, select the next one (or none). Drop its cached chat messages. The behaviour is extracted into two directly-testable units instead of mounting the whole BriefingPage (it depends on react-router `useNavigate` + the `useIntel()` SSE hook, so a full render test is brittle): a pure reducer `applyDelete` that returns BOTH the next reports AND the next selection (so we never nest a `setSelectedId` inside a `setReports` updater), and an async orchestrator `runDeleteDossier` (confirm gate → API → outcome). The orchestrator tests assert exactly what a render test would — confirm honoured, `deleteReport` called, report removed on success, report kept on failure.

**Files:**
- Create: `services/frontend/src/pages/briefingDelete.ts`
- Test: `services/frontend/src/pages/__tests__/briefingDelete.test.ts`
- Modify: `services/frontend/src/pages/BriefingPage.tsx` (`deleteDossier` wrapper + button)
- Modify: `services/frontend/src/pages/briefingPage.css` (danger style)

- [ ] **Step 1: Write the failing tests (reducer + orchestrator)**

```ts
// services/frontend/src/pages/__tests__/briefingDelete.test.ts
import { describe, it, expect, vi } from "vitest";
import type { ReportRecord } from "../../types";
import { applyDelete, runDeleteDossier } from "../briefingDelete";

const mk = (id: string, title = id.toUpperCase()) =>
  ({ id, title }) as unknown as ReportRecord;
const reports = [mk("a"), mk("b"), mk("c")];

describe("applyDelete (reducer)", () => {
  it("keeps the current selection when a different report is deleted", () => {
    const r = applyDelete(reports, "a", "c");
    expect(r.reports.map((x) => x.id)).toEqual(["a", "b"]);
    expect(r.selectedId).toBe("a");
  });

  it("moves to the next report when the selected one is deleted", () => {
    expect(applyDelete(reports, "b", "b").selectedId).toBe("c");
  });

  it("falls back to the previous when deleting the last selected", () => {
    expect(applyDelete(reports, "c", "c").selectedId).toBe("b");
  });

  it("returns empty selection when the only report is deleted", () => {
    const r = applyDelete([mk("a")], "a", "a");
    expect(r.reports).toEqual([]);
    expect(r.selectedId).toBe("");
  });
});

describe("runDeleteDossier (orchestrator)", () => {
  it("does nothing when the confirm dialog is declined", async () => {
    const deleteReportFn = vi.fn().mockResolvedValue(undefined);
    const out = await runDeleteDossier({
      reports, selectedId: "b", report: mk("b"),
      confirm: () => false, deleteReportFn,
    });
    expect(out.status).toBe("cancelled");
    expect(deleteReportFn).not.toHaveBeenCalled();
  });

  it("calls the API and removes the report on success", async () => {
    const deleteReportFn = vi.fn().mockResolvedValue(undefined);
    const out = await runDeleteDossier({
      reports, selectedId: "b", report: mk("b"),
      confirm: () => true, deleteReportFn,
    });
    expect(deleteReportFn).toHaveBeenCalledWith("b");
    expect(out.status).toBe("deleted");
    if (out.status === "deleted") {
      expect(out.reports.map((x) => x.id)).toEqual(["a", "c"]);
      expect(out.selectedId).toBe("c");
      expect(out.droppedChatId).toBe("b");
    }
  });

  it("keeps the report when the API call fails", async () => {
    const deleteReportFn = vi.fn().mockRejectedValue(new Error("500"));
    const out = await runDeleteDossier({
      reports, selectedId: "b", report: mk("b"),
      confirm: () => true, deleteReportFn,
    });
    expect(out.status).toBe("error");
    // caller keeps existing state — the outcome carries no replacement reports
    expect("reports" in out).toBe(false);
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npm run test -- briefingDelete`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement the reducer + orchestrator**

```ts
// services/frontend/src/pages/briefingDelete.ts
import type { ReportRecord } from "../types";

export interface DeleteState {
  reports: ReportRecord[];
  selectedId: string;
}

/** Pure reducer: remove `deletedId` and return BOTH the next reports list and
 *  the next selection. If the deleted report wasn't selected, selection is
 *  unchanged. Otherwise pick the next report, else the previous, else "". */
export function applyDelete(
  reports: ReportRecord[],
  selectedId: string,
  deletedId: string,
): DeleteState {
  const idx = reports.findIndex((r) => r.id === deletedId);
  const remaining = reports.filter((r) => r.id !== deletedId);
  let nextSelected = selectedId;
  if (selectedId === deletedId) {
    nextSelected =
      remaining.length === 0 ? "" : (remaining[Math.min(idx, remaining.length - 1)]?.id ?? "");
  }
  return { reports: remaining, selectedId: nextSelected };
}

export interface DeleteDeps {
  reports: ReportRecord[];
  selectedId: string;
  report: ReportRecord;
  confirm: (message: string) => boolean;
  deleteReportFn: (id: string) => Promise<void>;
}

export type DeleteOutcome =
  | { status: "cancelled" }
  | { status: "deleted"; reports: ReportRecord[]; selectedId: string; droppedChatId: string }
  | { status: "error"; error: unknown };

/** Confirm → delete via API → compute next state. Removes from state only on
 *  success; on failure returns `error` and the caller keeps its existing state. */
export async function runDeleteDossier(deps: DeleteDeps): Promise<DeleteOutcome> {
  const { reports, selectedId, report, confirm, deleteReportFn } = deps;
  if (!confirm(`Delete dossier "${report.title}"? This cannot be undone.`)) {
    return { status: "cancelled" };
  }
  try {
    await deleteReportFn(report.id); // remove from state only after success
    const next = applyDelete(reports, selectedId, report.id);
    return {
      status: "deleted",
      reports: next.reports,
      selectedId: next.selectedId,
      droppedChatId: report.id,
    };
  } catch (error) {
    return { status: "error", error }; // report stays in state
  }
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npm run test -- briefingDelete`
Expected: PASS (7 tests).

- [ ] **Step 5: Wire into BriefingPage (no nested setState updaters)**

In `BriefingPage.tsx`, add `deleteReport` to the existing `services/api` import (it already imports `createReport`/`updateReport`), and import the orchestrator:

```ts
import { runDeleteDossier } from "./briefingDelete";
```

Add the thin wrapper after `promoteToWorldview` (line 277). It reads the current `reports`/`selectedId` from scope and applies the two state updates SEPARATELY (no updater nesting):

```ts
  const deleteDossier = async (report: ReportRecord) => {
    const outcome = await runDeleteDossier({
      reports,
      selectedId,
      report,
      confirm: (m) => window.confirm(m),
      deleteReportFn: deleteReport,
    });
    if (outcome.status === "deleted") {
      setReports(outcome.reports);
      setSelectedId(outcome.selectedId);
      setChatByReport((prev) => {
        const next = { ...prev };
        delete next[outcome.droppedChatId];
        return next;
      });
      setReportsError(null);
    } else if (outcome.status === "error") {
      setReportsError(normalizeError(outcome.error));
    }
  };
```

Add the button to `.briefing-actions-row` (after the "Promote to Worldview" button, line 439):

```tsx
                <button
                  type="button"
                  className="briefing-link briefing-link--danger"
                  onClick={() => void deleteDossier(selectedReport)}
                >
                  ▸ Delete dossier
                </button>
```

Add a danger style to `services/frontend/src/pages/briefingPage.css`:

```css
.briefing-link--danger { color: var(--capital-red, #e63a26); }
```

- [ ] **Step 6: Run tests + type-check**

Run: `npm run test -- briefingDelete && npm run type-check`
Expected: PASS; type-check clean.

- [ ] **Step 7: Commit**

```bash
git add services/frontend/src/pages/briefingDelete.ts \
        services/frontend/src/pages/__tests__/briefingDelete.test.ts \
        services/frontend/src/pages/BriefingPage.tsx \
        services/frontend/src/pages/briefingPage.css
git commit -m "feat(briefing): delete dossiers — reducer + orchestrator, delete-on-success, reselect (P6)"
```

---

### Task 9: Munin text readability (P7)

**Decision (from spec):** Keep Instrument Serif, but upright (not italic) and ≥15px. Do NOT touch the global `.serif` utility — only Munin-specific selectors.

**Files:**
- Modify: `services/frontend/src/components/warroom/MuninStreamQuadrant.tsx` (`hypothesisStyle`)
- Modify: `services/frontend/src/pages/briefingPage.css` (munin-scoped override)
- Test: `services/frontend/src/components/warroom/__tests__/muninReadability.test.tsx`

- [ ] **Step 1: Write the failing test (War Room inline style — reliably assertable)**

```tsx
// services/frontend/src/components/warroom/__tests__/muninReadability.test.tsx
import { describe, it, expect, vi } from "vitest";
import { render } from "@testing-library/react";
import { MuninStreamQuadrant } from "../MuninStreamQuadrant";

describe("Munin hypothesis readability (P7)", () => {
  it("renders the hypothesis upright and at >= 15px", () => {
    const { container } = render(
      <MuninStreamQuadrant toolCalls={[]} hypothesis="Test working hypothesis" onAsk={vi.fn()} />,
    );
    const node = container.querySelector('[data-part="hypothesis"]') as HTMLElement;
    expect(node).toBeTruthy();
    expect(node.style.fontStyle).not.toBe("italic");
    expect(parseFloat(node.style.fontSize)).toBeGreaterThanOrEqual(15);
  });
});
```

(`MuninStreamQuadrantProps` = `{ toolCalls: MuninToolCall[]; hypothesis: string; onAsk: (p: string) => void; busy?: boolean }`; the assertion targets only the `[data-part="hypothesis"]` node.)

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test -- muninReadability`
Expected: FAIL — fontStyle is `italic`, fontSize is `12px`.

- [ ] **Step 3: Fix the War Room style**

In `MuninStreamQuadrant.tsx`, update `hypothesisStyle` (lines 45–48):

```ts
const hypothesisStyle: CSSProperties = {
  fontFamily: '"Instrument Serif", serif',
  fontStyle: "normal",
  fontSize: "15px",
  lineHeight: 1.5,
```

(keep the remaining properties of the object unchanged — `color: var(--bone)` etc.)

- [ ] **Step 4: Fix the Briefing munin messages (munin-scoped, not global `.serif`)**

In `services/frontend/src/pages/briefingPage.css`, add AFTER the existing `.briefing-chat-item p.serif { font-style: italic; }` rule (line 422) so it wins by source order:

```css
/* P7: Munin replies stay Instrument Serif (via .serif) but upright + larger. */
.briefing-chat-item.is-munin p {
  font-style: normal;
  font-size: 1rem;
  line-height: 1.62;
}
```

Do not modify the global `.serif` rule in `hlidskjalf.css`.

- [ ] **Step 5: Run test + build**

Run: `npm run test -- muninReadability && npm run build`
Expected: PASS; build succeeds.

- [ ] **Step 6: Commit**

```bash
git add services/frontend/src/components/warroom/MuninStreamQuadrant.tsx \
        services/frontend/src/pages/briefingPage.css \
        services/frontend/src/components/warroom/__tests__/muninReadability.test.tsx
git commit -m "fix(warroom): Munin text upright + >=15px for readability (P7)"
```

---

## Final verification (after all tasks)

- [ ] **Full test suite:** `cd services/frontend && npm run test` → all green.
- [ ] **Lint:** `npm run lint` → clean.
- [ ] **Types:** `npm run type-check` → clean.
- [ ] **Build:** `npm run build` → succeeds.
- [ ] **Manual smoke (`npm run dev`):**
  - Toggle City Buildings ON → click a country → almanac opens (P3); borders are clearly visible over the 3D tiles (P2); the capital pulses with a red dot + city name for arbitrary countries, not just 8 (P4); the country name is fully visible left of the Inspector Panel (P5).
  - CHRONIK: reverse/forward play run the clock both directions and clamp at the window edges; step buttons nudge one bucket; speed select changes pace (P1).
  - Briefing Room: create a dossier, delete it (confirm dialog), selection moves sensibly (P6).
  - War Room: Munin hypothesis text is upright and clearly larger (P7).

## Review gate (mandatory, per project policy)

After implementation: run the two-stage review (spec-conformance + quality) on the branch before any merge. Reviews stay solo/lean unless a Workflow is explicitly opted into with a cost estimate.
