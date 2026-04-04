# Globe Layers Evolution — Design Spec

> New data layers, animated globe markers, terrain, type-specific icons, and Telegram integration.

**Date:** 2026-04-05
**Scope:** Frontend (services/frontend) + Backend extensions (services/backend) + Data Ingestion enrichment (services/data-ingestion)

---

## Overview

Upgrade the ODIN Globe from static dot-markers to a cinematically animated, type-aware situational awareness display. Add terrain relief, oil/gas pipeline layer, and surface Telegram-ingested events on the globe with geocoding fallback.

**Four phases, each independently deployable:**

1. Terrain + Sidebar Icons
2. Pipeline Layer
3. Globe-Marker Animations + Type Icons
4. Telegram → Globe Integration

---

## Phase 1: Terrain + Sidebar Icons

### Cesium World Terrain

- Activate `Cesium.createWorldTerrainAsync()` as TerrainProvider in `GlobeViewer.tsx`
- Set `viewer.scene.verticalExaggeration = 1.5` for visible mountain/valley relief
- Bathymetry enabled (ocean floors visible — relevant for Hormuz, Suez, submarine cable routes)
- Google 3D Tiles remain as overlay — terrain provides elevation underneath, 3D Tiles provide buildings/texture on top
- No conflict: CesiumJS composites terrain + 3D tiles automatically

### Sidebar Icons (OperationsPanel)

Replace ASCII characters (`^*~%@!#`) with inline SVG icons. Each layer gets a unique color and shape.

| Layer | Color | Hex | Shape | SVG Style |
|-------|-------|-----|-------|-----------|
| Flights | Amber | `#c4813a` | Chevron/Arrow | Filled, glow filter |
| Satellites | Cyan | `#06b6d4` | Dot + Orbit ellipse | Filled dot, stroke orbit |
| Earthquakes | Red | `#ef4444` | Concentric rings + dot | Stroke rings, filled center |
| Vessels | Light Blue | `#4fc3f7` | Ship silhouette | Filled |
| Events | Orange | `#f97316` | Bullseye (rings + dot) | Stroke rings, filled center |
| Cables | Green | `#22c55e` | Wave form | Stroke only |
| CCTV | Bone | `#d4cdc0` | Camera silhouette | Filled |
| Pipelines | Yellow | `#eab308` | Curve + endpoints | Stroke + filled dots |

**Toggle states:**
- ON: Full color, `bg-{color}/10` background, `border-{color}/30` border
- OFF: 30% opacity, no background, transparent border

**Config contract (Finding 2 Fix):**
- `src/types/index.ts` — add `pipelines: boolean` to `LayerVisibility`
- `src/App.tsx` — add `pipelines: false` default in initial state (layer disabled until Phase 2 data exists)
- `services/backend/app/routers/config.py` — add `pipelines: false` to `ClientConfig` response defaults
- Backend config endpoint returns layer defaults — frontend reads them on init. New layers default to `false` until their data source is available, so Phase 1 deploys without breaking even if Phase 2 isn't done yet.

**Files to modify:**
- `src/components/ui/OperationsPanel.tsx` — replace `icon: string` with SVG components
- `src/types/index.ts` — add `pipelines: boolean` to `LayerVisibility`
- `src/App.tsx` — add pipelines layer state + toggle
- `services/backend/app/routers/config.py` — add pipelines default to ClientConfig

---

## Phase 2: Pipeline Layer

### Data Source

- Static GeoJSON file: `public/data/pipelines.geojson`
- Source: Global Energy Monitor Pipeline Tracker (Open Data, CC BY 4.0)
- Fallback source: OpenStreetMap Overpass export for `pipeline=*` tags
- No backend endpoint needed — Vite serves from `public/` directly

### GeoJSON Schema

Each Feature in the GeoJSON:

```json
{
  "type": "Feature",
  "properties": {
    "name": "Nord Stream 2",
    "tier": "major",
    "type": "gas",
    "status": "active",
    "operator": "Nord Stream 2 AG",
    "capacity_bcm": 55,
    "length_km": 1230,
    "countries": ["Russia", "Germany"]
  },
  "geometry": {
    "type": "LineString",
    "coordinates": [[...]]
  }
}
```

