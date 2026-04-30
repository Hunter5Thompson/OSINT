# Worldview Layer-Design Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the visual layer-stack and polymorphic Spotlight (circle + country) for the Worldview as specified in `docs/superpowers/specs/2026-04-30-worldview-layer-design.md`.

**Architecture:** Extend the existing CesiumJS-based Worldview without touching the 16 existing data-layer components. Spotlight rendering uses `Cesium.GroundPrimitive` + `Material.fabric.source` shaders over the unchanged ImageryLayer stack. Click-routing flows through a single extended `EntityClickHandler`; pure-logic units (reducer, hit-test) are TDD'd, Cesium-rendered units get shape-tests plus manual visual verification (visual regression is out-of-scope per spec §12.2).

**Tech Stack:** React 19 + TypeScript + Vite 6 + CesiumJS 1.132 + topojson-client + rbush + Vitest + Testing Library.

---

## File Structure

**New files:**
- `services/frontend/src/components/globe/spotlight/SpotlightContext.tsx` — reducer + provider
- `services/frontend/src/components/globe/spotlight/SpotlightOverlay.tsx` — `GroundPrimitive` rendering for circle + country
- `services/frontend/src/components/globe/spotlight/SpotlightCartouche.tsx` — adaptive DOM overlay
- `services/frontend/src/components/globe/spotlight/HudFrame.tsx` — corners/crosshair/eyebrow/time/scale/coords
- `services/frontend/src/components/globe/spotlight/CountryHeader.tsx` — minimal country header for `InspectorPanel`
- `services/frontend/src/components/globe/hooks/pointInPolygon.ts` — Polygon + MultiPolygon ray-cast
- `services/frontend/src/components/globe/hooks/useCountryHitTest.ts` — rbush + M49→ISO3 resolution
- `services/frontend/src/components/globe/hooks/useSpotlightTrigger.ts` — zoom + search trigger plumbing
- `services/frontend/src/components/globe/visual-layers/Graticule.tsx` — Layer 03
- `services/frontend/src/components/globe/visual-layers/CountryBorders.tsx` — Layer 04
- `services/frontend/public/country-endonyms.json` — generated endonym JSON
- `scripts/build-country-endonyms.mjs` — one-shot build script

**Modified files:**
- `services/frontend/package.json` — add `rbush` direct dep
- `services/frontend/src/theme/hlidskjalf.css` — append 7 new tokens
- `services/frontend/src/components/globe/EntityClickHandler.tsx` — dispatch to Spotlight + run country hit-test
- `services/frontend/src/components/worldview/LayersPanel.tsx` — restructure into 4 groups
- `services/frontend/src/components/worldview/InspectorPanel.tsx` — render `CountryHeader` in country-mode
- `services/frontend/src/pages/WorldviewPage.tsx` — mount `SpotlightProvider` + new visual layers + new chrome
- `services/frontend/src/components/layers/*.tsx` — token color swap (16 files, batched in Task 15)

**Test files (new):**
- `services/frontend/src/components/globe/spotlight/__tests__/SpotlightContext.test.tsx`
- `services/frontend/src/components/globe/hooks/__tests__/pointInPolygon.test.ts`
- `services/frontend/src/components/globe/hooks/__tests__/useCountryHitTest.test.ts`
- `services/frontend/src/components/globe/spotlight/__tests__/SpotlightCartouche.test.tsx`
- `services/frontend/src/components/globe/spotlight/__tests__/HudFrame.test.tsx`
- `services/frontend/src/components/globe/spotlight/__tests__/CountryHeader.test.tsx`

---

## Task 1: Add `rbush` Dependency + 7 New CSS Tokens

**Files:**
- Modify: `services/frontend/package.json`
- Modify: `services/frontend/src/theme/hlidskjalf.css`

- [ ] **Step 1: Add `rbush` as direct dependency**

Edit `services/frontend/package.json`, in `dependencies` block alphabetically:

```json
{
  "dependencies": {
    "cesium": "^1.132.0",
    "d3-array": "^3.2.4",
    "d3-geo": "^3.1.1",
    "rbush": "^4.0.1",
    "react": "^19.0.0",
    "react-dom": "^19.0.0",
    "react-force-graph-2d": "^1.29.1",
    "react-router-dom": "^7.14.1",
    "satellite.js": "^5.0.0",
    "topojson-client": "^3.1.0"
  }
}
```

Also add types in `devDependencies`:

```json
"@types/rbush": "^4.0.0",
```

- [ ] **Step 2: Run install**

Run: `cd services/frontend && npm install`
Expected: lockfile updates, `rbush` and `@types/rbush` listed.

- [ ] **Step 3: Append 7 new CSS tokens to `hlidskjalf.css`**

Open `services/frontend/src/theme/hlidskjalf.css`, locate the `:root` block with the existing accents (search `--amber:`), and append after the existing `--rust` line (still inside the same `:root` block):

```css
  /* Worldview layer-design tokens (Spec 2026-04-30 §6) */
  --steel: #3a5a78;
  --mesh-line: color-mix(in srgb, var(--amber) 60%, transparent);
  --graticule: color-mix(in srgb, var(--granite) 80%, var(--steel) 20%);
  --lens-bracket: var(--amber);
  --star-dust: color-mix(in srgb, var(--bone) 70%, transparent);
  --capital-red: #e63a26;
  --city-label: #ffd07a;
```

- [ ] **Step 4: Run lint + type-check to confirm no regression**

Run: `cd services/frontend && npm run lint && npm run type-check`
Expected: both PASS.

- [ ] **Step 5: Commit**

```bash
cd services/frontend
git add package.json package-lock.json src/theme/hlidskjalf.css
cd ../..
git commit -m "feat(frontend): add rbush dep + 7 worldview tokens"
```

---

## Task 2: Build & Commit `country-endonyms.json` (Seed Subset)

The full Wikidata SPARQL for 177 countries is out of scope for this plan. We commit a hand-curated seed (USA + GRC + DEU + RUS + 5 fallback samples including W. Sahara) and the build script that can be run later to expand it. The Worldview gracefully falls back for un-indexed M49 codes per spec §4.4.

**Files:**
- Create: `scripts/build-country-endonyms.mjs`
- Create: `services/frontend/public/country-endonyms.json`

- [ ] **Step 1: Create the build script**

Write `scripts/build-country-endonyms.mjs`:

```js
#!/usr/bin/env node
// Generates services/frontend/public/country-endonyms.json from
// Wikidata SPARQL keyed by M49 codes from countries-110m.json.
// Usage: node scripts/build-country-endonyms.mjs
//
// For S2 we ship a hand-curated seed; running this script regenerates
// the JSON from Wikidata. Network access required.

import { readFile, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const TOPO = resolve(__dirname, "../services/frontend/public/countries-110m.json");
const OUT  = resolve(__dirname, "../services/frontend/public/country-endonyms.json");

const SPARQL = `https://query.wikidata.org/sparql`;
const LANGS = ["en", "de", "fr", "es", "it", "ru", "zh", "ja", "ar", "tr"];

async function sparql(query) {
  const res = await fetch(`${SPARQL}?query=${encodeURIComponent(query)}&format=json`, {
    headers: { "User-Agent": "ODIN-Worldview-Build/1.0", "Accept": "application/json" },
  });
  if (!res.ok) throw new Error(`SPARQL ${res.status}`);
  return (await res.json()).results.bindings;
}

async function main() {
  const topo = JSON.parse(await readFile(TOPO, "utf8"));
  const features = topo.objects.countries.geometries;
  const m49s = features.map((f) => f.id);

  const _topoIndex = {};
  const countries = {};

  for (const m49 of m49s) {
    const q = `
      SELECT ?iso3 ?label ?official ?capital ?capitalLabel ?capitalCoord
      ${LANGS.map((l) => `?label_${l} ?endo_${l}`).join(" ")}
      WHERE {
        ?c wdt:P2861 "${m49}".
        OPTIONAL { ?c wdt:P298 ?iso3. }
        OPTIONAL { ?c wdt:P1448 ?official. FILTER(LANG(?official) = "en") }
        OPTIONAL { ?c wdt:P36 ?capital. ?capital wdt:P625 ?capitalCoord. }
        ${LANGS.map((l) => `OPTIONAL { ?c rdfs:label ?label_${l}. FILTER(LANG(?label_${l}) = "${l}") }`).join("\n")}
        ${LANGS.map((l) => `OPTIONAL { ?c wdt:P1705 ?endo_${l}. FILTER(LANG(?endo_${l}) = "${l}") }`).join("\n")}
        SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
      }
      LIMIT 1
    `;
    try {
      const rows = await sparql(q);
      const row = rows[0];
      if (!row || !row.iso3) {
        _topoIndex[m49] = null;
        continue;
      }
      const iso3 = row.iso3.value;
      _topoIndex[m49] = iso3;
      const endonyms = {};
      for (const l of LANGS) {
        const v = row[`endo_${l}`]?.value ?? row[`label_${l}`]?.value;
        if (v) endonyms[l] = v;
      }
      countries[iso3] = {
        iso3,
        m49,
        names: {
          en: row[`label_en`]?.value ?? "",
          official: row.official?.value ?? "",
          native: row[`endo_${LANGS[0]}`]?.value ?? "",
          endonyms,
        },
        capital: row.capitalCoord
          ? {
              name: row.capitalLabel?.value ?? "",
              ...parsePoint(row.capitalCoord.value),
            }
          : null,
      };
    } catch (e) {
      console.error(`M49 ${m49}: ${e.message}`);
      _topoIndex[m49] = null;
    }
    // Rate-limit politeness
    await new Promise((r) => setTimeout(r, 200));
  }

  await writeFile(OUT, JSON.stringify({ _topoIndex, countries }, null, 2));
  console.log(`Wrote ${OUT}: ${Object.keys(countries).length}/${m49s.length} mapped.`);
}

