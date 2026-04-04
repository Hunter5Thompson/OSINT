# Globe Layers Evolution — Phase 1+2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add terrain relief + SVG sidebar icons + oil/gas pipeline layer to the ODIN Globe.

**Architecture:** Phase 1 activates Cesium World Terrain and replaces ASCII layer icons with colored SVGs. Phase 2 adds a new PipelineLayer component with LOD-filtered static GeoJSON data, following the existing CableLayer pattern.

**Tech Stack:** CesiumJS (TerrainProvider, PolylineCollection, BillboardCollection), React 19, TypeScript, Tailwind CSS, Vite static serving

**Spec:** `docs/superpowers/specs/2026-04-05-globe-layers-evolution-design.md`

---

## File Structure

### Phase 1: Terrain + Icons (modify existing)

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `services/frontend/src/components/globe/GlobeViewer.tsx` | Add Cesium World Terrain |
| Modify | `services/frontend/src/components/ui/OperationsPanel.tsx` | Replace ASCII icons with SVGs |
| Modify | `services/frontend/src/types/index.ts` | Add `pipelines` to LayerVisibility |
| Modify | `services/frontend/src/App.tsx` | Add pipelines state + default |
| Modify | `services/backend/app/main.py` | Add pipelines to ClientConfig defaults |
| Modify | `services/frontend/src/services/api.ts` | (no change needed — config already generic) |

### Phase 2: Pipeline Layer (new + modify)

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `services/frontend/public/data/pipelines.geojson` | Static pipeline geo data |
| Create | `services/frontend/src/components/layers/PipelineLayer.tsx` | Pipeline rendering with LOD |
| Create | `services/frontend/src/hooks/usePipelines.ts` | Fetch + cache pipeline GeoJSON |
| Create | `services/frontend/src/types/pipeline.ts` | Pipeline TypeScript types |
| Modify | `services/frontend/src/components/ui/OperationsPanel.tsx` | Add Pipelines toggle |
| Modify | `services/frontend/src/components/globe/EntityClickHandler.tsx` | Add pipeline click handling |
| Modify | `services/frontend/src/App.tsx` | Add PipelineLayer + hook wiring |
| Modify | `services/frontend/src/components/ui/StatusBar.tsx` | Add pipeline count |

---

## Task 1: Cesium World Terrain

**Files:**
- Modify: `services/frontend/src/components/globe/GlobeViewer.tsx`

- [ ] **Step 1: Add terrain provider after viewer creation**

In `services/frontend/src/components/globe/GlobeViewer.tsx`, add after the `viewer.scene.backgroundColor` line (line 45) and before the Google 3D Tiles block (line 47):

```typescript
    // Cesium World Terrain — relief + bathymetry
    viewer.scene.setTerrain(
      Cesium.Terrain.fromWorldTerrain({
        requestWaterMask: true,
        requestVertexNormals: true,
      }),
    );
    viewer.scene.verticalExaggeration = 1.5;
```

- [ ] **Step 2: Verify terrain loads**

```bash
cd services/frontend && npm run dev
```

Open `http://localhost:5173`, zoom into a mountainous region (e.g. Alps, Himalayas). Mountains should have visible 3D relief. Zoom into Strait of Hormuz — ocean floor bathymetry should be visible.

- [ ] **Step 3: Commit**

```bash
git add services/frontend/src/components/globe/GlobeViewer.tsx
git commit -m "feat(frontend): activate Cesium World Terrain with 1.5x exaggeration + bathymetry"
```

---

## Task 2: Add `pipelines` to LayerVisibility Type

**Files:**
- Modify: `services/frontend/src/types/index.ts`

- [ ] **Step 1: Add pipelines field to LayerVisibility**

In `services/frontend/src/types/index.ts`, add `pipelines` to the `LayerVisibility` interface:

```typescript
export interface LayerVisibility {
  flights: boolean;
  satellites: boolean;
  earthquakes: boolean;
  vessels: boolean;
  cctv: boolean;
  events: boolean;
  cables: boolean;
  pipelines: boolean;
}
```

- [ ] **Step 2: Add pipelines to DataFreshness**

In the same file, add `pipelines` to `DataFreshness`:

```typescript
export interface DataFreshness {
  flights: Date | null;
  satellites: Date | null;
  earthquakes: Date | null;
  vessels: Date | null;
  events: Date | null;
  cables: Date | null;
  pipelines: Date | null;
}
```

- [ ] **Step 3: Update App.tsx default state**

In `services/frontend/src/App.tsx`, add `pipelines: false` to the initial `layers` state (line 38):

