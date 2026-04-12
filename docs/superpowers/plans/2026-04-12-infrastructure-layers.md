# Infrastructure Layers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two static infrastructure layers (Datacenter + Refineries) to the CesiumJS globe, following the PipelineLayer pattern with filled/intel-style icons.

**Architecture:** Static GeoJSON files in `public/data/`, lazy-loaded via enabled-gated hooks on first toggle. Each layer renders as a BillboardCollection with layer-local click handlers feeding into the existing SelectionPanel. Both sit in CORE_LAYERS in the OperationsPanel.

**Tech Stack:** React 19, TypeScript, CesiumJS, Vitest, Canvas 2D API

**Spec:** `docs/superpowers/specs/2026-04-12-infrastructure-layers-design.md`

---

## File Structure

All paths relative to `services/frontend/`.

### New files:
| File | Responsibility |
|------|---------------|
| `public/data/datacenters.geojson` | Static datacenter dataset (~200 entries) |
| `public/data/refineries.geojson` | Static refinery dataset (~150 entries) |
| `src/types/infrastructure.ts` | TypeScript types for GeoJSON properties |
| `src/hooks/useDatacenters.ts` | Lazy-loading hook for datacenter GeoJSON |
| `src/hooks/useRefineries.ts` | Lazy-loading hook for refinery GeoJSON |
| `src/components/layers/DatacenterLayer.tsx` | Cesium BillboardCollection + click handler |
| `src/components/layers/RefineryLayer.tsx` | Cesium BillboardCollection + click handler |
| `src/hooks/__tests__/useDatacenters.test.ts` | Hook unit tests |
| `src/hooks/__tests__/useRefineries.test.ts` | Hook unit tests |
| `src/components/layers/__tests__/DatacenterLayer.test.tsx` | Layer component tests |
| `src/components/layers/__tests__/RefineryLayer.test.tsx` | Layer component tests |

### Modified files:
| File | Change |
|------|--------|
| `src/types/index.ts` | Add `datacenters` + `refineries` to `LayerVisibility`, re-export infrastructure types |
| `src/components/ui/OperationsPanel.tsx` | Add entries to `CORE_LAYERS`, add `LayerIcon` cases |
| `src/components/ui/SelectionPanel.tsx` | Add `datacenter` + `refinery` to `Selected` union, add content components |
| `src/App.tsx` | Wire hooks, render layers, update default visibility |

---

### Task 1: Types + LayerVisibility

**Files:**
- Create: `src/types/infrastructure.ts`
- Modify: `src/types/index.ts`

- [ ] **Step 1: Create infrastructure types**

Create `src/types/infrastructure.ts`:

```typescript
export type DatacenterTier = "III" | "IV" | "hyperscaler";
export type RefineryStatus = "active" | "planned" | "shutdown";

export interface DatacenterProperties {
  name: string;
  operator: string;
  tier: DatacenterTier;
  capacity_mw: number | null;
  country: string;
  city: string;
}

export interface RefineryProperties {
  name: string;
  operator: string;
  capacity_bpd: number;
  country: string;
  status: RefineryStatus;
}

export interface InfraFeature<T> {
  type: "Feature";
  geometry: {
    type: "Point";
    coordinates: [number, number]; // [lon, lat]
  };
  properties: T;
}

export interface InfraGeoJSON<T> {
  type: "FeatureCollection";
  features: InfraFeature<T>[];
}

export type DatacenterGeoJSON = InfraGeoJSON<DatacenterProperties>;
export type RefineryGeoJSON = InfraGeoJSON<RefineryProperties>;
```

- [ ] **Step 2: Extend LayerVisibility in types/index.ts**

Add to the `LayerVisibility` interface (after `milAircraft: boolean;`):

```typescript
  datacenters: boolean;
  refineries: boolean;
```

Add re-exports at the bottom of `src/types/index.ts`:

```typescript
export type {
  DatacenterTier,
  RefineryStatus,
  DatacenterProperties,
  RefineryProperties,
  InfraFeature,
  InfraGeoJSON,
  DatacenterGeoJSON,
  RefineryGeoJSON,
} from "./infrastructure";
```

- [ ] **Step 3: Run type-check**

Run: `cd services/frontend && npx tsc --noEmit`
Expected: Clean (0 errors). The new `datacenters`/`refineries` fields will cause errors in `App.tsx` and `OperationsPanel.tsx` where `LayerVisibility` objects are constructed — these are expected and will be fixed in later tasks.

Note: If type-check shows errors in `App.tsx` default state or backend config fallback, that's expected — those files construct `LayerVisibility` literals that now need the new fields. We fix them in Task 8.

- [ ] **Step 4: Commit**

```bash
git add src/types/infrastructure.ts src/types/index.ts
git commit -m "feat(frontend): add infrastructure types and extend LayerVisibility"
```

---

### Task 2: GeoJSON Data Files

**Files:**
- Create: `public/data/datacenters.geojson`
- Create: `public/data/refineries.geojson`

- [ ] **Step 1: Create datacenter GeoJSON**

Create `public/data/datacenters.geojson` with ~200 entries. The file must be a valid GeoJSON FeatureCollection with Point geometries.

Each feature follows this schema:
```json
{
  "type": "Feature",
  "geometry": { "type": "Point", "coordinates": [-77.4875, 39.0438] },
  "properties": {
    "name": "AWS US-East-1 (Ashburn)",
    "operator": "Amazon Web Services",
    "tier": "hyperscaler",
    "capacity_mw": 600,
    "country": "US",
    "city": "Ashburn"
  }
}
```