**Required properties:**
- `tier`: `"major"` | `"regional"` | `"local"` — controls LOD visibility
- `type`: `"oil"` | `"gas"` | `"lng"` | `"mixed"` — controls color
- `status`: `"active"` | `"planned"` | `"under_construction"` — controls line style

### LOD Strategy

| Camera Altitude | Visible Tiers | Approx Count |
|-----------------|---------------|--------------|
| > 5M meters | `major` only | ~80-100 |
| 1M–5M meters | `major` + `regional` | ~300-500 |
| < 1M meters | All tiers | Full dataset |

Implementation: `camera.moveEnd` listener checks `camera.positionCartographic.height`, filters features by tier.

### Rendering

- `PolylineCollection` (same pattern as CableLayer)
- Color by type:
  - Oil: `#eab308` (yellow/gold)
  - Gas: `#f97316` (orange)
  - LNG: `#a855f7` (purple)
  - Mixed: `#d4cdc0` (bone)
- Line width: 2px active, 1.5px planned/under construction
- Dashed line for `status: "planned"` or `"under_construction"`
- Billboard dots at midpoints for click detection (same pattern as CableLayer)

### Click Handler

EntityClickHandler extended with `_pipelineData`:
- Name, operator, type, status
- Capacity, length, countries

**Files to create:**
- `src/components/layers/PipelineLayer.tsx`
- `src/hooks/usePipelines.ts`
- `public/data/pipelines.geojson`

**Files to modify:**
- `src/components/ui/OperationsPanel.tsx` — add Pipelines toggle
- `src/components/globe/EntityClickHandler.tsx` — add pipeline click handling
- `src/types/index.ts` — add Pipeline type
- `src/App.tsx` — add PipelineLayer + hook

---

## Phase 3: Globe-Marker Animations + Type Icons

### Performance Guard

All animations operate under a strict performance budget:

- **FPS Monitor:** Track frame time in `requestAnimationFrame` loop. If FPS < 30 for > 2 seconds, trigger degradation.
- **Degradation levels:**
  1. Shorten trails (30s → 10s → off)
  2. Stop pulse animations (static rings only)
  3. Hide orbit arcs
  4. Fall back to static dots only
- **LOD gate (Finding 5 Fix — per-layer thresholds):**
  - Flight trails, ship vectors, event pulses, earthquake pulses: < 10M meters
  - Satellite orbit arcs: < 20M meters (orbits are large-scale, visible from further out)
  - Above threshold = static dots/markers only
