# Infrastructure Layers Design — Datacenter + Refineries

**Date:** 2026-04-12
**Status:** Draft
**Pattern:** PipelineLayer (static GeoJSON + BillboardCollection)

## Architectural Decisions

### Click Handling: Layer-Local (not EntityClickHandler)

Each layer manages its own `ScreenSpaceEventHandler` and `idMapRef`, emitting selections via `onSelect` prop to `SelectionPanel`. This follows the FIRMS/MilAircraft pattern (not the older EntityClickHandler used by Cables/Pipelines). Rationale: layer-local handlers are self-contained, testable, and avoid coupling to a central dispatcher.

**Binding rule:** `EntityClickHandler` is for Entity API layers (legacy). All BillboardCollection-based layers use layer-local click handlers.

### Data Loading: Lazy, Enabled-Gated

Hooks only fetch when `enabled=true` (same as `usePipelines`). Since both layers default to `off`, no GeoJSON is downloaded until the user toggles the layer on. This avoids ~2 unnecessary fetches on every page load.

### No Backend Involvement

Pure frontend — static GeoJSON served from `public/data/`. Backend `/api/v1/config` already delivers `default_layers` for existing layers (flights, satellites, FIRMS, etc.); no backend change needed here since these new layers are static frontend-only data with a hardcoded default of `false`.

### All paths relative to `services/frontend/`

All `src/` and `public/` paths in this spec are relative to `services/frontend/`.

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
| `tier` | `"III"` \| `"IV"` \| `"hyperscaler"` | Tier classification |
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
| `status` | `"active"` \| `"planned"` \| `"shutdown"` | Operational status |

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
  tier: "III" | "IV" | "hyperscaler";
  capacity_mw: number | null;
  country: string;
  city: string;
}

export interface RefineryProperties {
  name: string;
  operator: string;
  capacity_bpd: number;
  country: string;
  status: "active" | "planned" | "shutdown";
}
```

### Hooks

**`useDatacenters.ts`** — identical pattern to `usePipelines.ts`:
- Accept `enabled: boolean` parameter — only fetch when `true`
- Fetch `/data/datacenters.geojson` once when first enabled
- Return `{ datacenters: FeatureCollection | null, loading, lastUpdate }`
- No polling (static data)

**`useRefineries.ts`** — same pattern:
- Accept `enabled: boolean` parameter — only fetch when `true`
- Fetch `/data/refineries.geojson` once when first enabled
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

All paths relative to `services/frontend/`.

### New files:
- `public/data/datacenters.geojson`
- `public/data/refineries.geojson`
- `src/components/layers/DatacenterLayer.tsx`
- `src/components/layers/RefineryLayer.tsx`
- `src/hooks/useDatacenters.ts`
- `src/hooks/useRefineries.ts`
- `src/components/layers/__tests__/DatacenterLayer.test.tsx`
- `src/components/layers/__tests__/RefineryLayer.test.tsx`
- `src/hooks/__tests__/useDatacenters.test.ts`
- `src/hooks/__tests__/useRefineries.test.ts`

### Modified files:
- `src/types/index.ts` — LayerVisibility + property types
- `src/components/ui/OperationsPanel.tsx` — add to CORE_LAYERS
- `src/components/ui/SelectionPanel.tsx` — handle datacenter/refinery selections
- `src/App.tsx` — wire hooks, render layers, update default visibility

## Testing

### Hook tests (`useDatacenters.test.ts`, `useRefineries.test.ts`):
- Fetch mock: returns GeoJSON, verifies state
- `enabled=false`: no fetch triggered
- `enabled` toggle: fetch on first enable, no re-fetch on subsequent toggles

### Layer tests (`DatacenterLayer.test.ts`, `RefineryLayer.test.ts`):
- Collection creation on mount
- Visibility toggle (`show` property)
- Billboard count matches feature count
- Click handler emits correct properties via `onSelect`

### Integration tests:
- OperationsPanel: new toggles render, click toggles `LayerVisibility` state
- App.tsx: layers receive correct props, default visibility is `false`
- SelectionPanel: datacenter/refinery selection renders correct detail fields

### Quality gates:
- `npm run type-check` clean
- `npm run lint` clean (0 new errors)
