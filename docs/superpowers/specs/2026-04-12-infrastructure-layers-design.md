# Infrastructure Layers Design — Datacenter + Refineries

**Date:** 2026-04-12
**Status:** Draft
**Pattern:** PipelineLayer (static GeoJSON + BillboardCollection)

## Goal

Two new static infrastructure layers on the CesiumJS globe: **Datacenter** (~200 Tier III+ / Hyperscaler) and **Oil Refineries** (~150, >100k bbl/day). Both follow the existing PipelineLayer pattern — static GeoJSON loaded once, rendered as BillboardCollections with click-to-select.

## Data

### Datacenter GeoJSON (`public/data/datacenters.geojson`)

~200 entries. FeatureCollection with Point geometries.

**Properties per feature:**

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Facility name (e.g. "AWS US-East-1 (Ashburn)") |
| `operator` | string | Company (AWS, Google, Meta, Equinix, Microsoft, Oracle, etc.) |
| `tier` | string | "III", "IV", or "hyperscaler" |
| `capacity_mw` | number \| null | Power capacity in megawatts (if known) |
| `country` | string | ISO 3166-1 alpha-2 |
| `city` | string | Nearest city |

**Sources:**
- Wikipedia "List of largest data centers"
- OpenStreetMap / Overture Maps POI (`telecom=data_center`)
- Manual curation from operator announcements

### Refinery GeoJSON (`public/data/refineries.geojson`)

~150 entries. FeatureCollection with Point geometries.

**Properties per feature:**

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Facility name (e.g. "Jamnagar Refinery") |
| `operator` | string | Company (Saudi Aramco, Reliance, ExxonMobil, etc.) |
| `capacity_bpd` | number | Capacity in barrels per day |
| `country` | string | ISO 3166-1 alpha-2 |
| `status` | string | "active", "planned", or "shutdown" |

**Sources:**
- Global Energy Monitor — Global Oil Infrastructure Tracker
- Wikipedia "List of oil refineries"
- EIA (US refineries)
- Filter: capacity > 100,000 bbl/day

## Frontend Architecture

### Types (`types/index.ts`)

```typescript
// Add to LayerVisibility
export interface LayerVisibility {
  // ... existing fields ...
  datacenters: boolean;
  refineries: boolean;
}

// GeoJSON types (reuse existing GeoJSON pattern or define inline)
export interface DatacenterProperties {
  name: string;
  operator: string;
  tier: string;
  capacity_mw: number | null;
  country: string;
  city: string;
}

export interface RefineryProperties {
  name: string;
  operator: string;
  capacity_bpd: number;
  country: string;
  status: string;
}
```

### Hooks

**`useDatacenters.ts`** — identical pattern to `usePipelines.ts`:
- Fetch `/data/datacenters.geojson` once on mount
- Return `{ datacenters: FeatureCollection | null, loading, lastUpdate }`
- No polling (static data)

**`useRefineries.ts`** — same pattern:
- Fetch `/data/refineries.geojson` once on mount
- Return `{ refineries: FeatureCollection | null, loading, lastUpdate }`
- No polling

### Layer Components

**`DatacenterLayer.tsx`:**
- Props: `viewer`, `datacenters` (FeatureCollection), `visible`, `onSelect`
- Cesium primitives: `BillboardCollection` + `LabelCollection`
- Icon: Canvas-rendered 32x32 — Filled server-rack silhouette, cyan (#00e5ff), semi-transparent fill with status LEDs and network symbol (Style B from brainstorm)
- Labels: Show facility name when camera altitude < 5,000,000 meters
- Click: Store feature properties in idMap, emit via `onSelect` for SelectionPanel
- Visibility: Toggle via `show` property on collections

**`RefineryLayer.tsx`:**
- Props: `viewer`, `refineries` (FeatureCollection), `visible`, `onSelect`
- Cesium primitives: `BillboardCollection` + `LabelCollection`
- Icon: Canvas-rendered 32x32 — Filled distillation tower silhouette, amber (#ff8f00), semi-transparent fill with emission circles (Style B from brainstorm)
- Labels: Show facility name when camera altitude < 5,000,000 meters
- Click: Store feature properties in idMap, emit via `onSelect` for SelectionPanel
- Visibility: Toggle via `show` property on collections

### OperationsPanel

Add to `CORE_LAYERS` array:
```typescript
{ key: "datacenters", label: "DATACENTERS", color: "#00e5ff" },
{ key: "refineries",  label: "REFINERIES",  color: "#ff8f00" },
```

No count badges (static data, no polling).

### SelectionPanel

Extend existing SelectionPanel to handle new selection types:

**Datacenter selection:**
- Name, Operator, Tier, Capacity (MW), Country, City

**Refinery selection:**
- Name, Operator, Capacity (bbl/day), Country, Status

### App.tsx Integration

- Wire `useDatacenters()` + `useRefineries()` hooks
- Render `<DatacenterLayer>` + `<RefineryLayer>` with viewer/visibility/onSelect props
- Default visibility: `datacenters: false`, `refineries: false` (opt-in, unlike FIRMS/Aircraft which default on)

## Default Visibility

Both layers default to **off**. Rationale: static reference data, not real-time intelligence. User enables when doing infrastructure analysis.

## Files Changed

### New files:
- `public/data/datacenters.geojson`
- `public/data/refineries.geojson`
- `src/components/layers/DatacenterLayer.tsx`
- `src/components/layers/RefineryLayer.tsx`
- `src/hooks/useDatacenters.ts`
- `src/hooks/useRefineries.ts`

### Modified files:
- `src/types/index.ts` — LayerVisibility + property types
- `src/components/ui/OperationsPanel.tsx` — add to CORE_LAYERS
- `src/components/ui/SelectionPanel.tsx` — handle datacenter/refinery selections
- `src/App.tsx` — wire hooks, render layers, update default visibility

## Testing

- Unit tests for `useDatacenters` + `useRefineries` hooks (fetch mock)
- Unit tests for `DatacenterLayer` + `RefineryLayer` (Cesium collection creation, visibility toggle)
- Type-check clean
- ESLint clean