```typescript
  const [layers, setLayers] = useState<LayerVisibility>({
    flights: true,
    satellites: true,
    earthquakes: true,
    vessels: false,
    cctv: false,
    events: false,
    cables: false,
    pipelines: false,
  });
```

- [ ] **Step 4: Update App.tsx config fallback + apply backend defaults**

In `services/frontend/src/App.tsx`, add `pipelines: false` to the fallback config (line 59):

```typescript
        setConfig({
          cesium_ion_token: "",
          default_layers: { flights: true, satellites: true, earthquakes: true, vessels: false, cctv: false, events: false, cables: false, pipelines: false },
          api_version: "v1",
        });
```

Also, add a `useEffect` after the config load (after line 63) to apply backend-provided layer defaults:

```typescript
  useEffect(() => {
    if (config?.default_layers) {
      setLayers((prev) => ({ ...prev, ...config.default_layers }));
    }
  }, [config]);
```

This ensures the backend `default_layers` dict is the source of truth for initial layer visibility. New layers added to the backend config will automatically propagate to the frontend without hardcoded changes.

- [ ] **Step 5: Update backend config defaults**

In `services/backend/app/main.py`, add `"pipelines": False` to the `default_layers` dict in the `client_config` endpoint (after line 115):

```python
        default_layers={
            "flights": True,
            "satellites": True,
            "earthquakes": True,
            "vessels": False,
            "cctv": False,
            "events": False,
            "cables": False,
            "pipelines": False,
        },
```

- [ ] **Step 6: Run type-check (expected interim error until Task 8)**

```bash
cd services/frontend && npx tsc --noEmit
```

Expected: No errors (or only pre-existing ones unrelated to our changes). Note: StatusBar will show a type error for missing `pipelines` in freshness — this is expected and fixed in Task 8 when we wire everything together.

- [ ] **Step 7: Commit**

```bash
git add services/frontend/src/types/index.ts services/frontend/src/App.tsx services/backend/app/main.py
git commit -m "feat(frontend,backend): add pipelines to LayerVisibility type + config defaults"
```

---

## Task 3: SVG Layer Icons in OperationsPanel

**Files:**
- Modify: `services/frontend/src/components/ui/OperationsPanel.tsx`

- [ ] **Step 1: Replace LAYER_CONFIG with SVG icon components**

Replace the entire `LAYER_CONFIG` array and add SVG icon rendering. Replace lines 10-18 of `services/frontend/src/components/ui/OperationsPanel.tsx`:

```typescript
const LAYER_CONFIG: { key: keyof LayerVisibility; label: string; color: string }[] = [
  { key: "flights", label: "FLIGHTS", color: "#c4813a" },
  { key: "satellites", label: "SATELLITES", color: "#06b6d4" },
  { key: "earthquakes", label: "EARTHQUAKES", color: "#ef4444" },
  { key: "vessels", label: "VESSELS", color: "#4fc3f7" },
  { key: "cctv", label: "CCTV", color: "#d4cdc0" },
  { key: "events", label: "EVENTS", color: "#f97316" },
  { key: "cables", label: "CABLES", color: "#22c55e" },
  { key: "pipelines", label: "PIPELINES", color: "#eab308" },
];

function LayerIcon({ layerKey, color }: { layerKey: string; color: string }) {
  const s = { width: 16, height: 16, viewBox: "0 0 32 32", fill: "none" } as const;
  switch (layerKey) {
    case "flights":
      return (
        <svg {...s}>
          <path d="M16 6 L22 20 L16 17 L10 20 Z" fill={color} opacity={0.8} />
        </svg>
      );
    case "satellites":
      return (
        <svg {...s}>
          <circle cx={16} cy={16} r={5} fill={color} opacity={0.8} />
          <ellipse cx={16} cy={16} rx={14} ry={6} transform="rotate(-20 16 16)" stroke={color} strokeWidth={1} opacity={0.4} fill="none" />
        </svg>
      );
    case "earthquakes":
      return (
        <svg {...s}>
          <circle cx={16} cy={16} r={8} stroke={color} strokeWidth={2} opacity={0.6} fill="none" />
          <circle cx={16} cy={16} r={3} fill={color} opacity={0.9} />
        </svg>
      );
    case "vessels":
      return (
        <svg {...s}>
          <path d="M16 6 L22 16 L16 14 L10 16 Z" fill={color} opacity={0.8} />
          <path d="M10 18 L22 18 L20 26 L12 26 Z" fill={color} opacity={0.4} />
        </svg>
      );
    case "cctv":
      return (
        <svg {...s}>
          <rect x={10} y={12} width={12} height={8} rx={2} fill={color} opacity={0.6} />
          <path d="M22 14 L28 10 L28 22 L22 18 Z" fill={color} opacity={0.4} />
          <circle cx={15} cy={16} r={2} fill={color} opacity={0.9} />
        </svg>
      );
    case "events":
      return (
        <svg {...s}>
          <circle cx={16} cy={16} r={10} stroke={color} strokeWidth={1.5} opacity={0.4} fill="none" />
          <circle cx={16} cy={16} r={5} stroke={color} strokeWidth={1.5} opacity={0.6} fill="none" />
          <circle cx={16} cy={16} r={2} fill={color} opacity={0.9} />
        </svg>
      );
    case "cables":
      return (
        <svg {...s}>
          <path d="M4 24 C10 24 10 8 16 8 C22 8 22 24 28 24" stroke={color} strokeWidth={2} opacity={0.7} fill="none" />
        </svg>
      );
    case "pipelines":
      return (
        <svg {...s}>
          <path d="M4 16 Q10 10 16 16 Q22 22 28 16" stroke={color} strokeWidth={2.5} opacity={0.7} fill="none" />
          <circle cx={4} cy={16} r={3} fill={color} opacity={0.6} />
          <circle cx={28} cy={16} r={3} fill={color} opacity={0.6} />
        </svg>
      );
    default:
      return <span style={{ color }}>●</span>;
  }
}
```