**Data sources to compile from:**
- Wikipedia "List of largest data centers" — covers hyperscalers globally
- Major operators: AWS (30+ regions), Google Cloud (35+ regions), Microsoft Azure (60+ regions), Meta (20+ DCs), Equinix (240+ IBX), Digital Realty, NTT, CyrusOne, QTS, CoreSite
- Filter: Tier III+, hyperscaler campuses, or >10 MW capacity
- `capacity_mw` may be `null` if unknown
- `country` uses ISO 3166-1 alpha-2 codes

- [ ] **Step 2: Create refinery GeoJSON**

Create `public/data/refineries.geojson` with ~150 entries. Same FeatureCollection format.

Each feature follows this schema:
```json
{
  "type": "Feature",
  "geometry": { "type": "Point", "coordinates": [72.0, 22.3] },
  "properties": {
    "name": "Jamnagar Refinery",
    "operator": "Reliance Industries",
    "capacity_bpd": 1240000,
    "country": "IN",
    "status": "active"
  }
}
```

**Data sources to compile from:**
- Wikipedia "List of oil refineries" — global, with capacity
- Global Energy Monitor — Global Oil Infrastructure Tracker
- EIA (US refineries with exact capacity)
- Filter: capacity > 100,000 bbl/day
- Include key producers: Saudi Arabia, USA, China, India, Russia, South Korea, Japan, Germany, Netherlands, Singapore
- `status` is one of: `"active"`, `"planned"`, `"shutdown"`

- [ ] **Step 3: Validate both files**

Run:
```bash
cd services/frontend
node -e "const d=JSON.parse(require('fs').readFileSync('public/data/datacenters.geojson','utf8')); console.log('Datacenters:', d.features.length, 'features'); const first=d.features[0]; console.log('Sample:', first.properties.name, first.geometry.coordinates);"
node -e "const d=JSON.parse(require('fs').readFileSync('public/data/refineries.geojson','utf8')); console.log('Refineries:', d.features.length, 'features'); const first=d.features[0]; console.log('Sample:', first.properties.name, first.geometry.coordinates);"
```

Expected: Valid JSON, feature counts in expected range (150-250 datacenters, 120-200 refineries), coordinates as `[lon, lat]`.

- [ ] **Step 4: Commit**

```bash
git add public/data/datacenters.geojson public/data/refineries.geojson
git commit -m "feat(frontend): add static GeoJSON for datacenters and refineries"
```

---

### Task 3: useDatacenters Hook + Tests

**Files:**
- Create: `src/hooks/useDatacenters.ts`
- Create: `src/hooks/__tests__/useDatacenters.test.ts`

- [ ] **Step 1: Write failing tests**

Create `src/hooks/__tests__/useDatacenters.test.ts`:

```typescript
import { describe, it, expect, vi, afterEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { useDatacenters } from "../useDatacenters";

const MOCK_GEOJSON = {
  type: "FeatureCollection" as const,
  features: [
    {
      type: "Feature" as const,
      geometry: { type: "Point" as const, coordinates: [-77.49, 39.04] },
      properties: {
        name: "Test DC",
        operator: "TestCorp",
        tier: "hyperscaler" as const,
        capacity_mw: 100,
        country: "US",
        city: "Ashburn",
      },
    },
  ],
};

describe("useDatacenters", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("does not fetch when disabled", () => {
    const spy = vi.spyOn(globalThis, "fetch");
    renderHook(() => useDatacenters(false));
    expect(spy).not.toHaveBeenCalled();
  });

  it("fetches GeoJSON when enabled", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => MOCK_GEOJSON,
    } as Response);

    const { result } = renderHook(() => useDatacenters(true));
    await waitFor(() => expect(result.current.datacenters).not.toBeNull());
    expect(result.current.datacenters!.features).toHaveLength(1);
    expect(result.current.lastUpdate).toBeInstanceOf(Date);
  });

  it("does not re-fetch once loaded", async () => {
    const spy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => MOCK_GEOJSON,
    } as Response);

    const { result, rerender } = renderHook(
      ({ on }: { on: boolean }) => useDatacenters(on),
      { initialProps: { on: true } },
    );
    await waitFor(() => expect(result.current.datacenters).not.toBeNull());

    rerender({ on: false });
    rerender({ on: true });
    expect(spy).toHaveBeenCalledTimes(1);
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd services/frontend && npx vitest run src/hooks/__tests__/useDatacenters.test.ts`
Expected: FAIL — module `../useDatacenters` not found.

- [ ] **Step 3: Implement useDatacenters**

Create `src/hooks/useDatacenters.ts`:

```typescript
import { useState, useEffect, useCallback } from "react";
import type { DatacenterGeoJSON } from "../types";

export function useDatacenters(enabled: boolean) {
  const [data, setData] = useState<DatacenterGeoJSON | null>(null);
  const [loading, setLoading] = useState(false);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);

  const fetchData = useCallback(async () => {
    if (!enabled || data) return;
    setLoading(true);
    try {
      const res = await fetch("/data/datacenters.geojson");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const geojson = (await res.json()) as DatacenterGeoJSON;
      setData(geojson);
      setLastUpdate(new Date());
    } catch {
      // keep null — datacenters not available
    } finally {
      setLoading(false);
    }
  }, [enabled, data]);

  useEffect(() => {
    if (!enabled) return;
    void fetchData();
  }, [enabled, fetchData]);

  return { datacenters: data, loading, lastUpdate };
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd services/frontend && npx vitest run src/hooks/__tests__/useDatacenters.test.ts`
Expected: 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/hooks/useDatacenters.ts src/hooks/__tests__/useDatacenters.test.ts
git commit -m "feat(frontend): add useDatacenters hook with lazy loading"
```

---

### Task 4: useRefineries Hook + Tests

**Files:**
- Create: `src/hooks/useRefineries.ts`
- Create: `src/hooks/__tests__/useRefineries.test.ts`

- [ ] **Step 1: Write failing tests**

Create `src/hooks/__tests__/useRefineries.test.ts`:

```typescript
import { describe, it, expect, vi, afterEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { useRefineries } from "../useRefineries";

const MOCK_GEOJSON = {
  type: "FeatureCollection" as const,
  features: [
    {
      type: "Feature" as const,
      geometry: { type: "Point" as const, coordinates: [72.0, 22.3] },
      properties: {
        name: "Test Refinery",
        operator: "TestOil",
        capacity_bpd: 500000,
        country: "IN",
        status: "active" as const,
      },
    },
  ],
};

describe("useRefineries", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("does not fetch when disabled", () => {
    const spy = vi.spyOn(globalThis, "fetch");
    renderHook(() => useRefineries(false));
    expect(spy).not.toHaveBeenCalled();
  });

  it("fetches GeoJSON when enabled", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => MOCK_GEOJSON,
    } as Response);

    const { result } = renderHook(() => useRefineries(true));
    await waitFor(() => expect(result.current.refineries).not.toBeNull());
    expect(result.current.refineries!.features).toHaveLength(1);
    expect(result.current.lastUpdate).toBeInstanceOf(Date);
  });

  it("does not re-fetch once loaded", async () => {
    const spy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => MOCK_GEOJSON,
    } as Response);

    const { result, rerender } = renderHook(
      ({ on }: { on: boolean }) => useRefineries(on),
      { initialProps: { on: true } },
    );
    await waitFor(() => expect(result.current.refineries).not.toBeNull());

    rerender({ on: false });
    rerender({ on: true });
    expect(spy).toHaveBeenCalledTimes(1);
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd services/frontend && npx vitest run src/hooks/__tests__/useRefineries.test.ts`
Expected: FAIL — module `../useRefineries` not found.

- [ ] **Step 3: Implement useRefineries**

Create `src/hooks/useRefineries.ts`:

```typescript
import { useState, useEffect, useCallback } from "react";
import type { RefineryGeoJSON } from "../types";

export function useRefineries(enabled: boolean) {
  const [data, setData] = useState<RefineryGeoJSON | null>(null);
  const [loading, setLoading] = useState(false);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);

  const fetchData = useCallback(async () => {
    if (!enabled || data) return;
    setLoading(true);
    try {
      const res = await fetch("/data/refineries.geojson");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const geojson = (await res.json()) as RefineryGeoJSON;
      setData(geojson);
      setLastUpdate(new Date());
    } catch {
      // keep null — refineries not available
    } finally {
      setLoading(false);
    }
  }, [enabled, data]);

  useEffect(() => {
    if (!enabled) return;
    void fetchData();
  }, [enabled, fetchData]);

  return { refineries: data, loading, lastUpdate };
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd services/frontend && npx vitest run src/hooks/__tests__/useRefineries.test.ts`
Expected: 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/hooks/useRefineries.ts src/hooks/__tests__/useRefineries.test.ts
git commit -m "feat(frontend): add useRefineries hook with lazy loading"
```

---

### Task 5: DatacenterLayer Component + Tests

**Files:**
- Create: `src/components/layers/DatacenterLayer.tsx`
- Create: `src/components/layers/__tests__/DatacenterLayer.test.tsx`

- [ ] **Step 1: Write failing tests**

Create `src/components/layers/__tests__/DatacenterLayer.test.tsx`:

```typescript
import { describe, it, expect, vi } from "vitest";
import { render } from "@testing-library/react";
import * as Cesium from "cesium";
import { DatacenterLayer, createDatacenterIcon } from "../DatacenterLayer";
import type { DatacenterGeoJSON } from "../../../types";

function fakeViewer(): Cesium.Viewer {
  const primitives = {
    add: vi.fn((p: unknown) => p),
    remove: vi.fn(),
  };
  const canvas = document.createElement("canvas");
  return {
    scene: {
      primitives,
      requestRender: vi.fn(),
      camera: { positionCartographic: { height: 10_000_000 } },
      pick: vi.fn(() => undefined),
    },
    canvas,
    isDestroyed: () => false,
  } as unknown as Cesium.Viewer;
}

const MOCK_DATA: DatacenterGeoJSON = {
  type: "FeatureCollection",
  features: [
    {
      type: "Feature",
      geometry: { type: "Point", coordinates: [-77.49, 39.04] },
      properties: {
        name: "Test DC 1",
        operator: "AWS",
        tier: "hyperscaler",
        capacity_mw: 600,
        country: "US",
        city: "Ashburn",
      },
    },
    {
      type: "Feature",
      geometry: { type: "Point", coordinates: [2.35, 48.86] },
      properties: {
        name: "Test DC 2",
        operator: "Equinix",
        tier: "IV",
        capacity_mw: null,
        country: "FR",
        city: "Paris",
      },
    },
  ],
};

describe("createDatacenterIcon", () => {
  it("returns a canvas of correct size", () => {
    const c = createDatacenterIcon(32);
    expect(c.width).toBe(32);
    expect(c.height).toBe(32);
  });
});

describe("DatacenterLayer", () => {
  it("renders without throwing", () => {
    const viewer = fakeViewer();
    render(
      <DatacenterLayer
        viewer={viewer}
        datacenters={MOCK_DATA}
        visible={true}
        onSelect={vi.fn()}
      />,
    );
  });

  it("adds billboard and label collections to scene", () => {
    const viewer = fakeViewer();
    render(
      <DatacenterLayer
        viewer={viewer}
        datacenters={MOCK_DATA}
        visible={true}
        onSelect={vi.fn()}
      />,
    );
    expect(viewer.scene.primitives.add).toHaveBeenCalled();
  });

  it("renders null to DOM", () => {
    const viewer = fakeViewer();
    const { container } = render(
      <DatacenterLayer
        viewer={viewer}
        datacenters={MOCK_DATA}
        visible={true}
        onSelect={vi.fn()}
      />,
    );
    expect(container.innerHTML).toBe("");
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd services/frontend && npx vitest run src/components/layers/__tests__/DatacenterLayer.test.tsx`
Expected: FAIL — module `../DatacenterLayer` not found.