function parsePoint(wkt) {
  // "Point(23.7275 37.9838)"
  const m = /Point\(([-\d.]+)\s+([-\d.]+)\)/.exec(wkt);
  return m ? { lon: parseFloat(m[1]), lat: parseFloat(m[2]) } : { lon: 0, lat: 0 };
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
```

- [ ] **Step 2: Hand-write seed `country-endonyms.json`**

For S2 we don't run the SPARQL. Write the seed file directly so the implementation can proceed without network. Create `services/frontend/public/country-endonyms.json`:

```json
{
  "_topoIndex": {
    "840": "USA",
    "300": "GRC",
    "276": "DEU",
    "643": "RUS",
    "732": null,
    "124": "CAN",
    "392": "JPN",
    "356": "IND",
    "203": "CZE"
  },
  "countries": {
    "USA": {
      "iso3": "USA",
      "m49": "840",
      "names": {
        "en": "United States",
        "official": "United States of America",
        "native": "United States",
        "endonyms": {
          "en": "United States",
          "de": "Vereinigte Staaten",
          "fr": "États-Unis",
          "es": "Estados Unidos",
          "it": "Stati Uniti",
          "ru": "Соединённые Штаты",
          "zh": "美国",
          "ja": "アメリカ合衆国",
          "ar": "الولايات المتحدة",
          "tr": "Amerika Birleşik Devletleri"
        }
      },
      "capital": { "name": "Washington, D.C.", "lat": 38.8951, "lon": -77.0364 }
    },
    "GRC": {
      "iso3": "GRC",
      "m49": "300",
      "names": {
        "en": "Greece",
        "official": "Hellenic Republic",
        "native": "Ελληνική Δημοκρατία",
        "endonyms": {
          "el": "Ελλάδα",
          "en": "Greece",
          "de": "Griechenland",
          "fr": "Grèce",
          "es": "Grecia",
          "it": "Grecia",
          "ru": "Греция",
          "tr": "Yunanistan",
          "ar": "اليونان",
          "zh": "希腊",
          "ja": "ギリシャ"
        }
      },
      "capital": { "name": "Athens", "lat": 37.9838, "lon": 23.7275 }
    },
    "DEU": {
      "iso3": "DEU",
      "m49": "276",
      "names": {
        "en": "Germany",
        "official": "Federal Republic of Germany",
        "native": "Bundesrepublik Deutschland",
        "endonyms": {
          "de": "Deutschland",
          "en": "Germany",
          "fr": "Allemagne",
          "es": "Alemania",
          "it": "Germania",
          "ru": "Германия",
          "tr": "Almanya",
          "ar": "ألمانيا",
          "zh": "德国",
          "ja": "ドイツ"
        }
      },
      "capital": { "name": "Berlin", "lat": 52.52, "lon": 13.405 }
    },
    "RUS": {
      "iso3": "RUS",
      "m49": "643",
      "names": {
        "en": "Russia",
        "official": "Russian Federation",
        "native": "Российская Федерация",
        "endonyms": {
          "ru": "Россия",
          "en": "Russia",
          "de": "Russland",
          "fr": "Russie",
          "es": "Rusia",
          "it": "Russia",
          "tr": "Rusya",
          "ar": "روسيا",
          "zh": "俄罗斯",
          "ja": "ロシア"
        }
      },
      "capital": { "name": "Moscow", "lat": 55.7558, "lon": 37.6173 }
    },
    "CAN": {
      "iso3": "CAN",
      "m49": "124",
      "names": { "en": "Canada", "official": "Canada", "native": "Canada", "endonyms": { "en": "Canada", "fr": "Canada" } },
      "capital": { "name": "Ottawa", "lat": 45.4215, "lon": -75.6972 }
    },
    "JPN": {
      "iso3": "JPN",
      "m49": "392",
      "names": { "en": "Japan", "official": "Japan", "native": "日本", "endonyms": { "ja": "日本", "en": "Japan" } },
      "capital": { "name": "Tokyo", "lat": 35.6762, "lon": 139.6503 }
    },
    "IND": {
      "iso3": "IND",
      "m49": "356",
      "names": { "en": "India", "official": "Republic of India", "native": "भारत गणराज्य", "endonyms": { "hi": "भारत", "en": "India" } },
      "capital": { "name": "New Delhi", "lat": 28.6139, "lon": 77.209 }
    },
    "CZE": {
      "iso3": "CZE",
      "m49": "203",
      "names": { "en": "Czechia", "official": "Czech Republic", "native": "Česká republika", "endonyms": { "cs": "Česko", "en": "Czechia" } },
      "capital": { "name": "Prague", "lat": 50.0755, "lon": 14.4378 }
    }
  }
}
```

- [ ] **Step 3: Make the script executable**

Run: `chmod +x scripts/build-country-endonyms.mjs`

- [ ] **Step 4: Verify the JSON parses and has expected shape**

Run:
```bash
node -e 'const j = require("./services/frontend/public/country-endonyms.json"); console.log(Object.keys(j._topoIndex).length, "indexed,", Object.keys(j.countries).length, "with-data");'
```
Expected: `9 indexed, 8 with-data`

- [ ] **Step 5: Commit**

```bash
git add scripts/build-country-endonyms.mjs services/frontend/public/country-endonyms.json
git commit -m "feat(frontend): seed country-endonyms.json + build script"
```

---

## Task 3: SpotlightContext + Reducer (TDD)

**Files:**
- Create: `services/frontend/src/components/globe/spotlight/SpotlightContext.tsx`
- Test: `services/frontend/src/components/globe/spotlight/__tests__/SpotlightContext.test.tsx`

- [ ] **Step 1: Write failing test for reducer**

Create `services/frontend/src/components/globe/spotlight/__tests__/SpotlightContext.test.tsx`:

```tsx
import { describe, it, expect } from "vitest";
import { spotlightReducer, type FocusTarget, type SpotlightAction } from "../SpotlightContext";

const idle: FocusTarget = null;

const samplePin: SpotlightAction = {
  type: "set",
  target: {
    kind: "circle",
    trigger: "pin",
    center: { lon: 41.87, lat: 36.34 },
    radius: 1,
    altitude: 312_000,
    label: "Sinjar Ridge",
    sourcePin: { layer: "events", entityId: "evt-44" },
  },
};

const sampleCountry: SpotlightAction = {
  type: "set",
  target: {
    kind: "country",
    trigger: "country",
    m49: "300",
    iso3: "GRC",
    polygon: { type: "Polygon", coordinates: [[[20, 40], [25, 40], [25, 38], [20, 38], [20, 40]]] },
    name: "Greece",
    capital: { name: "Athens", coords: { lon: 23.7275, lat: 37.9838 } },
  },
};

describe("spotlightReducer", () => {
  it("idle → focused (pin)", () => {
    const next = spotlightReducer(idle, samplePin);
    expect(next?.kind).toBe("circle");
    expect(next?.trigger).toBe("pin");
  });

  it("idle → focused (country)", () => {
    const next = spotlightReducer(idle, sampleCountry);
    expect(next?.kind).toBe("country");
    expect(next && "iso3" in next ? next.iso3 : null).toBe("GRC");
  });

  it("country can have null iso3 (graceful fallback)", () => {
    const fallback: SpotlightAction = {
      type: "set",
      target: {
        kind: "country", trigger: "country", m49: "732", iso3: null,
        polygon: { type: "Polygon", coordinates: [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]] },
        name: "W. Sahara", capital: null,
      },
    };
    const next = spotlightReducer(idle, fallback);
    expect(next && "iso3" in next ? next.iso3 : "x").toBeNull();
  });

  it("last-writer-wins: pin → country replaces", () => {
    const afterPin = spotlightReducer(idle, samplePin);
    const afterCountry = spotlightReducer(afterPin, sampleCountry);
    expect(afterCountry?.kind).toBe("country");
  });

  it("reset → idle", () => {
    const afterPin = spotlightReducer(idle, samplePin);
    const next = spotlightReducer(afterPin, { type: "reset" });
    expect(next).toBeNull();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/frontend && npx vitest run src/components/globe/spotlight/__tests__/SpotlightContext.test.tsx`
Expected: FAIL with "Cannot find module '../SpotlightContext'".

- [ ] **Step 3: Implement reducer + provider**

Create `services/frontend/src/components/globe/spotlight/SpotlightContext.tsx`:

```tsx
import { createContext, useContext, useReducer, type ReactNode, type Dispatch } from "react";

export type CircleTarget = {
  kind: "circle";
  trigger: "zoom" | "pin" | "search";
  center: { lon: number; lat: number };
  radius: number;        // degrees
  altitude: number;      // meters
  label: string;
  ref?: string;
  sourcePin?: { layer: string; entityId: string };
};

export type CountryTarget = {
  kind: "country";
  trigger: "country";
  m49: string;
  iso3: string | null;
  polygon: GeoJSON.Polygon | GeoJSON.MultiPolygon;
  name: string;
  capital: { name: string; coords: { lon: number; lat: number } } | null;
};

export type FocusTarget = CircleTarget | CountryTarget | null;

export type SpotlightAction =
  | { type: "set"; target: NonNullable<FocusTarget> }
  | { type: "reset" };

export function spotlightReducer(state: FocusTarget, action: SpotlightAction): FocusTarget {
  switch (action.type) {
    case "set":
      return action.target;
    case "reset":
      return null;
  }
}

interface SpotlightCtx {
  focusTarget: FocusTarget;
  dispatch: Dispatch<SpotlightAction>;
}

const SpotlightContext = createContext<SpotlightCtx | null>(null);

export function SpotlightProvider({ children }: { children: ReactNode }) {
  const [focusTarget, dispatch] = useReducer(spotlightReducer, null);
  return (
    <SpotlightContext.Provider value={{ focusTarget, dispatch }}>
      {children}
    </SpotlightContext.Provider>
  );
}

export function useSpotlight(): SpotlightCtx {
  const ctx = useContext(SpotlightContext);
  if (!ctx) throw new Error("useSpotlight must be used inside SpotlightProvider");
  return ctx;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/frontend && npx vitest run src/components/globe/spotlight/__tests__/SpotlightContext.test.tsx`
Expected: 5/5 PASS.

- [ ] **Step 5: Commit**

```bash
git add services/frontend/src/components/globe/spotlight/
git commit -m "feat(frontend): SpotlightContext reducer + provider"
```

---

## Task 4: `pointInPolygon.ts` (TDD)

**Files:**
- Create: `services/frontend/src/components/globe/hooks/pointInPolygon.ts`
- Test: `services/frontend/src/components/globe/hooks/__tests__/pointInPolygon.test.ts`

- [ ] **Step 1: Write failing test**

Create `services/frontend/src/components/globe/hooks/__tests__/pointInPolygon.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { polygonContains } from "../pointInPolygon";

const square: GeoJSON.Polygon = {
  type: "Polygon",
  coordinates: [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]],
};

const squareWithHole: GeoJSON.Polygon = {
  type: "Polygon",
  coordinates: [
    [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]],
    [[3, 3], [3, 7], [7, 7], [7, 3], [3, 3]],
  ],
};

const usaLike: GeoJSON.MultiPolygon = {
  type: "MultiPolygon",
  coordinates: [
    [[[-125, 25], [-66, 25], [-66, 49], [-125, 49], [-125, 25]]],   // contiguous
    [[[-160, 19], [-154, 19], [-154, 23], [-160, 23], [-160, 19]]], // hawaii-ish
    [[[-170, 60], [-140, 60], [-140, 72], [-170, 72], [-170, 60]]], // alaska-ish
  ],
};

describe("polygonContains", () => {
  it("inside simple polygon → true", () => {
    expect(polygonContains(square, 5, 5)).toBe(true);
  });
  it("outside simple polygon → false", () => {
    expect(polygonContains(square, 11, 5)).toBe(false);
  });
  it("inside hole → false", () => {
    expect(polygonContains(squareWithHole, 5, 5)).toBe(false);
  });
  it("inside ring but outside hole → true", () => {
    expect(polygonContains(squareWithHole, 1, 1)).toBe(true);
  });
  it("MultiPolygon contiguous USA point → true", () => {
    expect(polygonContains(usaLike, -100, 40)).toBe(true);
  });
  it("MultiPolygon Hawaii point → true", () => {
    expect(polygonContains(usaLike, -157, 21)).toBe(true);
  });
  it("MultiPolygon Alaska point → true", () => {
    expect(polygonContains(usaLike, -150, 65)).toBe(true);
  });
  it("MultiPolygon ocean point → false", () => {
    expect(polygonContains(usaLike, -130, 40)).toBe(false);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/frontend && npx vitest run src/components/globe/hooks/__tests__/pointInPolygon.test.ts`
Expected: FAIL with "Cannot find module '../pointInPolygon'".

- [ ] **Step 3: Implement**

Create `services/frontend/src/components/globe/hooks/pointInPolygon.ts`:

```ts
type Ring = number[][];

function ringContains(ring: Ring, lon: number, lat: number): boolean {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const xi = ring[i][0], yi = ring[i][1];
    const xj = ring[j][0], yj = ring[j][1];
    const intersect =
      yi > lat !== yj > lat &&
      lon < ((xj - xi) * (lat - yi)) / (yj - yi) + xi;
    if (intersect) inside = !inside;
  }
  return inside;
}

export function polygonContains(
  polygon: GeoJSON.Polygon | GeoJSON.MultiPolygon,
  lon: number,
  lat: number
): boolean {
  const polygons =
    polygon.type === "Polygon" ? [polygon.coordinates] : polygon.coordinates;
  for (const poly of polygons) {
    const [outer, ...holes] = poly as Ring[];
    if (!ringContains(outer, lon, lat)) continue;
    if (holes.some((h) => ringContains(h, lon, lat))) continue;
    return true;
  }
  return false;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/frontend && npx vitest run src/components/globe/hooks/__tests__/pointInPolygon.test.ts`
Expected: 8/8 PASS.

- [ ] **Step 5: Commit**

```bash
git add services/frontend/src/components/globe/hooks/
git commit -m "feat(frontend): pointInPolygon ray-cast (Polygon + MultiPolygon)"
```

---

## Task 5: `useCountryHitTest` Hook (TDD)

**Files:**
- Create: `services/frontend/src/components/globe/hooks/useCountryHitTest.ts`
- Test: `services/frontend/src/components/globe/hooks/__tests__/useCountryHitTest.test.ts`

- [ ] **Step 1: Write failing test**

Create `services/frontend/src/components/globe/hooks/__tests__/useCountryHitTest.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { buildCountryIndex, hitTestCountry, type CountryFeature } from "../useCountryHitTest";

const fakeFeatures: CountryFeature[] = [
  {
    m49: "300",
    name: "Greece",
    geometry: {
      type: "Polygon",
      coordinates: [[[20, 35], [28, 35], [28, 41], [20, 41], [20, 35]]],
    },
  },
  {
    m49: "732",
    name: "W. Sahara",
    geometry: {
      type: "Polygon",
      coordinates: [[[-17, 21], [-9, 21], [-9, 27], [-17, 27], [-17, 21]]],
    },
  },
];

const topoIndex = { "300": "GRC", "732": null };
const countriesData = {
  GRC: { iso3: "GRC", m49: "300", capital: { name: "Athens", lat: 37.98, lon: 23.73 } },
};

describe("useCountryHitTest", () => {
  it("builds an rbush index", () => {
    const idx = buildCountryIndex(fakeFeatures);
    expect(idx).toBeTruthy();
  });

  it("hit on Greece point → returns iso3 + capital", () => {
    const idx = buildCountryIndex(fakeFeatures);
    const r = hitTestCountry(idx, fakeFeatures, topoIndex, countriesData, 23, 38);
    expect(r?.m49).toBe("300");
    expect(r?.iso3).toBe("GRC");
    expect(r?.capital?.name).toBe("Athens");
  });

  it("hit on W. Sahara point → m49 + name only, iso3 null, capital null", () => {
    const idx = buildCountryIndex(fakeFeatures);
    const r = hitTestCountry(idx, fakeFeatures, topoIndex, countriesData, -13, 24);
    expect(r?.m49).toBe("732");
    expect(r?.iso3).toBeNull();
    expect(r?.capital).toBeNull();
    expect(r?.name).toBe("W. Sahara");
  });

  it("ocean point → null", () => {
    const idx = buildCountryIndex(fakeFeatures);
    const r = hitTestCountry(idx, fakeFeatures, topoIndex, countriesData, 0, 0);
    expect(r).toBeNull();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/frontend && npx vitest run src/components/globe/hooks/__tests__/useCountryHitTest.test.ts`
Expected: FAIL.

- [ ] **Step 3: Implement**

Create `services/frontend/src/components/globe/hooks/useCountryHitTest.ts`:

```ts
import RBush from "rbush";
import { useEffect, useState } from "react";
import { feature as topojsonFeature } from "topojson-client";
import { polygonContains } from "./pointInPolygon";

export interface CountryFeature {
  m49: string;
  name: string;
  geometry: GeoJSON.Polygon | GeoJSON.MultiPolygon;
}

interface BboxNode {
  minX: number;
  minY: number;
  maxX: number;
  maxY: number;
  index: number;
}

export type CountryIndex = RBush<BboxNode>;

interface CountryDatum {
  iso3: string;
  m49: string;
  capital: { name: string; lat: number; lon: number } | null;
}

interface EndonymJson {
  _topoIndex: Record<string, string | null>;
  countries: Record<string, CountryDatum>;
}

export interface CountryHit {
  m49: string;
  iso3: string | null;
  name: string;
  geometry: GeoJSON.Polygon | GeoJSON.MultiPolygon;
  capital: { name: string; coords: { lon: number; lat: number } } | null;
}

function bboxOf(geom: GeoJSON.Polygon | GeoJSON.MultiPolygon): [number, number, number, number] {
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  const polys = geom.type === "Polygon" ? [geom.coordinates] : geom.coordinates;
  for (const poly of polys) {
    for (const ring of poly as number[][][]) {
      for (const [x, y] of ring) {
        if (x < minX) minX = x; if (y < minY) minY = y;
        if (x > maxX) maxX = x; if (y > maxY) maxY = y;
      }
    }
  }
  return [minX, minY, maxX, maxY];
}

export function buildCountryIndex(features: CountryFeature[]): CountryIndex {
  const tree: CountryIndex = new RBush<BboxNode>();
  const items: BboxNode[] = features.map((f, index) => {
    const [minX, minY, maxX, maxY] = bboxOf(f.geometry);
    return { minX, minY, maxX, maxY, index };
  });
  tree.load(items);
  return tree;
}

export function hitTestCountry(
  index: CountryIndex,
  features: CountryFeature[],
  topoIndex: Record<string, string | null>,
  countries: Record<string, CountryDatum>,
  lon: number,
  lat: number
): CountryHit | null {
  const candidates = index.search({ minX: lon, minY: lat, maxX: lon, maxY: lat });
  for (const c of candidates) {
    const f = features[c.index];
    if (!polygonContains(f.geometry, lon, lat)) continue;
    const iso3 = topoIndex[f.m49] ?? null;
    const datum = iso3 ? countries[iso3] : null;
    return {
      m49: f.m49,
      iso3,
      name: f.name,
      geometry: f.geometry,
      capital: datum?.capital
        ? { name: datum.capital.name, coords: { lon: datum.capital.lon, lat: datum.capital.lat } }
        : null,
    };
  }
  return null;
}

interface LoaderState {
  features: CountryFeature[];
  index: CountryIndex | null;
  topoIndex: Record<string, string | null>;
  countries: Record<string, CountryDatum>;
}

export function useCountryHitTest(): LoaderState {
  const [state, setState] = useState<LoaderState>({
    features: [], index: null, topoIndex: {}, countries: {},
  });

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const [topoRes, endoRes] = await Promise.all([
        fetch("/countries-110m.json"),
        fetch("/country-endonyms.json"),
      ]);
      const topo = await topoRes.json();
      const endo = (await endoRes.json()) as EndonymJson;
      const fc = topojsonFeature(topo, topo.objects.countries) as GeoJSON.FeatureCollection;
      const features: CountryFeature[] = fc.features.map((f) => ({
        m49: String(f.id),
        name: (f.properties as { name: string })?.name ?? "",
        geometry: f.geometry as GeoJSON.Polygon | GeoJSON.MultiPolygon,
      }));
      if (cancelled) return;
      setState({
        features,
        index: buildCountryIndex(features),
        topoIndex: endo._topoIndex,
        countries: endo.countries,
      });
    })().catch((e) => console.error("useCountryHitTest load failed:", e));
    return () => { cancelled = true; };
  }, []);

  return state;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/frontend && npx vitest run src/components/globe/hooks/__tests__/useCountryHitTest.test.ts`
Expected: 4/4 PASS.

- [ ] **Step 5: Commit**

```bash
git add services/frontend/src/components/globe/hooks/
git commit -m "feat(frontend): useCountryHitTest with rbush + M49→ISO3 resolution"
```

---

## Task 6: SpotlightOverlay — Circle Kind

**Files:**
- Create: `services/frontend/src/components/globe/spotlight/SpotlightOverlay.tsx`

This task does not get a unit test — it interacts with Cesium primitives that require a real WebGL context. Visual verification is manual; reduced-motion / shape-correctness is covered by Task 17.

- [ ] **Step 1: Implement circle-kind GroundPrimitive lifecycle**

Create `services/frontend/src/components/globe/spotlight/SpotlightOverlay.tsx`:

```tsx
import { useEffect } from "react";
import * as Cesium from "cesium";
import { useSpotlight, type CircleTarget, type CountryTarget } from "./SpotlightContext";

interface Props {
  viewer: Cesium.Viewer | null;
}

const CIRCLE_FRAGMENT = `
  uniform vec4 color;
  uniform float alpha;
  uniform float falloff;
  czm_material czm_getMaterial(czm_materialInput m) {
    czm_material material = czm_getDefaultMaterial(m);
    float d = distance(m.st, vec2(0.5));
    // Center (d=0) → w=1 (warm), edge (d≥0.5) → w=0.
    float w = 1.0 - smoothstep(falloff * 0.5, 0.5, d);
    material.diffuse = color.rgb;
    material.alpha = color.a * w * alpha;
    return material;
  }
`;

const COUNTRY_FRAGMENT = `
  uniform vec4 color;
  uniform float alpha;
  czm_material czm_getMaterial(czm_materialInput m) {
    czm_material material = czm_getDefaultMaterial(m);
    material.diffuse = color.rgb;
    material.alpha = color.a * alpha;
    return material;
  }
`;

const AMBER = new Cesium.Color(0.769, 0.506, 0.227, 0.6);
const FADE_IN_MS = 320;
const FADE_OUT_MS = 200;

export function SpotlightOverlay({ viewer }: Props) {
  const { focusTarget } = useSpotlight();

  useEffect(() => {
    if (!viewer || viewer.isDestroyed() || !focusTarget) return;
    if (focusTarget.kind !== "circle") return;
    return mountCircle(viewer, focusTarget);
  }, [viewer, focusTarget]);

  useEffect(() => {
    if (!viewer || viewer.isDestroyed() || !focusTarget) return;
    if (focusTarget.kind !== "country") return;
    return mountCountry(viewer, focusTarget);
  }, [viewer, focusTarget]);

  return null;
}

function mountCircle(viewer: Cesium.Viewer, target: CircleTarget): () => void {
  const radiusMeters = degreesToMeters(target.radius);
  const center = Cesium.Cartesian3.fromDegrees(target.center.lon, target.center.lat);
  const material = new Cesium.Material({
    fabric: {
      type: "OdinSpotlightCircle",
      uniforms: { color: AMBER, alpha: 0.0, falloff: 0.85 },
      source: CIRCLE_FRAGMENT,
    },
    translucent: true,
  });
  const primitive = new Cesium.GroundPrimitive({
    geometryInstances: new Cesium.GeometryInstance({
      geometry: new Cesium.EllipseGeometry({ center, semiMajorAxis: radiusMeters, semiMinorAxis: radiusMeters }),
    }),
    appearance: new Cesium.MaterialAppearance({ material, flat: true }),
    classificationType: Cesium.ClassificationType.TERRAIN,
    asynchronous: false,
  });
  viewer.scene.primitives.add(primitive);

  const start = performance.now();
  const listener = () => {
    const t = performance.now() - start;
    material.uniforms.alpha = Math.min(1, t / FADE_IN_MS);
  };
  viewer.scene.preUpdate.addEventListener(listener);

  return () => {
    if (viewer.isDestroyed()) return;
    fadeOutAndRemove(viewer, material, primitive, listener);
  };
}

function mountCountry(viewer: Cesium.Viewer, target: CountryTarget): () => void {
  const polygons = target.polygon.type === "Polygon" ? [target.polygon.coordinates] : target.polygon.coordinates;
  const instances = polygons.map((rings) => {
    const positions = (rings[0] as number[][]).map(([lon, lat]) => Cesium.Cartesian3.fromDegrees(lon, lat));
    return new Cesium.GeometryInstance({
      geometry: new Cesium.PolygonGeometry({
        polygonHierarchy: new Cesium.PolygonHierarchy(positions),
        granularity: Cesium.Math.RADIANS_PER_DEGREE * 2,
      }),
    });
  });
  const COUNTRY_COLOR = new Cesium.Color(0.769, 0.506, 0.227, 0.35);
  const material = new Cesium.Material({
    fabric: {
      type: "OdinSpotlightCountry",
      uniforms: { color: COUNTRY_COLOR, alpha: 0.0 },
      source: COUNTRY_FRAGMENT,
    },
    translucent: true,
  });
  const primitive = new Cesium.GroundPrimitive({
    geometryInstances: instances,
    appearance: new Cesium.MaterialAppearance({ material, flat: true }),
    classificationType: Cesium.ClassificationType.TERRAIN,
    asynchronous: false,
  });
  viewer.scene.primitives.add(primitive);

  const start = performance.now();
  const listener = () => {
    const t = performance.now() - start;
    material.uniforms.alpha = Math.min(1, t / FADE_IN_MS);
  };
  viewer.scene.preUpdate.addEventListener(listener);

  return () => {
    if (viewer.isDestroyed()) return;
    fadeOutAndRemove(viewer, material, primitive, listener);
  };
}

function fadeOutAndRemove(
  viewer: Cesium.Viewer,
  material: Cesium.Material,
  primitive: Cesium.GroundPrimitive,
  inListener: () => void
): void {
  viewer.scene.preUpdate.removeEventListener(inListener);
  const start = performance.now();
  const startAlpha = material.uniforms.alpha as number;
  const fade = () => {
    const t = performance.now() - start;
    const a = Math.max(0, startAlpha * (1 - t / FADE_OUT_MS));
    material.uniforms.alpha = a;
    if (a <= 0) {
      viewer.scene.preUpdate.removeEventListener(fade);
      viewer.scene.primitives.remove(primitive);
    }
  };
  viewer.scene.preUpdate.addEventListener(fade);
}

function degreesToMeters(deg: number): number {
  // 1° lat ≈ 111 km
  return deg * 111_000;
}
```

- [ ] **Step 2: Manual run + visual verify (circle)**

Run: `cd services/frontend && npm run dev`. Open `http://localhost:5173/worldview`. In the browser console, manually dispatch a circle target — but `SpotlightProvider` isn't mounted yet (Task 9). For now, verify the file compiles:

Run: `cd services/frontend && npm run type-check`
Expected: PASS.

- [ ] **Step 3: Run lint**

Run: `cd services/frontend && npm run lint`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add services/frontend/src/components/globe/spotlight/SpotlightOverlay.tsx
git commit -m "feat(frontend): SpotlightOverlay GroundPrimitive (circle + country)"
```

---

## Task 7: Extend `EntityClickHandler` with Spotlight Dispatch

**Files:**
- Modify: `services/frontend/src/components/globe/EntityClickHandler.tsx`

The existing handler picks primitives by data-tag. We add: (a) a Spotlight dispatch alongside `setSelected` for tag-matches, and (b) a country hit-test fallback for no-tag picks.

- [ ] **Step 1: Read the current handler tail to find the no-pick branch**

Run: `grep -n "viewer.scene.pick\|setSelected(null)\|return\b" services/frontend/src/components/globe/EntityClickHandler.tsx | head -20`
Expected: shows the picked-undefined fall-through branch (`setSelected(null)` near end of `setInputAction`).

- [ ] **Step 2: Modify the handler to dispatch Spotlight**

In `services/frontend/src/components/globe/EntityClickHandler.tsx`:

1. Add imports near the top:

```tsx
import { useSpotlight } from "./spotlight/SpotlightContext";
import { useCountryHitTest, hitTestCountry } from "./hooks/useCountryHitTest";
```

2. In the `EntityClickHandler` function body, near `const [selected, setSelected] = useState`, add:

```tsx
const { dispatch: dispatchSpotlight } = useSpotlight();
const country = useCountryHitTest();
```

3. After each existing `setSelected({...})` block (one per data-tag), add a parallel dispatch. Example for `eventData`:

```tsx
if (eventData) {
  setSelected({ /* …existing… */ });
  dispatchSpotlight({
    type: "set",
    target: {
      kind: "circle",
      trigger: "pin",
      center: { lon: eventData.lon, lat: eventData.lat },
      radius: 1,
      altitude: 0,
      label: eventData.title,
      sourcePin: { layer: "events", entityId: eventData.id },
    },
  });
  return;
}
```

Apply the same pattern for `cableData`, and for every other data-tag branch in the existing file. The `center` / `lon` / `lat` come from each tag's existing fields; `layer` is the corresponding key from `LayerVisibility` (e.g. `"cables"`, `"flights"`, `"firmsHotspots"`, `"milAircraft"`, `"datacenters"`, `"refineries"`, `"eonet"`, `"gdacs"`, `"satellites"`, `"earthquakes"`, `"vessels"`, `"cctv"`, `"pipelines"`).

4. At the no-tag fall-through (where `setSelected(null)` currently runs when nothing was picked), insert before it:

```tsx
// No primitive matched — try country hit-test
if (country.index) {
  const cartesian = viewer.scene.pickPosition(movement.position) ?? viewer.camera.pickEllipsoid(movement.position);
  if (cartesian) {
    const carto = Cesium.Cartographic.fromCartesian(cartesian);
    const lon = Cesium.Math.toDegrees(carto.longitude);
    const lat = Cesium.Math.toDegrees(carto.latitude);
    const hit = hitTestCountry(country.index, country.features, country.topoIndex, country.countries, lon, lat);
    if (hit) {
      setSelected({
        id: hit.iso3 ?? hit.m49,
        name: hit.name,
        type: "country",
        position: { lat, lon },
        properties: { iso3: hit.iso3 ?? "—", m49: hit.m49 },
      });
      dispatchSpotlight({
        type: "set",
        target: {
          kind: "country",
          trigger: "country",
          m49: hit.m49,
          iso3: hit.iso3,
          polygon: hit.geometry,
          name: hit.name,
          capital: hit.capital,
        },
      });
      return;
    }
  }
}
setSelected(null);
dispatchSpotlight({ type: "reset" });
```

- [ ] **Step 3: Type-check**

Run: `cd services/frontend && npm run type-check`
Expected: PASS.

- [ ] **Step 4: Lint**

Run: `cd services/frontend && npm run lint`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/frontend/src/components/globe/EntityClickHandler.tsx
git commit -m "feat(frontend): EntityClickHandler dispatches Spotlight + country hit-test"
```

---

## Task 8: `useSpotlightTrigger` — Zoom Trigger

**Files:**
- Create: `services/frontend/src/components/globe/hooks/useSpotlightTrigger.ts`

The zoom trigger is a camera observer that dispatches `circle` Spotlight when altitude drops below 500 km. Search trigger is parked for now (the `§ Search` panel doesn't yet emit match events; we'll wire it when that contract exists).

- [ ] **Step 1: Implement the camera observer**

Create `services/frontend/src/components/globe/hooks/useSpotlightTrigger.ts`:

```ts
import { useEffect } from "react";
import * as Cesium from "cesium";
import { useSpotlight } from "../spotlight/SpotlightContext";

const ZOOM_THRESHOLD_M = 500_000;
const ZOOM_EXIT_M = 1_500_000;

export function useSpotlightTrigger(viewer: Cesium.Viewer | null): void {
  const { focusTarget, dispatch } = useSpotlight();

  useEffect(() => {
    if (!viewer || viewer.isDestroyed()) return;
    const camera = viewer.camera;

    const onChange = () => {
      const carto = camera.positionCartographic;
      if (!carto) return;
      const altitude = carto.height;
      const lon = Cesium.Math.toDegrees(carto.longitude);
      const lat = Cesium.Math.toDegrees(carto.latitude);

      if (altitude <= ZOOM_THRESHOLD_M && (!focusTarget || focusTarget.kind === "circle")) {
        dispatch({
          type: "set",
          target: {
            kind: "circle", trigger: "zoom",
            center: { lon, lat }, radius: 1, altitude,
            label: `${lat.toFixed(2)}N · ${lon.toFixed(2)}E`,
          },
        });
      } else if (altitude >= ZOOM_EXIT_M && focusTarget?.trigger === "zoom") {
        dispatch({ type: "reset" });
      }
    };

    const remove = camera.changed.addEventListener(onChange);
    return () => remove();
  }, [viewer, focusTarget, dispatch]);
}
```

- [ ] **Step 2: Type-check**

Run: `cd services/frontend && npm run type-check`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add services/frontend/src/components/globe/hooks/useSpotlightTrigger.ts
git commit -m "feat(frontend): useSpotlightTrigger camera-zoom observer"
```

---

## Task 9: Mount `SpotlightProvider` + Overlay + Trigger in `WorldviewPage`

**Files:**
- Modify: `services/frontend/src/pages/WorldviewPage.tsx`

- [ ] **Step 1: Wrap mount points in `SpotlightProvider`**

In `services/frontend/src/pages/WorldviewPage.tsx`:

1. Import:

```tsx
import { SpotlightProvider } from "../components/globe/spotlight/SpotlightContext";
import { SpotlightOverlay } from "../components/globe/spotlight/SpotlightOverlay";
import { useSpotlightTrigger } from "../components/globe/hooks/useSpotlightTrigger";
```

2. Wrap the page body's render tree with `<SpotlightProvider>` (it must enclose `EntityClickHandler` and the Cesium `<GlobeViewer>` mount).

3. Inside the provider, alongside `<EntityClickHandler viewer={viewer} />`, add `<SpotlightOverlay viewer={viewer} />`.

4. Inside the provider (must be inside, since it uses the context), add a small inner component that calls the hook:

```tsx
function ZoomTriggerHook({ viewer }: { viewer: Cesium.Viewer | null }) {
  useSpotlightTrigger(viewer);
  return null;
}
```

Mount it: `<ZoomTriggerHook viewer={viewer} />`.

- [ ] **Step 2: Type-check + lint**

Run: `cd services/frontend && npm run type-check && npm run lint`
Expected: both PASS.

- [ ] **Step 3: Manual smoke test**

Run: `cd services/frontend && npm run dev`. Open `http://localhost:5173/worldview`. Click a country (e.g. Greece): a translucent amber polygon should fade in over the country. ESC key not yet wired; resolved in Task 13.

- [ ] **Step 4: Commit**

```bash
git add services/frontend/src/pages/WorldviewPage.tsx
git commit -m "feat(frontend): mount SpotlightProvider + Overlay + zoom trigger"
```

---

## Task 10: HudFrame Component (TDD)

**Files:**
- Create: `services/frontend/src/components/globe/spotlight/HudFrame.tsx`
- Test: `services/frontend/src/components/globe/spotlight/__tests__/HudFrame.test.tsx`

- [ ] **Step 1: Write failing test**

Create `services/frontend/src/components/globe/spotlight/__tests__/HudFrame.test.tsx`:

```tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { HudFrame } from "../HudFrame";
import { SpotlightProvider } from "../SpotlightContext";

describe("HudFrame", () => {
  it("renders idle eyebrow when no focus", () => {
    render(<SpotlightProvider><HudFrame /></SpotlightProvider>);
    expect(screen.getByText(/§ worldview · idle/i)).toBeInTheDocument();
  });

  it("renders UTC clock", () => {
    render(<SpotlightProvider><HudFrame /></SpotlightProvider>);
    expect(screen.getByText(/utc/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/frontend && npx vitest run src/components/globe/spotlight/__tests__/HudFrame.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Implement**

Create `services/frontend/src/components/globe/spotlight/HudFrame.tsx`:

```tsx
import { useEffect, useState } from "react";
import { useSpotlight } from "./SpotlightContext";

function utcLabel(d: Date): string {
  return `${d.toISOString().slice(11, 19)} UTC`;
}

export function HudFrame() {
  const { focusTarget } = useSpotlight();
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);

  const stateLabel =
    focusTarget == null
      ? "idle"
      : focusTarget.kind === "country"
        ? `country · ${focusTarget.iso3 ?? focusTarget.m49}`
        : `focus · ${focusTarget.label}`;

  return (
    <div className="hud-frame" aria-hidden="true">
      <div className="hud-corners" />
      <div className="hud-crosshair" />
      <div className="hud-eyebrow">§ worldview · {stateLabel} · {now.toISOString().slice(0, 10)}</div>
      <div className="hud-time">{utcLabel(now)}</div>
      <div className="hud-scale">
        <span>500 km</span>
        <span className="hud-scale-bar" />
        <span>1000 km</span>
      </div>
      <div className="hud-coord">— · —</div>
    </div>
  );
}
```

Append matching CSS to `services/frontend/src/components/worldview/worldviewHudLoader.css` (or create a new `hud-frame.css` and import it):

```css
.hud-frame {
  position: absolute; inset: 0; pointer-events: none;
  font-family: "Martian Mono", ui-monospace, monospace;
  font-size: 9px; letter-spacing: .18em; color: var(--ash);
}
.hud-corners {
  position: absolute; inset: 14px;
  background: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' preserveAspectRatio='none' viewBox='0 0 100 100' fill='none' stroke='%236b6358' stroke-width='0.4'%3E%3Cpath d='M0 4 L0 0 L4 0 M96 0 L100 0 L100 4 M100 96 L100 100 L96 100 M4 100 L0 100 L0 96'/%3E%3C/svg%3E");
}
.hud-crosshair {
  position: absolute; left: 50%; top: 54%; width: 240px; height: 240px;
  transform: translate(-50%, -50%);
  background: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 240 240' fill='none' stroke='%236b6358' stroke-width='0.4' opacity='.5'%3E%3Cpath d='M115 0 L115 8 M115 232 L115 240 M0 120 L8 120 M232 120 L240 120'/%3E%3C/svg%3E");
}
.hud-eyebrow { position: absolute; top: 18px; left: 24px; }
.hud-time { position: absolute; top: 18px; right: 24px; }
.hud-scale { position: absolute; bottom: 18px; left: 24px; display: flex; gap: 10px; align-items: center; }
.hud-scale-bar { width: 80px; height: 1px; background: var(--ash); }
.hud-coord { position: absolute; bottom: 18px; right: 24px; }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/frontend && npx vitest run src/components/globe/spotlight/__tests__/HudFrame.test.tsx`
Expected: 2/2 PASS.

- [ ] **Step 5: Mount in WorldviewPage and commit**

Add `<HudFrame />` inside `<SpotlightProvider>` in `WorldviewPage.tsx`, after `<SpotlightOverlay>`.

```bash
git add services/frontend/src/components/globe/spotlight/HudFrame.tsx \
        services/frontend/src/components/globe/spotlight/__tests__/HudFrame.test.tsx \
        services/frontend/src/pages/WorldviewPage.tsx \
        services/frontend/src/components/worldview/worldviewHudLoader.css
git commit -m "feat(frontend): HudFrame chrome (corners, crosshair, eyebrow, clock)"
```

---

## Task 11: SpotlightCartouche (TDD)

**Files:**
- Create: `services/frontend/src/components/globe/spotlight/SpotlightCartouche.tsx`
- Test: `services/frontend/src/components/globe/spotlight/__tests__/SpotlightCartouche.test.tsx`

- [ ] **Step 1: Write failing test**

```tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { SpotlightCartouche } from "../SpotlightCartouche";
import { SpotlightProvider, type FocusTarget } from "../SpotlightContext";

function PreloadedProvider({ value, children }: { value: FocusTarget; children: React.ReactNode }) {
  // Test-only: use the real Provider seeded by mounting an effect that dispatches.
  // For these tests, render the Cartouche with a value injected by the wrapper:
  return <SpotlightProvider>{children}</SpotlightProvider>;
}

// We test the pure render function instead of the connected component:
import { renderCartouche } from "../SpotlightCartouche";

describe("renderCartouche", () => {
  it("idle → renders nothing", () => {
    expect(renderCartouche(null)).toBeNull();
  });

  it("circle → renders coordinate cartouche", () => {
    const r = renderCartouche({
      kind: "circle", trigger: "pin",
      center: { lon: 41.87, lat: 36.34 }, radius: 1, altitude: 312_000,
      label: "Sinjar Ridge",
    });
    const { container } = render(<>{r}</>);
    expect(container.textContent).toContain("Sinjar Ridge");
    expect(container.textContent).toMatch(/36\.34/);
  });

  it("country GRC with endonyms → renders Greece title + cartouche stack", () => {
    const r = renderCartouche({
      kind: "country", trigger: "country",
      m49: "300", iso3: "GRC",
      polygon: { type: "Polygon", coordinates: [[[0,0],[1,0],[1,1],[0,1],[0,0]]] },
      name: "Greece",
      capital: { name: "Athens", coords: { lon: 23.7275, lat: 37.9838 } },
    });
    const { container } = render(<>{r}</>);
    expect(container.textContent).toContain("Greece");
  });

  it("country fallback (iso3 = null) → renders display name only", () => {
    const r = renderCartouche({
      kind: "country", trigger: "country",
      m49: "732", iso3: null,
      polygon: { type: "Polygon", coordinates: [[[0,0],[1,0],[1,1],[0,1],[0,0]]] },
      name: "W. Sahara", capital: null,
    });
    const { container } = render(<>{r}</>);
    expect(container.textContent).toContain("W. Sahara");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/frontend && npx vitest run src/components/globe/spotlight/__tests__/SpotlightCartouche.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Implement**

Create `services/frontend/src/components/globe/spotlight/SpotlightCartouche.tsx`:

```tsx
import { useEffect, useState, type ReactNode } from "react";
import { useSpotlight, type FocusTarget } from "./SpotlightContext";

interface EndonymJson {
  countries: Record<string, {
    iso3: string;
    names: { en: string; official: string; native: string; endonyms: Record<string, string> };
  }>;
}

export function renderCartouche(t: FocusTarget, endo?: EndonymJson | null): ReactNode {
  if (t == null) return null;
  if (t.kind === "circle") {
    return (
      <div className="cartouche cartouche-circle">
        <div className="cartouche-headline">{t.label}</div>
        <div className="cartouche-sub">
          {t.center.lat.toFixed(2)}N · {t.center.lon.toFixed(2)}E
        </div>
      </div>
    );
  }
  // country
  const datum = t.iso3 && endo ? endo.countries[t.iso3] : null;
  const endonyms = datum?.names.endonyms ?? {};
  const cyrillic = endonyms.ru ?? endonyms.uk ?? null;
  return (
    <div className="cartouche cartouche-country">
      <div className="cartouche-endonyms">
        {Object.entries(endonyms).slice(0, 8).map(([lang, value]) => (
          <div key={lang} className="cartouche-endo">{value}</div>
        ))}
      </div>
      <h2 className="cartouche-title">{t.name}</h2>
      {cyrillic && <div className="cartouche-cyrillic">{cyrillic}</div>}
    </div>
  );
}

export function SpotlightCartouche() {
  const { focusTarget } = useSpotlight();
  const [endo, setEndo] = useState<EndonymJson | null>(null);
  useEffect(() => {
    fetch("/country-endonyms.json").then((r) => r.json()).then(setEndo).catch(() => setEndo(null));
  }, []);
  return <>{renderCartouche(focusTarget, endo)}</>;
}
```

Append CSS to `worldviewHudLoader.css`:

```css
.cartouche { position: absolute; pointer-events: none; }
.cartouche-circle { right: 30%; top: 40%; text-align: right; color: var(--bone); font-family: "Hanken Grotesk", sans-serif; }
.cartouche-headline { font-family: "Instrument Serif", Georgia, serif; font-style: italic; font-size: 20px; }
.cartouche-sub { font-family: "Martian Mono", monospace; font-size: 9px; color: var(--ash); letter-spacing: .14em; }
.cartouche-country { right: 36px; top: 46%; transform: translateY(-50%); text-align: right; color: var(--bone); font-family: "Hanken Grotesk", sans-serif; }
.cartouche-endonyms { font-size: 11px; line-height: 1.35; color: rgba(212,205,192,0.8); margin-bottom: 6px; }
.cartouche-title { margin: 0; font-weight: 300; font-size: 96px; line-height: .95; letter-spacing: -.02em; color: #fafafa; text-shadow: 0 0 24px rgba(0,0,0,.4); }
.cartouche-cyrillic { font-weight: 300; font-size: 34px; color: var(--amber); margin-top: 4px; }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/frontend && npx vitest run src/components/globe/spotlight/__tests__/SpotlightCartouche.test.tsx`
Expected: 4/4 PASS.

- [ ] **Step 5: Mount + commit**

Add `<SpotlightCartouche />` inside `<SpotlightProvider>` in `WorldviewPage.tsx`, after `<HudFrame>`.

```bash
git add services/frontend/src/components/globe/spotlight/SpotlightCartouche.tsx \
        services/frontend/src/components/globe/spotlight/__tests__/SpotlightCartouche.test.tsx \
        services/frontend/src/components/worldview/worldviewHudLoader.css \
        services/frontend/src/pages/WorldviewPage.tsx
git commit -m "feat(frontend): SpotlightCartouche adaptive (idle/circle/country)"
```

---

## Task 12: CountryHeader for InspectorPanel

**Files:**
- Create: `services/frontend/src/components/globe/spotlight/CountryHeader.tsx`
- Test: `services/frontend/src/components/globe/spotlight/__tests__/CountryHeader.test.tsx`
- Modify: `services/frontend/src/components/worldview/InspectorPanel.tsx`

- [ ] **Step 1: Write failing test**

```tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { CountryHeader } from "../CountryHeader";

describe("CountryHeader", () => {
  it("renders name + capital + S2.5 placeholder", () => {
    render(<CountryHeader name="Greece" iso3="GRC" m49="300" capital={{ name: "Athens", coords: { lon: 23.7, lat: 37.9 } }} />);
    expect(screen.getByText(/Greece/)).toBeInTheDocument();
    expect(screen.getByText(/Athens/)).toBeInTheDocument();
    expect(screen.getByText(/S2\.5 coming soon/i)).toBeInTheDocument();
  });

  it("falls back gracefully without iso3 + capital", () => {
    render(<CountryHeader name="W. Sahara" iso3={null} m49="732" capital={null} />);
    expect(screen.getByText(/W\. Sahara/)).toBeInTheDocument();
    expect(screen.getByText(/m49 · 732/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/frontend && npx vitest run src/components/globe/spotlight/__tests__/CountryHeader.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Implement**

Create `services/frontend/src/components/globe/spotlight/CountryHeader.tsx`:

```tsx
interface Props {
  name: string;
  iso3: string | null;
  m49: string;
  capital: { name: string; coords: { lon: number; lat: number } } | null;
}

export function CountryHeader({ name, iso3, m49, capital }: Props) {
  return (
    <div className="country-header">
      <div className="eyebrow">§ inspector · country · {iso3 ?? `m49 · ${m49}`}</div>
      <h3 className="country-title">{name}</h3>
      {capital && (
        <dl className="country-grid">
          <dt>capital</dt>
          <dd>{capital.name} · {capital.coords.lat.toFixed(2)}N {capital.coords.lon.toFixed(2)}E</dd>
        </dl>
      )}
      <div className="country-placeholder">§ Almanac · S2.5 coming soon</div>
    </div>
  );
}
```

Add corresponding CSS to `worldviewHudLoader.css`:

```css
.country-header { padding: 14px 18px; font-family: "Hanken Grotesk", sans-serif; }
.country-title { margin: 4px 0 12px; font-family: "Instrument Serif", Georgia, serif; font-style: italic; font-size: 22px; color: var(--bone); }
.country-grid { display: grid; grid-template-columns: auto 1fr; gap: 6px 14px; font-size: 11px; color: var(--bone); }
.country-grid dt { font-family: "Martian Mono", monospace; font-size: 9px; color: var(--ash); letter-spacing: .14em; text-transform: uppercase; }
.country-placeholder { margin-top: 14px; padding-top: 10px; border-top: 1px solid var(--granite); font-family: "Martian Mono", monospace; font-size: 9px; color: var(--ash); letter-spacing: .14em; text-transform: uppercase; }
```

- [ ] **Step 4: Wire into InspectorPanel**

In `services/frontend/src/components/worldview/InspectorPanel.tsx`, when the selected entity has `type === "country"`, render `<CountryHeader />` instead of the default property list. Sample diff (adjust to actual file shape):

```tsx
import { CountryHeader } from "../globe/spotlight/CountryHeader";
// ...
if (selected?.type === "country") {
  return (
    <CountryHeader
      name={selected.name}
      iso3={selected.properties.iso3 === "—" ? null : selected.properties.iso3}
      m49={selected.properties.m49}
      capital={null /* InspectorPanel does not yet receive capital; deferred to S2.5 — header still renders */}
    />
  );
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd services/frontend && npx vitest run src/components/globe/spotlight/__tests__/CountryHeader.test.tsx`
Expected: 2/2 PASS.

- [ ] **Step 6: Type-check + commit**

Run: `cd services/frontend && npm run type-check`
Expected: PASS.

```bash
git add services/frontend/src/components/globe/spotlight/CountryHeader.tsx \
        services/frontend/src/components/globe/spotlight/__tests__/CountryHeader.test.tsx \
        services/frontend/src/components/worldview/InspectorPanel.tsx \
        services/frontend/src/components/worldview/worldviewHudLoader.css
git commit -m "feat(frontend): CountryHeader for Inspector country-mode"
```

---

## Task 13: ESC Handler & Click-into-Void Reset

**Files:**
- Modify: `services/frontend/src/components/globe/spotlight/SpotlightContext.tsx` (add ESC listener as a useEffect inside the Provider)

- [ ] **Step 1: Add ESC + outside-click reset to SpotlightProvider**

In `SpotlightContext.tsx`, modify `SpotlightProvider`:

```tsx
import { useEffect } from "react";
// ...
export function SpotlightProvider({ children }: { children: ReactNode }) {
  const [focusTarget, dispatch] = useReducer(spotlightReducer, null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") dispatch({ type: "reset" });
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <SpotlightContext.Provider value={{ focusTarget, dispatch }}>
      {children}
    </SpotlightContext.Provider>
  );
}
```

Click-into-void reset: already covered in Task 7 (the "no-pick" branch dispatches `{type:'reset'}`).

- [ ] **Step 2: Add a test for ESC**

Append to `SpotlightContext.test.tsx`:

```tsx
import { render, fireEvent } from "@testing-library/react";
import { SpotlightProvider, useSpotlight } from "../SpotlightContext";

function Probe() {
  const { focusTarget, dispatch } = useSpotlight();
  return (
    <>
      <button onClick={() => dispatch({ type: "set", target: { kind: "circle", trigger: "pin", center: { lon: 0, lat: 0 }, radius: 1, altitude: 0, label: "x" } })}>set</button>
      <span data-testid="state">{focusTarget?.kind ?? "idle"}</span>
    </>
  );
}

it("ESC resets focusTarget to null", async () => {
  const { getByText, getByTestId } = render(<SpotlightProvider><Probe /></SpotlightProvider>);
  fireEvent.click(getByText("set"));
  expect(getByTestId("state").textContent).toBe("circle");
  fireEvent.keyDown(window, { key: "Escape" });
  expect(getByTestId("state").textContent).toBe("idle");
});
```

- [ ] **Step 3: Run test**

Run: `cd services/frontend && npx vitest run src/components/globe/spotlight/__tests__/SpotlightContext.test.tsx`
Expected: 6/6 PASS.

- [ ] **Step 4: Commit**

```bash
git add services/frontend/src/components/globe/spotlight/
git commit -m "feat(frontend): ESC resets Spotlight focus to idle"
```

---

## Task 14: Layer 03 — Graticule

**Files:**
- Create: `services/frontend/src/components/globe/visual-layers/Graticule.tsx`
- Modify: `services/frontend/src/pages/WorldviewPage.tsx` (mount + add `graticule` to `LayerVisibility` if appropriate or treat as always-on)

For S2 we keep Graticule always-on (no new `LayerVisibility` key — group A semantics from spec §2 say Group A is always-on).

- [ ] **Step 1: Implement Graticule as a Cesium PolylineCollection**

Create `services/frontend/src/components/globe/visual-layers/Graticule.tsx`:

```tsx
import { useEffect } from "react";
import * as Cesium from "cesium";

interface Props { viewer: Cesium.Viewer | null; }

export function Graticule({ viewer }: Props) {
  useEffect(() => {
    if (!viewer || viewer.isDestroyed()) return;
    const collection = new Cesium.PolylineCollection();
    const color = Cesium.Color.fromCssColorString("#3a3530"); // approx --graticule
    const material = Cesium.Material.fromType("Color", { color: color.withAlpha(0.45) });

    // Latitudes every 10°
    for (let lat = -80; lat <= 80; lat += 10) {
      const positions: Cesium.Cartesian3[] = [];
      for (let lon = -180; lon <= 180; lon += 5) {
        positions.push(Cesium.Cartesian3.fromDegrees(lon, lat));
      }
      collection.add({ positions, width: 0.5, material });
    }
    // Longitudes every 10°
    for (let lon = -180; lon < 180; lon += 10) {
      const positions: Cesium.Cartesian3[] = [];
      for (let lat = -85; lat <= 85; lat += 5) {
        positions.push(Cesium.Cartesian3.fromDegrees(lon, lat));
      }
      collection.add({ positions, width: 0.5, material });
    }

    viewer.scene.primitives.add(collection);
    return () => {
      if (viewer.isDestroyed()) return;
      viewer.scene.primitives.remove(collection);
    };
  }, [viewer]);
  return null;
}
```

- [ ] **Step 2: Mount in WorldviewPage**

Inside `<SpotlightProvider>`, add `<Graticule viewer={viewer} />`.

- [ ] **Step 3: Type-check + manual visual verify**

Run: `cd services/frontend && npm run type-check && npm run dev`
Expected: PASS, and the globe shows thin dark hairlines every 10° latitude/longitude.

- [ ] **Step 4: Commit**

```bash
git add services/frontend/src/components/globe/visual-layers/Graticule.tsx \
        services/frontend/src/pages/WorldviewPage.tsx
git commit -m "feat(frontend): Graticule (Layer 03, 10° lat/long hairlines)"
```

---

## Task 14b: Layer 04 — CountryBorders PolylineCollection

**Files:**
- Create: `services/frontend/src/components/globe/visual-layers/CountryBorders.tsx`
- Modify: `services/frontend/src/pages/WorldviewPage.tsx` (mount; toggle key `countryBorders` already exists in `LayerVisibility`)

The spec §3.5 calls for a vector PolylineCollection rendering of admin-0 polygons from `countries-110m.json`. This is independent from the existing raster `bordersLayer` in `GlobeViewer.tsx:117` (which uses `IonWorldImageryStyle.ROAD` and is a different style). For S2, mount the new vector layer alongside; user can toggle either via `countryBorders` key (controlling the new vector layer).

- [ ] **Step 1: Implement CountryBorders**

Create `services/frontend/src/components/globe/visual-layers/CountryBorders.tsx`:

```tsx
import { useEffect } from "react";
import * as Cesium from "cesium";
import { feature as topojsonFeature } from "topojson-client";

interface Props {
  viewer: Cesium.Viewer | null;
  visible: boolean;
}

export function CountryBorders({ viewer, visible }: Props) {
  useEffect(() => {
    if (!viewer || viewer.isDestroyed() || !visible) return;
    let cancelled = false;
    let collection: Cesium.PolylineCollection | null = null;

    (async () => {
      const res = await fetch("/countries-110m.json");
      const topo = await res.json();
      if (cancelled || viewer.isDestroyed()) return;
      const fc = topojsonFeature(topo, topo.objects.countries) as GeoJSON.FeatureCollection;
      const stoneColor = Cesium.Color.fromCssColorString(
        getComputedStyle(document.documentElement).getPropertyValue("--stone").trim() || "#958a7a"
      ).withAlpha(0.7);
      const material = Cesium.Material.fromType("Color", { color: stoneColor });

      collection = new Cesium.PolylineCollection();
      for (const f of fc.features) {
        const geom = f.geometry as GeoJSON.Polygon | GeoJSON.MultiPolygon;
        const polygons = geom.type === "Polygon" ? [geom.coordinates] : geom.coordinates;
        for (const poly of polygons) {
          for (const ring of poly as number[][][]) {
            const positions = (ring as number[][]).map(([lon, lat]) => Cesium.Cartesian3.fromDegrees(lon, lat));
            collection.add({ positions, width: 0.6, material });
          }
        }
      }
      viewer.scene.primitives.add(collection);
    })().catch((e) => console.error("CountryBorders load failed:", e));

    return () => {
      cancelled = true;
      if (viewer.isDestroyed() || !collection) return;
      viewer.scene.primitives.remove(collection);
    };
  }, [viewer, visible]);

  return null;
}
```

- [ ] **Step 2: Mount in WorldviewPage with the existing toggle**

Inside `<SpotlightProvider>` in `WorldviewPage.tsx`:

```tsx
<CountryBorders viewer={viewer} visible={layers.countryBorders} />
```

- [ ] **Step 3: Type-check + manual visual verify**

Run: `cd services/frontend && npm run type-check && npm run dev`
Expected: PASS, and the globe shows thin stone-colored country outlines that toggle on/off via the § Layers panel `countryBorders` switch.

- [ ] **Step 4: Commit**

```bash
git add services/frontend/src/components/globe/visual-layers/CountryBorders.tsx \
        services/frontend/src/pages/WorldviewPage.tsx
git commit -m "feat(frontend): CountryBorders PolylineCollection (Layer 04)"
```

---

## Task 15: Glyph-Layer Token Migration (Batched)

This task touches 14 existing layer-component files to swap their hardcoded color hex values to the new tokens from §6. Done as a single batch commit because each individual change is one-line and trivially reversible.

**Files:**
- Modify: `services/frontend/src/components/layers/FlightLayer.tsx`
- Modify: `services/frontend/src/components/layers/SatelliteLayer.tsx`
- Modify: `services/frontend/src/components/layers/EarthquakeLayer.tsx`
- Modify: `services/frontend/src/components/layers/ShipLayer.tsx`
- Modify: `services/frontend/src/components/layers/CCTVLayer.tsx`
- Modify: `services/frontend/src/components/layers/EventLayer.tsx`
- Modify: `services/frontend/src/components/layers/CableLayer.tsx`
- Modify: `services/frontend/src/components/layers/PipelineLayer.tsx`
- Modify: `services/frontend/src/components/layers/FIRMSLayer.tsx`
- Modify: `services/frontend/src/components/layers/MilAircraftLayer.tsx`
- Modify: `services/frontend/src/components/layers/DatacenterLayer.tsx`
- Modify: `services/frontend/src/components/layers/RefineryLayer.tsx`
- Modify: `services/frontend/src/components/layers/EONETLayer.tsx`
- Modify: `services/frontend/src/components/layers/GDACSLayer.tsx`

- [ ] **Step 1: Inspect existing color usage per layer**

Run: `grep -nE "Cesium\.Color\.|fromCssColorString\(\"#" services/frontend/src/components/layers/*.tsx | head -50`
Expected: shows hex literals per layer (e.g. red for incidents, gray for static).

- [ ] **Step 2: Define a shared token helper**

Create `services/frontend/src/components/layers/glyphTokens.ts`:

```ts
import * as Cesium from "cesium";

function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

export const glyphColor = {
  sentinel: () => Cesium.Color.fromCssColorString(cssVar("--sentinel") || "#b85a2a"),
  amber:    () => Cesium.Color.fromCssColorString(cssVar("--amber")    || "#c4813a"),
  stone:    () => Cesium.Color.fromCssColorString(cssVar("--stone")    || "#958a7a"),
  sage:     () => Cesium.Color.fromCssColorString(cssVar("--sage")     || "#7a8a68"),
} as const;
```

- [ ] **Step 3: Apply per-layer color swap**

Per the §3.8 mapping in the spec, swap each layer's primary color literal to call `glyphColor.<family>()`:

| File | Family |
|---|---|
| FlightLayer | stone |
| SatelliteLayer | stone |
| EarthquakeLayer | sentinel |
| ShipLayer | stone |
| CCTVLayer | stone |
| EventLayer | (per-event-type via codebook — leave as-is, deferred to S2.5) |
| CableLayer | sentinel for incidents, stone otherwise (existing dual-mode) |
| PipelineLayer | sentinel for incidents, stone otherwise |
| FIRMSLayer | sage |
| MilAircraftLayer | amber |
| DatacenterLayer | stone |
| RefineryLayer | stone |
| EONETLayer | sage |
| GDACSLayer | sentinel |

For each file, locate the color literal (typically a `Cesium.Color.fromCssColorString("#...")` call near the BillboardCollection / PointPrimitiveCollection setup) and replace with `glyphColor.<family>()`. EventLayer is the only file deliberately untouched (codebook lookup is S2.5).

- [ ] **Step 4: Run all layer tests**

Run: `cd services/frontend && npx vitest run src/components/layers/__tests__/`
Expected: PASS (existing tests, may need to update color assertions if any test pinned a literal hex — fix those alongside).

- [ ] **Step 5: Type-check + lint**

Run: `cd services/frontend && npm run type-check && npm run lint`
Expected: both PASS.

- [ ] **Step 6: Manual visual verify (sanity)**

Run: `cd services/frontend && npm run dev`. Spot-check `/worldview`: glyph colors look amber/stone/sentinel/sage, not the previous palette.

- [ ] **Step 7: Commit**

```bash
git add services/frontend/src/components/layers/
git commit -m "refactor(frontend): migrate 13 glyph-layers to Hlidskjalf tokens"
```

---

## Task 16: LayersPanel Restructure into 4 Groups

**Files:**
- Modify: `services/frontend/src/components/worldview/LayersPanel.tsx`
- Modify: `services/frontend/src/components/worldview/LayersPanel.test.tsx` (extend)

- [ ] **Step 1: Read current panel structure**

Run: `grep -n "Group\|group\|sectionTitle\|<h3" services/frontend/src/components/worldview/LayersPanel.tsx | head`
Expected: shows the current layout (likely flat or shallowly grouped).

- [ ] **Step 2: Restructure into 4 groups**

In `LayersPanel.tsx`, define a static grouping that maps each `LayerVisibility` key to its display group:

```tsx
const PANEL_GROUPS: Array<{
  group: "A · sky" | "B · earth" | "C · signal · network" | "C · signal · glyphs" | "D · lens & chrome";
  always?: boolean;
  items: Array<{ key: keyof LayerVisibility | "void" | "atmosphere" | "spotlight"; label: string }>;
}> = [
  {
    group: "A · sky", always: true,
    items: [
      { key: "void", label: "Void & Stars" },
      { key: "atmosphere", label: "Atmosphere" },
    ],
  },
  {
    group: "B · earth",
    items: [
      { key: "countryBorders", label: "Country Borders" },
      { key: "cityBuildings", label: "City Buildings" },
    ],
  },
  {
    group: "C · signal · network",
    items: [
      { key: "cables", label: "Cables" },
      { key: "pipelines", label: "Pipelines" },
      { key: "satellites", label: "Satellites" },
    ],
  },
  {
    group: "C · signal · glyphs",
    items: [
      { key: "flights", label: "Flights" },
      { key: "earthquakes", label: "Earthquakes" },
      { key: "vessels", label: "Vessels" },
      { key: "cctv", label: "CCTV" },
      { key: "events", label: "Graph Events" },
      { key: "firmsHotspots", label: "FIRMS Hotspots" },
      { key: "milAircraft", label: "Mil-air" },
      { key: "datacenters", label: "Datacenters" },
      { key: "refineries", label: "Refineries" },
      { key: "eonet", label: "EONET" },
      { key: "gdacs", label: "GDACS" },
    ],
  },
  {
    group: "D · lens & chrome", always: true,
    items: [
      { key: "spotlight", label: "Spotlight" },
    ],
  },
];
```

Render groups with hairline separators and an "always" pseudo-state (display only, no toggle) for groups A and D. Toggle items in B and C wire to the existing `onToggle(key)`.

- [ ] **Step 3: Add a test that all 16 toggleable keys appear under correct groups**

Add to `LayersPanel.test.tsx`:

```tsx
it("renders 4 groups with §-eyebrow", () => {
  render(<LayersPanel layers={defaultLayers} onToggle={() => {}} />);
  expect(screen.getByText(/A · sky/i)).toBeInTheDocument();
  expect(screen.getByText(/B · earth/i)).toBeInTheDocument();
  expect(screen.getByText(/C · signal · glyphs/i)).toBeInTheDocument();
  expect(screen.getByText(/D · lens & chrome/i)).toBeInTheDocument();
});

it("renders all 16 LayerVisibility keys under correct groups", () => {
  render(<LayersPanel layers={defaultLayers} onToggle={() => {}} />);
  const expectedKeys = ["flights","satellites","earthquakes","vessels","cctv","events","cables","pipelines","countryBorders","cityBuildings","firmsHotspots","milAircraft","datacenters","refineries","eonet","gdacs"];
  for (const k of expectedKeys) {
    expect(screen.getByTestId(`layer-toggle-${k}`)).toBeInTheDocument();
  }
});
```

(Add `data-testid={`layer-toggle-${item.key}`}` to each toggle row.)

- [ ] **Step 4: Run tests**

Run: `cd services/frontend && npx vitest run src/components/worldview/LayersPanel.test.tsx`
Expected: PASS.

- [ ] **Step 5: Manual visual verify**

Run: `cd services/frontend && npm run dev`. Open `/worldview`, expand the § Layers panel, confirm 4-group structure with all 16 toggles present.

- [ ] **Step 6: Commit**

```bash
git add services/frontend/src/components/worldview/LayersPanel.tsx \
        services/frontend/src/components/worldview/LayersPanel.test.tsx
git commit -m "refactor(frontend): LayersPanel into 4-group structure (Sky/Earth/Signal/Lens)"
```

---

## Task 17: Reduced-Motion Fallback + FPS Sanity Check

**Files:**
- Modify: `services/frontend/src/components/globe/spotlight/SpotlightOverlay.tsx`
- Modify: `services/frontend/src/components/globe/spotlight/HudFrame.tsx`

- [ ] **Step 1: Detect `prefers-reduced-motion`**

In `SpotlightOverlay.tsx`, compute fade durations conditionally:

```ts
const REDUCED = typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
const FADE_IN_MS = REDUCED ? 120 : 320;
const FADE_OUT_MS = REDUCED ? 120 : 200;
```

Move this to module scope or recompute on each mount; either is acceptable.

- [ ] **Step 2: HudFrame clock interval respects reduced-motion**

In `HudFrame.tsx`, when reduced-motion is set, update the clock every 5 s instead of every 1 s (visual flicker reduction):

```tsx
const interval = REDUCED ? 5000 : 1000;
const id = setInterval(() => setNow(new Date()), interval);
```

- [ ] **Step 3: Manual FPS check**

Run: `cd services/frontend && npm run dev`. Open `/worldview`, enable Cesium FPS counter (set `viewer.scene.debugShowFramesPerSecond = true` in `GlobeViewer.tsx` temporarily, **revert before commit**). Rotate the camera with all default layers on.
Expected: ≥ 55 FPS sustained at 1080p.

- [ ] **Step 4: Type-check + lint**

Run: `cd services/frontend && npm run type-check && npm run lint`
Expected: both PASS.

- [ ] **Step 5: Commit**

```bash
git add services/frontend/src/components/globe/spotlight/
git commit -m "feat(frontend): prefers-reduced-motion fallback + FPS sanity"
```

---

## Acceptance Verification

After Task 17, run the full test suite + lint + type-check:

- [ ] **Final verification commands**

```bash
cd services/frontend
npm run lint && npm run type-check && npm test
```

All three must PASS.

- [ ] **Manual acceptance walkthrough**

Open `/worldview`. Verify against spec §14:
- Layer-stack 00, 01, 02, 03, 04, 06, 07, 08, 09a, 09b implemented.
- § Layers Panel shows 4-group structure.
- Four triggers: zoom (camera ≤ 500 km), pin click, country click; search trigger placeholder (deferred until § Search emits match events).
- `focusTarget` last-writer-wins, ESC resets.
- Country mode: amber polygon-highlight, capital pulse (only for indexed countries), multilingual cartouche from `country-endonyms.json`. Inspector shows country header with `S2.5 coming soon` placeholder.
- Token-Delta in `hlidskjalf.css` is integrated.
- ≥ 55 FPS rotation.
- Reduced-motion shortens animations.
- Existing 16 layer-components remain structurally unchanged (only color swaps).
- Country click on USA (alaska or hawaii) hits the same M49.

---

## Out-of-Scope Reminders

The following are explicitly **not** part of this plan (per spec §11.1) and should not be added by drift:

- Layer-engine consolidation (`useGlyphMerger`, single `BillboardCollection`)
- Almanac panel with REST Countries / Wikidata SPARQL / Munin briefs / Active-intel pulses
- GeoNames cities1000 major-city labels
- Layer 05 Hydrography (rivers asset not in repo)
- Natural Earth 1:50m admin-0 upgrade
- Sentinel-2 daytime composite
- Animated time-slider
- Country-vs-country comparison
- Visual regression CI gate

Search trigger (camera flyTo on § Search match acceptance) is logically part of S2 but parked here because the existing `§ Search` panel does not yet emit match events. When that contract is added (separate small task), wire it as a fourth dispatch in `useSpotlightTrigger.ts`.