- [ ] **Step 2: Update the button rendering**

In the same file, replace the button content inside the `.map()` (the `<span className="w-4 text-center">{icon}</span>` line) with:

```tsx
          <button
            key={key}
            onClick={() => onToggleLayer(key)}
            className="w-full flex items-center gap-2 px-2 py-1.5 rounded mb-1 transition-colors border"
            style={layers[key] ? {
              backgroundColor: `${color}1a`,
              borderColor: `${color}4d`,
              color: color,
            } : {
              color: "rgba(0, 255, 65, 0.4)",
              borderColor: "transparent",
            }}
          >
            <span className="w-4 flex items-center justify-center" style={{ opacity: layers[key] ? 1 : 0.3 }}>
              <LayerIcon layerKey={key} color={color} />
            </span>
            <span>{label}</span>
            <span className="ml-auto text-[10px]">{layers[key] ? "ON" : "OFF"}</span>
          </button>
```

Note: We use inline `style` for the dynamic colors because Tailwind can't handle runtime color values in `bg-[${color}]` syntax.

- [ ] **Step 3: Verify visually**

```bash
cd services/frontend && npm run dev
```

Open `http://localhost:5173`. The Operations panel should show colored SVG icons for each layer. Toggling should change opacity. The new PIPELINES entry should appear at the bottom (OFF by default).

- [ ] **Step 4: Run type-check**

```bash
npx tsc --noEmit
```

- [ ] **Step 5: Commit**

```bash
git add services/frontend/src/components/ui/OperationsPanel.tsx
git commit -m "feat(frontend): replace ASCII layer icons with colored SVGs in OperationsPanel"
```

---

## Task 4: Pipeline TypeScript Types

**Files:**
- Create: `services/frontend/src/types/pipeline.ts`

- [ ] **Step 1: Create pipeline types**

Create `services/frontend/src/types/pipeline.ts`:

```typescript
/** GeoJSON Feature properties for a pipeline segment. */
export interface PipelineProperties {
  name: string;
  tier: "major" | "regional" | "local";
  type: "oil" | "gas" | "lng" | "mixed";
  status: "active" | "planned" | "under_construction";
  operator: string | null;
  capacity_bcm: number | null;
  length_km: number | null;
  countries: string[];
}

/** A single GeoJSON Feature for a pipeline. */
export interface PipelineFeature {
  type: "Feature";
  properties: PipelineProperties;
  geometry: {
    type: "LineString" | "MultiLineString";
    coordinates: number[][] | number[][][];
  };
}

/** Root GeoJSON FeatureCollection for pipelines. */
export interface PipelineGeoJSON {
  type: "FeatureCollection";
  features: PipelineFeature[];
}

/** Color mapping for pipeline types. */
export const PIPELINE_COLORS: Record<PipelineProperties["type"], string> = {
  oil: "#eab308",
  gas: "#f97316",
  lng: "#a855f7",
  mixed: "#d4cdc0",
};

/** Camera altitude thresholds for LOD tiers (meters). */
export const PIPELINE_LOD_THRESHOLDS = {
  major: Infinity,       // always visible
  regional: 5_000_000,   // visible below 5M meters
  local: 1_000_000,      // visible below 1M meters
} as const;
```

- [ ] **Step 2: Export from types index**

In `services/frontend/src/types/index.ts`, add at the bottom:

```typescript
export type { PipelineProperties, PipelineFeature, PipelineGeoJSON } from "./pipeline";
export { PIPELINE_COLORS, PIPELINE_LOD_THRESHOLDS } from "./pipeline";
```

- [ ] **Step 3: Commit**

```bash
git add services/frontend/src/types/pipeline.ts services/frontend/src/types/index.ts
git commit -m "feat(frontend): add Pipeline GeoJSON types with LOD thresholds"
```

---

## Task 5: Pipeline Data (GeoJSON)

**Files:**
- Create: `services/frontend/public/data/pipelines.geojson`

- [ ] **Step 1: Create initial pipeline GeoJSON with major trunk lines**

Create `services/frontend/public/data/pipelines.geojson` with a representative set of major pipelines. This is a seed dataset — the full dataset will be enriched from Global Energy Monitor later.

```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "properties": {
        "name": "Nord Stream 1",
        "tier": "major",
        "type": "gas",
        "status": "active",
        "operator": "Nord Stream AG",
        "capacity_bcm": 55,
        "length_km": 1224,
        "countries": ["Russia", "Germany"]
      },
      "geometry": {
        "type": "LineString",
        "coordinates": [[28.8, 59.4], [25.0, 59.2], [20.0, 58.5], [17.5, 56.5], [13.6, 54.6], [12.1, 54.1]]
      }
    },
    {
      "type": "Feature",
      "properties": {
        "name": "TurkStream",
        "tier": "major",
        "type": "gas",
        "status": "active",
        "operator": "South Stream Transport",
        "capacity_bcm": 31.5,
        "length_km": 930,
        "countries": ["Russia", "Turkey"]
      },
      "geometry": {
        "type": "LineString",
        "coordinates": [[38.5, 44.6], [37.0, 43.0], [34.0, 42.5], [31.0, 42.0], [29.5, 41.5], [28.7, 41.2]]
      }
    },
    {
      "type": "Feature",
      "properties": {
        "name": "BTC Pipeline",
        "tier": "major",
        "type": "oil",
        "status": "active",
        "operator": "BP",
        "capacity_bcm": null,
        "length_km": 1768,
        "countries": ["Azerbaijan", "Georgia", "Turkey"]
      },
      "geometry": {
        "type": "LineString",
        "coordinates": [[49.9, 40.4], [47.5, 41.0], [45.0, 41.7], [43.5, 41.8], [41.0, 41.2], [39.5, 40.5], [37.0, 39.0], [36.0, 36.8]]
      }
    },
    {
      "type": "Feature",
      "properties": {
        "name": "TANAP",
        "tier": "major",
        "type": "gas",
        "status": "active",
        "operator": "SOCAR",
        "capacity_bcm": 16,
        "length_km": 1850,
        "countries": ["Azerbaijan", "Georgia", "Turkey", "Greece"]
      },
      "geometry": {
        "type": "LineString",
        "coordinates": [[49.9, 40.4], [47.5, 41.0], [43.5, 41.8], [41.0, 40.5], [39.0, 39.5], [36.0, 38.5], [33.0, 39.5], [30.0, 40.0], [27.0, 40.5], [26.0, 40.8]]
      }
    },
    {
      "type": "Feature",
      "properties": {
        "name": "Druzhba Pipeline",
        "tier": "major",
        "type": "oil",
        "status": "active",
        "operator": "Transneft",
        "capacity_bcm": null,
        "length_km": 5500,
        "countries": ["Russia", "Belarus", "Poland", "Germany", "Czech Republic", "Slovakia", "Hungary"]
      },
      "geometry": {
        "type": "LineString",
        "coordinates": [[52.0, 56.0], [48.0, 55.5], [43.0, 54.0], [38.0, 53.5], [33.0, 53.0], [28.0, 52.8], [24.0, 52.5], [21.0, 52.5], [18.0, 52.0], [14.5, 51.5]]
      }
    },
    {
      "type": "Feature",
      "properties": {
        "name": "East-West Pipeline",
        "tier": "major",
        "type": "oil",
        "status": "active",
        "operator": "Saudi Aramco",
        "capacity_bcm": null,
        "length_km": 1200,
        "countries": ["Saudi Arabia"]
      },
      "geometry": {
        "type": "LineString",
        "coordinates": [[50.1, 26.4], [48.5, 26.0], [46.0, 25.0], [44.0, 24.5], [42.0, 24.0], [39.5, 23.5], [38.0, 22.5]]
      }
    },
    {
      "type": "Feature",
      "properties": {
        "name": "Keystone Pipeline",
        "tier": "major",
        "type": "oil",
        "status": "active",
        "operator": "TC Energy",
        "capacity_bcm": null,
        "length_km": 3462,
        "countries": ["Canada", "United States"]
      },
      "geometry": {
        "type": "LineString",
        "coordinates": [[-110.0, 52.0], [-108.0, 50.0], [-105.0, 49.0], [-100.0, 46.0], [-97.0, 42.0], [-97.0, 38.0], [-96.0, 35.0], [-95.0, 32.0], [-94.5, 29.5]]
      }
    },
    {
      "type": "Feature",
      "properties": {
        "name": "Power of Siberia",
        "tier": "major",
        "type": "gas",
        "status": "active",
        "operator": "Gazprom",
        "capacity_bcm": 38,
        "length_km": 3000,
        "countries": ["Russia", "China"]
      },
      "geometry": {
        "type": "LineString",
        "coordinates": [[130.0, 53.0], [128.0, 51.0], [127.5, 49.5], [127.0, 48.0], [126.5, 46.5], [126.0, 45.0]]
      }
    },
    {
      "type": "Feature",
      "properties": {
        "name": "TAP (Trans Adriatic Pipeline)",
        "tier": "major",
        "type": "gas",
        "status": "active",
        "operator": "TAP AG",
        "capacity_bcm": 10,
        "length_km": 878,
        "countries": ["Greece", "Albania", "Italy"]
      },
      "geometry": {
        "type": "LineString",
        "coordinates": [[26.0, 40.8], [24.0, 40.5], [21.0, 40.2], [19.8, 40.5], [18.5, 40.8], [17.0, 41.0]]
      }
    },
    {
      "type": "Feature",
      "properties": {
        "name": "Yamal-Europe Pipeline",
        "tier": "major",
        "type": "gas",
        "status": "active",
        "operator": "Gazprom",
        "capacity_bcm": 33,
        "length_km": 4107,
        "countries": ["Russia", "Belarus", "Poland", "Germany"]
      },
      "geometry": {
        "type": "LineString",
        "coordinates": [[73.0, 68.0], [65.0, 62.0], [55.0, 58.0], [45.0, 55.0], [35.0, 53.5], [28.0, 52.5], [22.0, 52.0], [18.0, 52.5], [14.5, 52.5]]
      }
    }
  ]
}
```