- [ ] **Step 3: Implement DatacenterLayer**

Create `src/components/layers/DatacenterLayer.tsx`:

```typescript
import { useEffect, useRef } from "react";
import * as Cesium from "cesium";
import type { DatacenterGeoJSON, DatacenterProperties } from "../../types";

const ICON_COLOR = "#00e5ff";
const LABEL_ALTITUDE_THRESHOLD = 5_000_000;

export function createDatacenterIcon(size = 32): HTMLCanvasElement {
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d");
  if (!ctx) return canvas;

  const pad = size * 0.15;
  const w = size - pad * 2;
  const h = size - pad * 2;
  const x = pad;
  const y = pad;

  // Building outline
  ctx.fillStyle = "rgba(0, 229, 255, 0.15)";
  ctx.strokeStyle = ICON_COLOR;
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.roundRect(x, y, w, h, 3);
  ctx.fill();
  ctx.stroke();

  // Server rows (3 shelves)
  const rowH = h * 0.18;
  const rowW = w * 0.7;
  const rowX = x + (w - rowW) / 2;
  for (let i = 0; i < 3; i++) {
    const rowY = y + h * 0.15 + i * (rowH + h * 0.08);
    ctx.fillStyle = "rgba(0, 229, 255, 0.25)";
    ctx.beginPath();
    ctx.roundRect(rowX, rowY, rowW, rowH, 1.5);
    ctx.fill();

    // Status LED
    const ledR = size * 0.04;
    const ledX = rowX + rowW - ledR * 3;
    const ledY = rowY + rowH / 2;
    ctx.fillStyle = i === 1 ? "#00ff88" : ICON_COLOR;
    ctx.beginPath();
    ctx.arc(ledX, ledY, ledR, 0, Math.PI * 2);
    ctx.fill();
  }

  // Network symbol at top
  ctx.strokeStyle = ICON_COLOR;
  ctx.lineWidth = 1.2;
  const topCx = size / 2;
  const topCy = y - size * 0.02;
  ctx.beginPath();
  ctx.arc(topCx, topCy, size * 0.07, 0, Math.PI * 2);
  ctx.stroke();
  ctx.beginPath();
  ctx.moveTo(topCx, topCy + size * 0.07);
  ctx.lineTo(topCx, y);
  ctx.stroke();

  return canvas;
}

interface DatacenterLayerProps {
  viewer: Cesium.Viewer | null;
  datacenters: DatacenterGeoJSON | null;
  visible: boolean;
  onSelect?: (props: DatacenterProperties) => void;
}

export function DatacenterLayer({ viewer, datacenters, visible, onSelect }: DatacenterLayerProps) {
  const billboardCollectionRef = useRef<Cesium.BillboardCollection | null>(null);
  const labelCollectionRef = useRef<Cesium.LabelCollection | null>(null);
  const idMapRef = useRef<Map<object, DatacenterProperties>>(new Map());
  const handlerRef = useRef<Cesium.ScreenSpaceEventHandler | null>(null);
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;
  const iconRef = useRef<HTMLCanvasElement | null>(null);

  // Setup collections + click handler
  useEffect(() => {
    if (!viewer || viewer.isDestroyed()) return;
    if (!billboardCollectionRef.current) {
      billboardCollectionRef.current = new Cesium.BillboardCollection({ scene: viewer.scene });
      viewer.scene.primitives.add(billboardCollectionRef.current);
    }
    if (!labelCollectionRef.current) {
      labelCollectionRef.current = new Cesium.LabelCollection({ scene: viewer.scene });
      viewer.scene.primitives.add(labelCollectionRef.current);
    }
    if (!handlerRef.current) {
      const h = new Cesium.ScreenSpaceEventHandler(viewer.canvas);
      h.setInputAction((movement: Cesium.ScreenSpaceEventHandler.PositionedEvent) => {
        const picked = viewer.scene.pick(movement.position);
        if (!picked) return;
        const props = idMapRef.current.get(picked.primitive as unknown as object);
        if (props && onSelectRef.current) onSelectRef.current(props);
      }, Cesium.ScreenSpaceEventType.LEFT_CLICK);
      handlerRef.current = h;
    }
    return () => {
      if (handlerRef.current) {
        handlerRef.current.destroy();
        handlerRef.current = null;
      }
      if (!viewer.isDestroyed()) {
        if (billboardCollectionRef.current) viewer.scene.primitives.remove(billboardCollectionRef.current);
        if (labelCollectionRef.current) viewer.scene.primitives.remove(labelCollectionRef.current);
      }
      billboardCollectionRef.current = null;
      labelCollectionRef.current = null;
      idMapRef.current.clear();
    };
  }, [viewer]);

  // Render billboards + labels
  useEffect(() => {
    const bc = billboardCollectionRef.current;
    const lc = labelCollectionRef.current;
    if (!bc || !lc) return;
    bc.removeAll();
    lc.removeAll();
    idMapRef.current.clear();
    if (!visible || !datacenters) return;

    if (!iconRef.current) {
      iconRef.current = createDatacenterIcon(32);
    }

    for (const feature of datacenters.features) {
      const [lon, lat] = feature.geometry.coordinates;
      const position = Cesium.Cartesian3.fromDegrees(lon, lat);

      const bb = bc.add({
        position,
        image: iconRef.current,
        scale: 0.8,
        eyeOffset: new Cesium.Cartesian3(0, 0, -20),
      });
      idMapRef.current.set(bb as unknown as object, feature.properties);

      lc.add({
        position,
        text: feature.properties.name,
        font: "11px monospace",
        fillColor: Cesium.Color.fromCssColorString(ICON_COLOR).withAlpha(0.9),
        outlineColor: Cesium.Color.BLACK,
        outlineWidth: 2,
        style: Cesium.LabelStyle.FILL_AND_OUTLINE,
        pixelOffset: new Cesium.Cartesian2(0, -22),
        distanceDisplayCondition: new Cesium.DistanceDisplayCondition(0, LABEL_ALTITUDE_THRESHOLD),
        scale: 0.9,
      });
    }
  }, [datacenters, visible, viewer]);

  return null;
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd services/frontend && npx vitest run src/components/layers/__tests__/DatacenterLayer.test.tsx`
Expected: 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/components/layers/DatacenterLayer.tsx src/components/layers/__tests__/DatacenterLayer.test.tsx
git commit -m "feat(frontend): add DatacenterLayer with filled intel-style icon"
```

---

### Task 6: RefineryLayer Component + Tests

**Files:**
- Create: `src/components/layers/RefineryLayer.tsx`
- Create: `src/components/layers/__tests__/RefineryLayer.test.tsx`

- [ ] **Step 1: Write failing tests**

Create `src/components/layers/__tests__/RefineryLayer.test.tsx`:

```typescript
import { describe, it, expect, vi } from "vitest";
import { render } from "@testing-library/react";
import * as Cesium from "cesium";
import { RefineryLayer, createRefineryIcon } from "../RefineryLayer";
import type { RefineryGeoJSON } from "../../../types";