- **Hard limit:** Max 10,000 animated primitives simultaneously.
- **Animation technique:** Canvas-based `requestAnimationFrame` loops for pulses and trail updates (not `PostProcessStage` — that's a full-screen filter, wrong tool for per-marker animation). GLSL custom shaders only considered for future heatmap overlays.

### Aircraft Type Icons

Replace single triangle icon with type-specific silhouettes rendered on Canvas:

| Type | Silhouette | Color | Classification Source |
|------|-----------|-------|----------------------|
| Fighter | Delta wings, narrow body | Red `#ef4444` | ADS-B category A1/B1 + military callsign prefix |
| Bomber/Heavy Mil | Swept wings, wide | Red `#ef4444` | ADS-B category A5/B5 + military callsign |
| Transport Mil | Wide body, straight wings | Amber `#c4813a` | Military callsign (RCH, EVAC, etc.) |
| Helicopter | Rotor disc + tail boom | Red `#ef4444` | ADS-B category C1-C3 (VTOL) |
| UAV/Drone | Narrow profile, small | Purple `#a855f7` | Callsign pattern + low altitude + slow speed heuristic |
| Civilian | Standard airliner shape | Bone `#d4cdc0` | Default fallback |

**Military callsign prefixes** (partial list): RCH, EVAC, DUKE, VALOR, REACH, FORGE, COBRA, HAWK, VIPER, RAPTOR, REAPER, SIGINT, FORTE.

**Canvas icon cache:** Icons cached by `{type}_{heading_bucket}` key. Heading bucketed to 5° steps = max 72 × 6 types = 432 cached icons.

### Ship Type Icons

Replace single diamond icon with type-specific silhouettes:

| Type | Silhouette | Color | Classification Source |
|------|-----------|-------|----------------------|
| Warship | Hull + superstructure + mast | Red `#ef4444` | AIS ship_type 35 |
| Carrier | Flat deck + island | Red `#ef4444` | AIS ship_type 35 + name pattern |
| Submarine | Cigar hull + conning tower | Red `#ef4444` | AIS ship_type 35 + name pattern |
| Tanker | Hull + round tanks | Yellow `#eab308` | AIS ship_type 80-89 |
| Cargo | Hull + container stacks | Light Blue `#4fc3f7` | AIS ship_type 70-79 |
| Civilian | Small hull | Bone `#d4cdc0` | Default fallback |

**Classification:** AIS `ship_type` field (IMO standard numeric codes). Already available in vessel data. Sub-classification for carrier/submarine uses MMSI country prefix + vessel name pattern matching.

### Flight Trails

- Ring buffer of last 10 interpolated positions per aircraft
- `PolylineCollection` with color gradient: layer color at head → transparent at tail
- Only rendered for visible flights (frustum culling)
- When > 500 visible flights: trails only for military aircraft
- Trail length: ~30 seconds of movement history

### Ship Course Vectors

- Line from current position in heading direction
- Length proportional to speed: `position + heading × speed × 5min`
- Same color as ship type icon, 50% opacity
- Only rendered when camera < 5M meters

### Satellite Enhancements

**Orbit Arcs:**
- SGP4 propagates 50 points into the future (half orbit)
- Thin polyline in category color (military=red, GPS=yellow, weather=cyan, etc.)
- Visible only when satellite layer active AND camera < 20M meters
- On hover: full orbit ellipse rendered

**Operator/Country (Finding 3 Fix — full contract):**
- Extract from satellite name prefix using a static mapping table in the backend
- Mapping: `USA`/`NROL` → US, `COSMOS` → RU, `YAOGAN`/`CZ` → CN, `GALILEO` → EU, etc.
- New fields added to the `Satellite` Pydantic response model in `services/backend/app/routers/satellites.py`:
  - `operator_country: str | None` (ISO 3166-1 alpha-2, e.g. `"US"`, `"RU"`, `"CN"`)
  - `satellite_type: str` (`"recon"` | `"comms"` | `"gps"` | `"weather"` | `"station"` | `"unknown"`)
- Frontend `Satellite` type in `src/types/index.ts` extended with matching fields
- Color override by country: US=`#3b82f6`, RU=`#ef4444`, CN=`#eab308`, EU=`#d4cdc0`, others=`#6b7280`
- Applied as secondary tint on orbit arc, not on the satellite dot itself

**Footprint on Hover:**
- Semi-transparent circle on Earth surface showing satellite field of view
- Radius calculated from altitude + minimum elevation angle (typically 5°)
- `EllipseGeometry` with category color at 15% opacity
- Only rendered on hover, destroyed on mouse leave

**Reconnaissance Highlight:**
- Known recon satellite series (USA/NROL, COSMOS 2500+, Yaogan) get eye-symbol icon instead of standard dot
- Slightly larger (10px vs 3px)
- Pulse animation when passing over active conflict zones

**Click Popup Extended:**
- Name, NORAD ID, operator/country, type (Recon/Comms/GPS/Weather/Station)
- Altitude, inclination, period
- Current footprint radius in km

### Earthquake Pulses

- Two concentric rings per earthquake expanding + fading
- Outer ring: `radius = baseRadius + sin(time × speed) × amplitude`
- Inner dot remains static
- Magnitude ≥ 7: permanent pulse
- Magnitude ≥ 5: 30-second pulse after event time, then static
- Magnitude < 5: single ripple then static

### Event Pulses

- Critical severity: fast pulse (2 Hz ring expansion)
- High severity: slow pulse (0.5 Hz)
- Medium/Low: static marker, no animation

**Files to modify:**
- `src/components/layers/FlightLayer.tsx` — type icons, trails
- `src/components/layers/ShipLayer.tsx` — type icons, course vectors
- `src/components/layers/SatelliteLayer.tsx` — orbit arcs, footprint, recon highlight, country
- `src/components/layers/EarthquakeLayer.tsx` — pulse animation
- `src/components/layers/EventLayer.tsx` — severity-based pulse
- `src/components/globe/EntityClickHandler.tsx` — extended satellite popup
- `src/App.tsx` — FPS monitor, performance guard state

**Backend changes:**
- `services/backend/app/routers/satellites.py` — add `operator_country` + `satellite_type` fields to Satellite Pydantic model + response
- `services/backend/app/routers/satellites.py` — add static name-prefix → country mapping dict
- `src/types/index.ts` — extend `Satellite` type with `operator_country` + `satellite_type`

---

## Phase 4: Telegram → Globe Integration

### Unified Events Endpoint (Finding 1 Fix)

**No separate `/api/v1/events/telegram` endpoint.** Instead, extend the existing `/api/v1/graph/events/geo` endpoint with a `source` query parameter:

```
GET /api/v1/graph/events/geo?source=all        (default — Neo4j + Qdrant/Telegram)
GET /api/v1/graph/events/geo?source=telegram   (Qdrant only, source=telegram)
GET /api/v1/graph/events/geo?source=rss        (Neo4j only, existing behavior)
```

- Backend merges Neo4j events + Qdrant Telegram events into a single response
- Dedup by `url` field — if same URL exists in both stores, Neo4j version wins (richer extraction)
- Each event carries a `source` field in the response: `"telegram"` | `"rss"` | `"gdelt"`
- Frontend `useEvents` hook passes `source` param from OperationsPanel filter
- **Single data flow:** useEvents → API → EventLayer. No separate hook, no client-side merge.

### Geocoding Fallback (Data Ingestion) (Finding 4 Fix)

Added to the telegram collector pipeline after vLLM extraction:

- When `entities` contains items with type `location` but no coordinates in the extracted data
- Lookup against static Gazetteer file (~50,000 places, GeoNames export)
- File: `services/data-ingestion/feeds/geonames_gazetteer.json`

**Matching strategy (strict to prevent false positives):**
- Exact name match only — no fuzzy matching
- Gazetteer entries keyed by `(name, country_code)` tuples to disambiguate (e.g. "Springfield, US" vs "Springfield, UK")
- Country context extracted from surrounding entities in the same message (if LLM extracted a country entity, use it to scope the lookup)
- Minimum population filter: only places with population > 10,000 (removes hamlets/villages with duplicate names)
- Confidence field: `geo_confidence: "exact"` | `"contextual"` | `"none"` stored in Qdrant payload
  - `"exact"`: LLM extracted coordinates directly
  - `"contextual"`: Gazetteer matched with country context
  - `"none"`: no geo data available

- Result stored as `lat`/`lon` + `geo_confidence` in the Qdrant payload during upsert
- Fallback chain: LLM-extracted coordinates (`exact`) → Gazetteer + country context (`contextual`) → no geo (`none`, feed only)

### EventLayer Extension

- Add `source` field to event data model (`"telegram"` | `"rss"` | `"gdelt"`)
- Telegram events get a small paperplane badge icon next to the event marker
- Color remains by codebook_type (military=red, political=orange, etc.) — not by source
- Badge rendered as secondary billboard offset slightly from main marker

### OperationsPanel Source Filter

- Below the Events toggle button: collapsible sub-filter
- Options: `ALL` | `TELEGRAM` | `RSS/GDELT`
- Default: `ALL`
- Filter triggers re-fetch via `useEvents(source)` — server-side filtering, not client-side

### Source Bias Indicator

- Telegram events from channels with `source_bias != "neutral"` show bias badge in click popup
- Display format: `⚠ pro_russian`, `⚠ pro_ukrainian`, etc.
- No visual difference on the globe markers themselves — bias is context, not filter
- Bias info already present in Qdrant payload from telegram collector

**Files to create:**
- `services/data-ingestion/feeds/geonames_gazetteer.json` — geocoding data
- `services/data-ingestion/feeds/geocoder.py` — gazetteer lookup module

**Files to modify:**
- `services/backend/app/routers/graph.py` — extend events/geo endpoint with source param + Qdrant merge + dedup
- `services/data-ingestion/feeds/telegram_collector.py` — geocoding fallback in `_process_single` / `_process_album`
- `src/components/layers/EventLayer.tsx` — source badge, source field
- `src/components/ui/OperationsPanel.tsx` — source sub-filter
- `src/components/globe/EntityClickHandler.tsx` — bias badge in popup
- `src/hooks/useEvents.ts` — add source parameter
- `src/types/index.ts` — extend IntelEvent type with source, source_bias, geo_confidence fields

---

## Color System Summary

| Layer | Primary Color | Hex | Military Variant |
|-------|--------------|-----|------------------|
| Flights | Amber | `#c4813a` | Red `#ef4444` |
| Satellites | Cyan | `#06b6d4` | Red `#ef4444` (recon) |
| Earthquakes | Red | `#ef4444` | N/A |
| Vessels | Light Blue | `#4fc3f7` | Red `#ef4444` |
| Events | Orange | `#f97316` | N/A (severity colors) |
| Cables | Green | `#22c55e` | N/A |
| CCTV | Bone | `#d4cdc0` | N/A |
| Pipelines | Yellow (oil) | `#eab308` | N/A |
| Pipelines | Orange (gas) | `#f97316` | N/A |
| Pipelines | Purple (LNG) | `#a855f7` | N/A |
| Telegram Badge | — | Same as event | — |

---

## Performance Constraints

| Metric | Target | Degradation Trigger |
|--------|--------|---------------------|
| FPS | ≥ 30 | < 30 for > 2 seconds |
| Max animated primitives | 10,000 | Hard limit, excess culled by distance |
| Trail buffer per entity | 10 positions | Reduced to 5 under pressure |
| Animation LOD gate | < 10M meters altitude | Above = static dots only |
| Pipeline LOD | 3 tiers by altitude | Camera moveEnd listener |
| Satellite orbit arcs | < 20M meters altitude | Above = dots only |
| Icon cache size | ~500 entries | LRU eviction |

---

## Acceptance Criteria / Test Matrix (Finding 6 Fix)

### Phase 1: Terrain + Icons
- [ ] Terrain visible: mountains have relief, ocean floors visible at zoom (visual check)
- [ ] All 8 sidebar icons render as SVG with correct colors
- [ ] Toggle ON/OFF changes opacity correctly
- [ ] `pipelines: false` default in config endpoint response
- [ ] Existing layer tests still pass (no regressions)

### Phase 2: Pipeline Layer
- [ ] GeoJSON loads without errors
- [ ] LOD: only major pipelines visible at global zoom, all tiers at local zoom
- [ ] Color coding: oil=yellow, gas=orange, LNG=purple
- [ ] Dashed lines for planned/under_construction
- [ ] Click popup shows name, operator, capacity, countries
- [ ] FPS ≥ 30 with all pipelines visible at local zoom

### Phase 3: Animations + Type Icons
- [ ] Aircraft icons differ by type (fighter vs civilian visually distinct)
- [ ] Ship icons differ by type (warship vs cargo visually distinct)
- [ ] Flight trails render behind moving aircraft, fade to transparent
- [ ] Ship course vectors point in heading direction
- [ ] Satellite orbit arcs visible at < 20M meters, hidden above
- [ ] Satellite footprint appears on hover, disappears on leave
- [ ] Satellite click popup shows operator_country, type, footprint radius
- [ ] Earthquake pulses: ≥7 permanent, ≥5 timed, <5 single ripple
- [ ] FPS monitor: degradation triggers when FPS < 30 for > 2s
- [ ] At global zoom (>10M): only static dots, no trails/pulses
- [ ] Backend: `operator_country` and `satellite_type` fields in satellite API response

### Phase 4: Telegram Integration
- [ ] `/api/v1/graph/events/geo?source=telegram` returns only Telegram events
- [ ] `/api/v1/graph/events/geo?source=all` returns merged + deduped events
- [ ] Dedup: same URL in Neo4j + Qdrant → Neo4j version wins
- [ ] Telegram events show paperplane badge on globe
- [ ] Source filter in OperationsPanel triggers re-fetch (not client-side filter)
- [ ] Bias badge shows in click popup for non-neutral channels
- [ ] Geocoding: exact match places resolved correctly
- [ ] Geocoding: ambiguous names without country context → not geocoded (no false positives)
- [ ] `geo_confidence` field present in Qdrant payload

---

## Out of Scope

- Landing Page / Routing (separate spec)
- Briefing Room (separate spec)
- Timeline/4D Scrubber (separate spec)
- Globe Fullscreen Takeover layout changes (separate spec)
- Vision Enrichment results on globe (depends on vision service running)