This is 10 major trunk lines as seed data. Full dataset from Global Energy Monitor to be added later.

- [ ] **Step 2: Verify the file is valid JSON**

```bash
python3 -c "import json; json.load(open('services/frontend/public/data/pipelines.geojson')); print('Valid GeoJSON')"
```

- [ ] **Step 3: Commit**

```bash
git add services/frontend/public/data/pipelines.geojson
git commit -m "feat(frontend): add seed pipeline GeoJSON with 10 major trunk lines"
```

---

## Task 6: usePipelines Hook

**Files:**
- Create: `services/frontend/src/hooks/usePipelines.ts`

- [ ] **Step 1: Create the hook**

Create `services/frontend/src/hooks/usePipelines.ts`:

```typescript
import { useState, useEffect, useCallback } from "react";
import type { PipelineGeoJSON } from "../types";

/**
 * Fetches pipeline GeoJSON from static file.
 * Data is loaded once and cached — pipelines don't change at runtime.
 */
export function usePipelines(enabled: boolean) {
  const [data, setData] = useState<PipelineGeoJSON | null>(null);
  const [loading, setLoading] = useState(false);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);

  const fetchData = useCallback(async () => {
    if (!enabled || data) return; // already loaded
    setLoading(true);
    try {
      const res = await fetch("/data/pipelines.geojson");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const geojson = (await res.json()) as PipelineGeoJSON;
      setData(geojson);
      setLastUpdate(new Date());
    } catch {
      // keep null — pipelines not available
    } finally {
      setLoading(false);
    }
  }, [enabled, data]);

  useEffect(() => {
    if (!enabled) return;
    void fetchData();
  }, [enabled, fetchData]);

  return { pipelines: data, loading, lastUpdate };
}
```

- [ ] **Step 2: Commit**

```bash
git add services/frontend/src/hooks/usePipelines.ts
git commit -m "feat(frontend): add usePipelines hook for static GeoJSON loading"
```

---

## Task 7: PipelineLayer Component

**Files:**
- Create: `services/frontend/src/components/layers/PipelineLayer.tsx`

- [ ] **Step 1: Create the PipelineLayer**

Create `services/frontend/src/components/layers/PipelineLayer.tsx`:

```typescript
import { useEffect, useRef, useCallback } from "react";
import * as Cesium from "cesium";
import type { PipelineGeoJSON, PipelineFeature } from "../../types";
import { PIPELINE_COLORS, PIPELINE_LOD_THRESHOLDS } from "../../types/pipeline";

interface PipelineLayerProps {
  viewer: Cesium.Viewer | null;
  pipelines: PipelineGeoJSON | null;
  visible: boolean;
}

interface PipelineBillboard extends Cesium.Billboard {
  _pipelineData?: {
    name: string;
    type: string;
    status: string;
    operator: string | null;
    capacity_bcm: number | null;
    length_km: number | null;
    countries: string[];
    lat: number;
    lon: number;
  };
}

function getVisibleTier(altitudeMeters: number): Set<string> {
  const tiers = new Set<string>();
  for (const [tier, threshold] of Object.entries(PIPELINE_LOD_THRESHOLDS)) {
    if (altitudeMeters < threshold) {
      tiers.add(tier);
    }
  }
  // "major" is always visible (threshold = Infinity)
  tiers.add("major");
  return tiers;
}

function getCoordinatesFlat(feature: PipelineFeature): number[][] {
  if (feature.geometry.type === "LineString") {
    return feature.geometry.coordinates as number[][];
  }
  // MultiLineString — flatten to first segment
  return (feature.geometry.coordinates as number[][][])[0] ?? [];
}

export function PipelineLayer({ viewer, pipelines, visible }: PipelineLayerProps) {
  const polylineCollectionRef = useRef<Cesium.PolylineCollection | null>(null);
  const billboardCollectionRef = useRef<Cesium.BillboardCollection | null>(null);
  const labelCollectionRef = useRef<Cesium.LabelCollection | null>(null);
  const currentTiersRef = useRef<Set<string>>(new Set<string>());
  const labelsVisibleRef = useRef(false);

  const LABEL_ALTITUDE_THRESHOLD = 5_000_000;

  // Initialize collections
  useEffect(() => {
    if (!viewer || viewer.isDestroyed()) return;

    polylineCollectionRef.current = new Cesium.PolylineCollection();
    billboardCollectionRef.current = new Cesium.BillboardCollection({ scene: viewer.scene });
    labelCollectionRef.current = new Cesium.LabelCollection({ scene: viewer.scene });

    viewer.scene.primitives.add(polylineCollectionRef.current);
    viewer.scene.primitives.add(billboardCollectionRef.current);
    viewer.scene.primitives.add(labelCollectionRef.current);

    return () => {
      if (!viewer.isDestroyed()) {
        if (polylineCollectionRef.current) viewer.scene.primitives.remove(polylineCollectionRef.current);
        if (billboardCollectionRef.current) viewer.scene.primitives.remove(billboardCollectionRef.current);
        if (labelCollectionRef.current) viewer.scene.primitives.remove(labelCollectionRef.current);
      }
      polylineCollectionRef.current = null;
      billboardCollectionRef.current = null;
      labelCollectionRef.current = null;
    };
  }, [viewer]);

  // Render pipelines based on LOD
  const renderPipelines = useCallback(
    (tiers: Set<string>) => {
      const pc = polylineCollectionRef.current;
      const bc = billboardCollectionRef.current;
      const lc = labelCollectionRef.current;
      if (!pc || !bc || !lc || !pipelines) return;

      pc.removeAll();
      bc.removeAll();
      lc.removeAll();

      for (const feature of pipelines.features) {
        const props = feature.properties;
        if (!tiers.has(props.tier)) continue;

        const coords = getCoordinatesFlat(feature);
        if (coords.length < 2) continue;

        const positions = Cesium.Cartesian3.fromDegreesArray(
          coords.flatMap(([lon, lat]) => [lon, lat]),
        );

        const color = Cesium.Color.fromCssColorString(
          PIPELINE_COLORS[props.type] ?? PIPELINE_COLORS.mixed,
        );

        const isDashed = props.status !== "active";
        const width = props.status === "active" ? 2.0 : 1.5;

        pc.add({
          positions,
          width,
          material: isDashed
            ? Cesium.Material.fromType("PolylineDash", {
                color,
                dashLength: 16.0,
              })
            : Cesium.Material.fromType("Color", { color }),
        });

        // Midpoint billboard for click detection
        const midIdx = Math.floor(coords.length / 2);
        const midCoord = coords[midIdx];
        const bb = bc.add({
          position: Cesium.Cartesian3.fromDegrees(midCoord[0], midCoord[1]),
          image: createPipelineDot(PIPELINE_COLORS[props.type] ?? PIPELINE_COLORS.mixed),
          scale: 1.0,
          translucencyByDistance: new Cesium.NearFarScalar(1e5, 1.0, 1e7, 0.3),
        }) as PipelineBillboard;

        bb._pipelineData = {
          name: props.name,
          type: props.type,
          status: props.status,
          operator: props.operator,
          capacity_bcm: props.capacity_bcm,
          length_km: props.length_km,
          countries: props.countries,
          lat: midCoord[1],
          lon: midCoord[0],
        };

        // Label
        lc.add({
          position: Cesium.Cartesian3.fromDegrees(midCoord[0], midCoord[1]),
          text: props.name,
          font: "11px monospace",
          fillColor: color.withAlpha(0.8),
          outlineColor: Cesium.Color.BLACK,
          outlineWidth: 2,
          style: Cesium.LabelStyle.FILL_AND_OUTLINE,
          pixelOffset: new Cesium.Cartesian2(0, -12),
          show: labelsVisibleRef.current,
          disableDepthTestDistance: Number.POSITIVE_INFINITY,
        });
      }
    },
    [pipelines],
  );

  // Camera moveEnd listener for LOD + label visibility
  useEffect(() => {
    if (!viewer || viewer.isDestroyed() || !pipelines) return;

    const updateLOD = () => {
      if (!viewer || viewer.isDestroyed()) return;

      const altitude = viewer.camera.positionCartographic.height;
      const newTiers = getVisibleTier(altitude);

      // Check if tiers changed
      const tiersChanged =
        newTiers.size !== currentTiersRef.current.size ||
        [...newTiers].some((t) => !currentTiersRef.current.has(t));

      if (tiersChanged) {
        currentTiersRef.current = newTiers;
        renderPipelines(newTiers);
      }

      // Label visibility
      const shouldShowLabels = altitude < LABEL_ALTITUDE_THRESHOLD;
      if (shouldShowLabels !== labelsVisibleRef.current) {
        labelsVisibleRef.current = shouldShowLabels;
        const lc = labelCollectionRef.current;
        if (lc) {
          for (let i = 0; i < lc.length; i++) {
            lc.get(i).show = shouldShowLabels;
          }
        }
      }
    };

    viewer.camera.moveEnd.addEventListener(updateLOD);
    // Initial render at current camera altitude (not hardcoded to "major")
    updateLOD();

    return () => {
      if (!viewer.isDestroyed()) {
        viewer.camera.moveEnd.removeEventListener(updateLOD);
      }
    };
  }, [viewer, pipelines, renderPipelines]);

  // Visibility toggle
  useEffect(() => {
    if (polylineCollectionRef.current) polylineCollectionRef.current.show = visible;
    if (billboardCollectionRef.current) billboardCollectionRef.current.show = visible;
    if (labelCollectionRef.current) labelCollectionRef.current.show = visible;
  }, [visible]);

  return null;
}

/** Create a small colored dot for pipeline midpoint click targets. */
function createPipelineDot(color: string): string {
  const size = 12;
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d")!;
  ctx.beginPath();
  ctx.arc(size / 2, size / 2, size / 2 - 1, 0, Math.PI * 2);
  ctx.fillStyle = color;
  ctx.globalAlpha = 0.7;
  ctx.fill();
  return canvas.toDataURL();
}
```