function fakeViewer(): Cesium.Viewer {
  const primitives = {
    add: vi.fn((p: unknown) => p),
    remove: vi.fn(),
  };
  const canvas = document.createElement("canvas");
  return {
    scene: {
      primitives,
      requestRender: vi.fn(),
      camera: { positionCartographic: { height: 10_000_000 } },
      pick: vi.fn(() => undefined),
    },
    canvas,
    isDestroyed: () => false,
  } as unknown as Cesium.Viewer;
}

const MOCK_DATA: RefineryGeoJSON = {
  type: "FeatureCollection",
  features: [
    {
      type: "Feature",
      geometry: { type: "Point", coordinates: [72.0, 22.3] },
      properties: {
        name: "Jamnagar Refinery",
        operator: "Reliance Industries",
        capacity_bpd: 1240000,
        country: "IN",
        status: "active",
      },
    },
    {
      type: "Feature",
      geometry: { type: "Point", coordinates: [50.1, 26.6] },
      properties: {
        name: "Ras Tanura",
        operator: "Saudi Aramco",
        capacity_bpd: 550000,
        country: "SA",
        status: "active",
      },
    },
  ],
};

describe("createRefineryIcon", () => {
  it("returns a canvas of correct size", () => {
    const c = createRefineryIcon(32);
    expect(c.width).toBe(32);
    expect(c.height).toBe(32);
  });
});

describe("RefineryLayer", () => {
  it("renders without throwing", () => {
    const viewer = fakeViewer();
    render(
      <RefineryLayer
        viewer={viewer}
        refineries={MOCK_DATA}
        visible={true}
        onSelect={vi.fn()}
      />,
    );
  });

  it("adds billboard and label collections to scene", () => {
    const viewer = fakeViewer();
    render(
      <RefineryLayer
        viewer={viewer}
        refineries={MOCK_DATA}
        visible={true}
        onSelect={vi.fn()}
      />,
    );
    expect(viewer.scene.primitives.add).toHaveBeenCalled();
  });

  it("renders null to DOM", () => {
    const viewer = fakeViewer();
    const { container } = render(
      <RefineryLayer
        viewer={viewer}
        refineries={MOCK_DATA}
        visible={true}
        onSelect={vi.fn()}
      />,
    );
    expect(container.innerHTML).toBe("");
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd services/frontend && npx vitest run src/components/layers/__tests__/RefineryLayer.test.tsx`
Expected: FAIL — module `../RefineryLayer` not found.

- [ ] **Step 3: Implement RefineryLayer**

Create `src/components/layers/RefineryLayer.tsx`:

```typescript
import { useEffect, useRef } from "react";
import * as Cesium from "cesium";
import type { RefineryGeoJSON, RefineryProperties } from "../../types";

const ICON_COLOR = "#ff8f00";
const LABEL_ALTITUDE_THRESHOLD = 5_000_000;

export function createRefineryIcon(size = 32): HTMLCanvasElement {
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d");
  if (!ctx) return canvas;

  const baseY = size * 0.85;

  // Main distillation tower (tall center)
  const towerW = size * 0.22;
  const towerH = size * 0.55;
  const towerX = size * 0.38;
  const towerY = baseY - towerH;
  const towerR = towerW / 2;
  ctx.fillStyle = "rgba(255, 143, 0, 0.2)";
  ctx.strokeStyle = ICON_COLOR;
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.roundRect(towerX, towerY, towerW, towerH, towerR);
  ctx.fill();
  ctx.stroke();

  // Left smaller column
  const colW = size * 0.16;
  const colH = size * 0.4;
  const colX = size * 0.14;
  const colY = baseY - colH;
  ctx.fillStyle = "rgba(255, 143, 0, 0.15)";
  ctx.lineWidth = 1.2;
  ctx.beginPath();
  ctx.roundRect(colX, colY, colW, colH, colW / 2);
  ctx.fill();
  ctx.stroke();

  // Right chimney
  const chimW = size * 0.1;
  const chimH = size * 0.45;
  const chimX = size * 0.7;
  const chimY = baseY - chimH;
  ctx.fillStyle = "rgba(255, 143, 0, 0.15)";
  ctx.lineWidth = 1.2;
  ctx.beginPath();
  ctx.roundRect(chimX, chimY, chimW, chimH, 1);
  ctx.fill();
  ctx.stroke();

  // Smoke/emission circles
  const smokeX = chimX + chimW / 2;
  ctx.fillStyle = "rgba(255, 143, 0, 0.12)";
  ctx.strokeStyle = ICON_COLOR;
  ctx.lineWidth = 0.8;
  ctx.beginPath();
  ctx.arc(smokeX, chimY - size * 0.06, size * 0.06, 0, Math.PI * 2);
  ctx.fill();
  ctx.stroke();
  ctx.beginPath();
  ctx.arc(smokeX + size * 0.04, chimY - size * 0.14, size * 0.045, 0, Math.PI * 2);
  ctx.fill();
  ctx.stroke();

  // Connecting pipes
  ctx.strokeStyle = ICON_COLOR;
  ctx.lineWidth = 1.2;
  ctx.beginPath();
  ctx.moveTo(colX + colW, colY + colH * 0.4);
  ctx.lineTo(towerX, towerY + towerH * 0.4);
  ctx.stroke();
  ctx.beginPath();
  ctx.moveTo(towerX + towerW, towerY + towerH * 0.5);
  ctx.lineTo(chimX, chimY + chimH * 0.5);
  ctx.stroke();

  // Base platform
  ctx.strokeStyle = ICON_COLOR;
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.moveTo(size * 0.06, baseY);
  ctx.lineTo(size * 0.88, baseY);
  ctx.stroke();

  return canvas;
}

interface RefineryLayerProps {
  viewer: Cesium.Viewer | null;
  refineries: RefineryGeoJSON | null;
  visible: boolean;
  onSelect?: (props: RefineryProperties) => void;
}

export function RefineryLayer({ viewer, refineries, visible, onSelect }: RefineryLayerProps) {
  const billboardCollectionRef = useRef<Cesium.BillboardCollection | null>(null);
  const labelCollectionRef = useRef<Cesium.LabelCollection | null>(null);
  const idMapRef = useRef<Map<object, RefineryProperties>>(new Map());
  const handlerRef = useRef<Cesium.ScreenSpaceEventHandler | null>(null);
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;
  const iconRef = useRef<HTMLCanvasElement | null>(null);

  // Setup collections + click handler
  useEffect(() => {
    if (!viewer || viewer.isDestroyed()) return;
    if (!billboardCollectionRef.current) {
      billboardCollectionRef.current = new Cesium.BillboardCollection({ scene: viewer.scene });
      viewer.scene.primitives.add(billboardCollectionRef.current);
    }
    if (!labelCollectionRef.current) {
      labelCollectionRef.current = new Cesium.LabelCollection({ scene: viewer.scene });
      viewer.scene.primitives.add(labelCollectionRef.current);
    }
    if (!handlerRef.current) {
      const h = new Cesium.ScreenSpaceEventHandler(viewer.canvas);
      h.setInputAction((movement: Cesium.ScreenSpaceEventHandler.PositionedEvent) => {
        const picked = viewer.scene.pick(movement.position);
        if (!picked) return;
        const props = idMapRef.current.get(picked.primitive as unknown as object);
        if (props && onSelectRef.current) onSelectRef.current(props);
      }, Cesium.ScreenSpaceEventType.LEFT_CLICK);
      handlerRef.current = h;
    }
    return () => {
      if (handlerRef.current) {
        handlerRef.current.destroy();
        handlerRef.current = null;
      }
      if (!viewer.isDestroyed()) {
        if (billboardCollectionRef.current) viewer.scene.primitives.remove(billboardCollectionRef.current);
        if (labelCollectionRef.current) viewer.scene.primitives.remove(labelCollectionRef.current);
      }
      billboardCollectionRef.current = null;
      labelCollectionRef.current = null;
      idMapRef.current.clear();
    };
  }, [viewer]);

  // Render billboards + labels
  useEffect(() => {
    const bc = billboardCollectionRef.current;
    const lc = labelCollectionRef.current;
    if (!bc || !lc) return;
    bc.removeAll();
    lc.removeAll();
    idMapRef.current.clear();
    if (!visible || !refineries) return;

    if (!iconRef.current) {
      iconRef.current = createRefineryIcon(32);
    }

    for (const feature of refineries.features) {
      const [lon, lat] = feature.geometry.coordinates;
      const position = Cesium.Cartesian3.fromDegrees(lon, lat);

      const bb = bc.add({
        position,
        image: iconRef.current,
        scale: 0.8,
        eyeOffset: new Cesium.Cartesian3(0, 0, -20),
      });
      idMapRef.current.set(bb as unknown as object, feature.properties);

      lc.add({
        position,
        text: feature.properties.name,
        font: "11px monospace",
        fillColor: Cesium.Color.fromCssColorString(ICON_COLOR).withAlpha(0.9),
        outlineColor: Cesium.Color.BLACK,
        outlineWidth: 2,
        style: Cesium.LabelStyle.FILL_AND_OUTLINE,
        pixelOffset: new Cesium.Cartesian2(0, -22),
        distanceDisplayCondition: new Cesium.DistanceDisplayCondition(0, LABEL_ALTITUDE_THRESHOLD),
        scale: 0.9,
      });
    }
  }, [refineries, visible, viewer]);

  return null;
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd services/frontend && npx vitest run src/components/layers/__tests__/RefineryLayer.test.tsx`
Expected: 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/components/layers/RefineryLayer.tsx src/components/layers/__tests__/RefineryLayer.test.tsx
git commit -m "feat(frontend): add RefineryLayer with filled intel-style icon"
```

---

### Task 7: OperationsPanel — Add Layer Toggles + Icons

**Files:**
- Modify: `src/components/ui/OperationsPanel.tsx`

- [ ] **Step 1: Add entries to CORE_LAYERS array**

In `OperationsPanel.tsx`, add two entries at the end of the `CORE_LAYERS` array (after the `pipelines` entry):

```typescript
  { key: "datacenters", label: "DATACENTERS", color: "#00e5ff" },
  { key: "refineries",  label: "REFINERIES",  color: "#ff8f00" },
```

- [ ] **Step 2: Add LayerIcon SVG cases**

In the `LayerIcon` component's `switch` statement, add two cases before the `default`:

```typescript
    case "datacenters":
      return (
        <svg {...s}>
          <rect x={8} y={8} width={16} height={16} rx={2} fill={color} opacity={0.3} stroke={color} strokeWidth={1} />
          <line x1={11} y1={13} x2={21} y2={13} stroke={color} strokeWidth={1.5} opacity={0.7} />
          <line x1={11} y1={17} x2={21} y2={17} stroke={color} strokeWidth={1.5} opacity={0.7} />
          <line x1={11} y1={21} x2={21} y2={21} stroke={color} strokeWidth={1.5} opacity={0.7} />
          <circle cx={20} cy={13} r={1.2} fill={color} opacity={0.9} />
          <circle cx={20} cy={17} r={1.2} fill="#00ff88" opacity={0.9} />
          <circle cx={20} cy={21} r={1.2} fill={color} opacity={0.9} />
        </svg>
      );
    case "refineries":
      return (
        <svg {...s}>
          <rect x={10} y={14} width={5} height={14} rx={2.5} fill={color} opacity={0.3} stroke={color} strokeWidth={1} />
          <rect x={17} y={10} width={5} height={18} rx={2.5} fill={color} opacity={0.3} stroke={color} strokeWidth={1} />
          <rect x={24} y={16} width={4} height={12} rx={1} fill={color} opacity={0.2} stroke={color} strokeWidth={1} />
          <circle cx={26} cy={12} r={2} fill={color} opacity={0.15} stroke={color} strokeWidth={0.8} />
          <line x1={8} y1={28} x2={30} y2={28} stroke={color} strokeWidth={1.5} />
        </svg>
      );
```

- [ ] **Step 3: Run type-check**

Run: `cd services/frontend && npx tsc --noEmit`
Expected: May show errors in `App.tsx` where `LayerVisibility` literals are missing the new fields — that's expected, fixed in Task 8.

- [ ] **Step 4: Commit**

```bash
git add src/components/ui/OperationsPanel.tsx
git commit -m "feat(frontend): add datacenter + refinery toggles to OperationsPanel"
```

---

### Task 8: SelectionPanel — Add Datacenter + Refinery Content

**Files:**
- Modify: `src/components/ui/SelectionPanel.tsx`

- [ ] **Step 1: Extend Selected union type**

In `SelectionPanel.tsx`, import the new types and extend the `Selected` type:

Add imports at the top:
```typescript
import type { AircraftTrack, FIRMSHotspot, DatacenterProperties, RefineryProperties } from "../../types";
```

Extend the `Selected` type:
```typescript
export type Selected =
  | { type: "firms"; data: FIRMSHotspot }
  | { type: "aircraft"; data: AircraftTrack }
  | { type: "datacenter"; data: DatacenterProperties }
  | { type: "refinery"; data: RefineryProperties };
```

- [ ] **Step 2: Update header text and routing**

In the `SelectionPanel` component, update the header `<span>` to handle new types:

```typescript
<span>
  {selected.type === "firms"
    ? "THERMAL ANOMALY"
    : selected.type === "aircraft"
      ? "AIRCRAFT TRACK"
      : selected.type === "datacenter"
        ? "DATACENTER"
        : "OIL REFINERY"}
</span>
```

Update the content area to route to new components:

```typescript
<div className="p-3 text-green-300/80 leading-relaxed">
  {selected.type === "firms" ? (
    <FIRMSContent h={selected.data} />
  ) : selected.type === "aircraft" ? (
    <AircraftContent t={selected.data} viewer={viewer} />
  ) : selected.type === "datacenter" ? (
    <DatacenterContent d={selected.data} />
  ) : (
    <RefineryContent r={selected.data} />
  )}
</div>
```

- [ ] **Step 3: Add DatacenterContent component**

Add after the existing `AircraftContent` function:

```typescript
function DatacenterContent({ d }: { d: DatacenterProperties }) {
  return (
    <>
      <div className="mb-1 text-cyan-300 font-bold">{d.name}</div>
      <Row label="OPERATOR" value={d.operator} />
      <Row label="TIER" value={d.tier.toUpperCase()} />
      <Row label="CAPACITY" value={d.capacity_mw != null ? `${d.capacity_mw} MW` : "—"} />
      <Row label="COUNTRY" value={d.country} />
      <Row label="CITY" value={d.city} />
    </>
  );
}
```

- [ ] **Step 4: Add RefineryContent component**

Add after `DatacenterContent`:

```typescript
function RefineryContent({ r }: { r: RefineryProperties }) {
  const fmtCapacity = (bpd: number): string => {
    if (bpd >= 1_000_000) return `${(bpd / 1_000_000).toFixed(2)}M bbl/day`;
    return `${(bpd / 1_000).toFixed(0)}K bbl/day`;
  };

  return (
    <>
      <div className="mb-1 text-amber-300 font-bold">{r.name}</div>
      <Row label="OPERATOR" value={r.operator} />
      <Row label="CAPACITY" value={fmtCapacity(r.capacity_bpd)} />
      <Row label="COUNTRY" value={r.country} />
      <Row label="STATUS" value={r.status.toUpperCase()} />
    </>
  );
}
```

- [ ] **Step 5: Run type-check**

Run: `cd services/frontend && npx tsc --noEmit`
Expected: May still have errors in `App.tsx` — fixed in next task.

- [ ] **Step 6: Commit**

```bash
git add src/components/ui/SelectionPanel.tsx
git commit -m "feat(frontend): add datacenter + refinery content to SelectionPanel"
```

---

### Task 9: App.tsx — Wire Everything Together

**Files:**
- Modify: `src/App.tsx`

- [ ] **Step 1: Add imports**

Add these imports to `App.tsx`:

```typescript
import { DatacenterLayer } from "./components/layers/DatacenterLayer";
import { RefineryLayer } from "./components/layers/RefineryLayer";
import { useDatacenters } from "./hooks/useDatacenters";
import { useRefineries } from "./hooks/useRefineries";
```

Also import new types in the existing type import line:
```typescript
import type { LayerVisibility, ShaderType, Hotspot, ClientConfig, DatacenterProperties, RefineryProperties } from "./types";
```

- [ ] **Step 2: Update default LayerVisibility state**

In the `useState<LayerVisibility>` initial value, add the two new fields:

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
    firmsHotspots: true,
    milAircraft: true,
    datacenters: false,
    refineries: false,
  });
```

- [ ] **Step 3: Update config fallback default_layers**

In the `getConfig().catch()` fallback, add the new fields:

```typescript
  default_layers: {
    flights: true, satellites: true, earthquakes: true, vessels: false,
    cctv: false, events: false, cables: false, pipelines: false,
    firmsHotspots: true, milAircraft: true,
    datacenters: false, refineries: false,
  },
```

- [ ] **Step 4: Wire hooks**

Add after the existing `useAircraftTracks` line:

```typescript
  const { datacenters: datacenterData } = useDatacenters(layers.datacenters);
  const { refineries: refineryData } = useRefineries(layers.refineries);
```

- [ ] **Step 5: Render layer components**

Add after the `<MilAircraftLayer>` JSX, before `<EntityClickHandler>`:

```typescript
      <DatacenterLayer
        viewer={viewer}
        datacenters={datacenterData}
        visible={layers.datacenters}
        onSelect={(d: DatacenterProperties) => setSelected({ type: "datacenter", data: d })}
      />
      <RefineryLayer
        viewer={viewer}
        refineries={refineryData}
        visible={layers.refineries}
        onSelect={(r: RefineryProperties) => setSelected({ type: "refinery", data: r })}
      />
```

- [ ] **Step 6: Run type-check**

Run: `cd services/frontend && npx tsc --noEmit`
Expected: CLEAN — all `LayerVisibility` literals now have the new fields.

- [ ] **Step 7: Run all tests**

Run: `cd services/frontend && npx vitest run`
Expected: All tests pass (existing + new).

- [ ] **Step 8: Run lint**

Run: `cd services/frontend && npx eslint src/ --ext .ts,.tsx`
Expected: 0 new errors (pre-existing warnings in GraphCanvas.tsx are acceptable).

- [ ] **Step 9: Commit**

```bash
git add src/App.tsx
git commit -m "feat(frontend): wire datacenter + refinery layers into App"
```

---

### Task 10: Full Integration Verification

**Files:** None (verification only)

- [ ] **Step 1: Run full test suite**

Run: `cd services/frontend && npx vitest run`
Expected: All tests pass. Note exact count.

- [ ] **Step 2: Run type-check**

Run: `cd services/frontend && npx tsc --noEmit`
Expected: 0 errors.

- [ ] **Step 3: Run lint**

Run: `cd services/frontend && npx eslint src/ --ext .ts,.tsx`
Expected: 0 new errors.

- [ ] **Step 4: Build check**

Run: `cd services/frontend && npm run build`
Expected: Build succeeds without errors.

- [ ] **Step 5: Verify GeoJSON data integrity**

Run:
```bash
cd services/frontend
node -e "
const fs = require('fs');
const dc = JSON.parse(fs.readFileSync('public/data/datacenters.geojson','utf8'));
const rf = JSON.parse(fs.readFileSync('public/data/refineries.geojson','utf8'));
console.log('Datacenters:', dc.features.length);
console.log('Refineries:', rf.features.length);
const tiers = new Set(dc.features.map(f => f.properties.tier));
const statuses = new Set(rf.features.map(f => f.properties.status));
console.log('DC tiers:', [...tiers]);
console.log('Refinery statuses:', [...statuses]);
const badDC = dc.features.filter(f => !f.geometry.coordinates || f.geometry.coordinates.length !== 2);
const badRF = rf.features.filter(f => !f.geometry.coordinates || f.geometry.coordinates.length !== 2);
console.log('Invalid DC coords:', badDC.length);
console.log('Invalid RF coords:', badRF.length);
"
```

Expected: Feature counts in range, all tiers in `["III", "IV", "hyperscaler"]`, all statuses in `["active", "planned", "shutdown"]`, 0 invalid coordinates.

- [ ] **Step 6: Report results**

Report all test counts, type-check status, lint status, build status, and data integrity check results.