- [ ] **Step 2: Verify type-check**

```bash
cd services/frontend && npx tsc --noEmit
```

- [ ] **Step 3: Commit**

```bash
git add services/frontend/src/components/layers/PipelineLayer.tsx
git commit -m "feat(frontend): add PipelineLayer with LOD, color-coded polylines, click targets"
```

---

## Task 8: Wire Pipeline Layer into App

**Files:**
- Modify: `services/frontend/src/App.tsx`
- Modify: `services/frontend/src/components/globe/EntityClickHandler.tsx`
- Modify: `services/frontend/src/components/ui/StatusBar.tsx`

- [ ] **Step 1: Add PipelineLayer imports and hook to App.tsx**

In `services/frontend/src/App.tsx`, add imports:

```typescript
import { PipelineLayer } from "./components/layers/PipelineLayer";
import { usePipelines } from "./hooks/usePipelines";
```

Add the hook call after the other hooks (after line 48):

```typescript
  const { pipelines: pipelineData, lastUpdate: pipelinesUpdate } = usePipelines(layers.pipelines);
```

- [ ] **Step 2: Add PipelineLayer component after CableLayer**

After the `<CableLayer ... />` line (line 118), add:

```tsx
      <PipelineLayer viewer={viewer} pipelines={pipelineData} visible={layers.pipelines} />
```

- [ ] **Step 3: Update StatusBar props**

Update the StatusBar freshness and counts to include pipelines:

```tsx
      <StatusBar
        freshness={{
          flights: flightsUpdate,
          satellites: satellitesUpdate,
          earthquakes: earthquakesUpdate,
          vessels: vesselsUpdate,
          events: eventsUpdate,
          cables: cablesUpdate,
          pipelines: pipelinesUpdate,
        }}
        flightCount={flights.length}
        satelliteCount={satellites.length}
        earthquakeCount={earthquakes.length}
        vesselCount={vessels.length}
        eventCount={events.length}
        cableCount={cables.length}
        pipelineCount={pipelineData?.features.length ?? 0}
      />
```

- [ ] **Step 4: Add pipeline click handling to EntityClickHandler**

In `services/frontend/src/components/globe/EntityClickHandler.tsx`, add a new guard block after the `cableData` block (after line 94, before the `vesselData` guard). Follow the existing `setSelected` + `_...Data` pattern:

```typescript
      // Guard: Pipeline billboard (custom _pipelineData property)
      const pipelineData = (picked?.primitive as Record<string, unknown>)?._pipelineData as
        | {
            name: string;
            type: string;
            status: string;
            operator: string | null;
            capacity_bcm: number | null;
            length_km: number | null;
            countries: string[];
            lat: number;
            lon: number;
          }
        | undefined;

      if (pipelineData) {
        const props: Record<string, string> = {};
        props.type = pipelineData.type.toUpperCase();
        props.status = pipelineData.status.replace("_", " ").toUpperCase();
        if (pipelineData.operator) props.operator = pipelineData.operator;
        if (pipelineData.capacity_bcm != null) props.capacity = `${pipelineData.capacity_bcm} bcm/yr`;
        if (pipelineData.length_km != null) props.length = `${Math.round(pipelineData.length_km).toLocaleString()} km`;
        if (pipelineData.countries.length > 0) props.countries = pipelineData.countries.join(", ");

        setSelected({
          id: pipelineData.name,
          name: pipelineData.name,
          type: "pipeline",
          position: { lat: pipelineData.lat, lon: pipelineData.lon },
          properties: props,
        });
        return;
      }
```

Also update the `_pipelineData` assignment in `PipelineLayer.tsx` (Task 7) to include `lat` and `lon` from the midpoint coordinate:

```typescript
        bb._pipelineData = {
          name: props.name,
          type: props.type,
          status: props.status,
          operator: props.operator,
          capacity_bcm: props.capacity_bcm,
          length_km: props.length_km,
          countries: props.countries,
          lat: midCoord[1],
          lon: midCoord[0],
        };
```

- [ ] **Step 5: Update StatusBar component to accept pipelineCount**

In `services/frontend/src/components/ui/StatusBar.tsx`, add `pipelineCount` to the props interface and render it. Find the existing count display pattern and add:

```tsx
        <span>PIPES</span>
        <span className="text-yellow-400">{pipelineCount}</span>
```

- [ ] **Step 6: Run type-check + visual verification**

```bash
cd services/frontend && npx tsc --noEmit && npm run dev
```

Open `http://localhost:5173`. Enable PIPELINES layer. Major trunk lines should appear as colored polylines. Zoom in — more detail. Click a pipeline midpoint — popup with details.

- [ ] **Step 7: Commit**

```bash
git add services/frontend/src/App.tsx services/frontend/src/components/globe/EntityClickHandler.tsx services/frontend/src/components/ui/StatusBar.tsx
git commit -m "feat(frontend): wire PipelineLayer into App with click handling and status bar"
```

---

## Task 9: Final Verification

- [ ] **Step 1: Run full type-check**

```bash
cd services/frontend && npx tsc --noEmit
```

Expected: No errors.

- [ ] **Step 2: Run lint**

```bash
cd services/frontend && npm run lint
```

Expected: No new errors.

- [ ] **Step 3: Run backend tests**

```bash
cd services/backend && uv run pytest tests/ -v
```

Expected: All pass (config default change should be backward-compatible).

- [ ] **Step 4: Visual verification checklist**

```bash
cd services/frontend && npm run dev
```

- [ ] Terrain: Mountains have visible 3D relief
- [ ] Terrain: Ocean bathymetry visible when zoomed in
- [ ] Icons: All 8 sidebar icons are colored SVGs
- [ ] Icons: Toggle ON/OFF changes color/opacity
- [ ] Pipelines: Major trunk lines visible at global zoom
- [ ] Pipelines: More pipelines appear when zooming in
- [ ] Pipelines: Oil=yellow, Gas=orange lines
- [ ] Pipelines: Click shows name, operator, countries
- [ ] Pipelines: Labels appear when zoomed in, hide when zoomed out
- [ ] StatusBar: PIPES count shown
- [ ] FPS: No noticeable performance degradation

- [ ] **Step 5: Commit any remaining fixes**

```bash
git add -A && git status
# Only commit if there are actual fixes
```
