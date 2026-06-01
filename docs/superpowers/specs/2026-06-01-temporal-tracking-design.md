# Temporal Tracking — Design Spec

- **Date:** 2026-06-01
- **Status:** Approved for implementation planning. Slice-0 **code** is gated behind
  the reliability-first refactor landing (see §9).
- **Related:** `docs/superpowers/plans/2026-06-01-reliability-first-refactor.md`,
  `docs/superpowers/specs/2026-05-03-fusion-core-design.md`,
  `docs/superpowers/specs/2026-04-11-ingestion-globe-layers-design.md`
- **Hardening:** six static code reviews; every file:line reference below was
  verified against the working tree.

---

## 1. Context & Motivation

Tracking events and movements over time is a recurring, previously-deferred idea.
Today the whole application implicitly renders "now":

- **Live feeds** (flights, vessels, satellites, earthquakes, hotspots, cables) are
  Redis snapshots with TTL — overwritten each cycle, **no history**.
- The **graph Event model** carries a single `timestamp`, which the RSS pipeline
  even **drops on write** (`services/data-ingestion/pipeline.py:141,380-396`).
- Cesium **Clock & Timeline are deliberately disabled**
  (`services/frontend/src/components/globe/GlobeViewer.tsx:38-39`).

The request decomposes into **two distinct subsystems** with different sources,
storage, and UI. They must not drift apart, so this spec first fixes a **unifying
concept**, then makes the first building block (Slice 0) executable.

- **A) Movement replay (kinematics)** — physical objects (aircraft, ships,
  satellites) moving through space; high-frequency; from live feeds.
- **B) Event evolution (situation)** — fires, conflicts evolving over days;
  low-frequency; from OSINT extraction in the graph.

The one piece of genuinely seekable history that **already exists** is military
aircraft tracks (`MilitaryAircraft-[:SPOTTED_AT]->`), served by
`services/backend/app/routers/aircraft.py`. Slice 0 uses it as an honest,
zero-new-storage replay proof.

---

## 2. Scope & Non-Goals

**This spec covers:** the unifying temporal architecture and **Slice 0** in
implementation detail. Slices 1 and 2 are scoped at the level needed to keep the
seam stable; each gets its own spec.

**Build order (dependency-driven — events already exist in the graph, movements do
not):**

| Slice | Theme | New storage? |
|---|---|---|
| **0** | Shared time foundation + real mil-track replay | none |
| **1** | Event evolution (B): dedup, identity, geo backfill, agent tool | none |
| **2** | Movement archive (A): TimescaleDB+PostGIS, civil flight/ship/sat replay | TimescaleDB |

**Non-goals (Slice 0):** civil flight/ship/satellite replay; event dedup/threading;
event geo backfill; the intelligence-agent temporal tool; the timeseries database.

---

## 3. The Unifying Concept

**Core idea:** promote time from an implicit "now" to an **app-wide dimension** —
one clock the whole app reads from. Once it exists, movement replay is just "the
clock drives position interpolation," and event evolution is just "the clock drives
which events are visible."

**Four shared primitives:**

1. **Global clock (`TimeContext`)** wrapping `Cesium.Clock`: cursor `t`, mode
   (`live|replay`), playback (play/pause/speed), window `[t_start, t_end]`.
2. **Two-tier scrubber** — the only shared UI. Coarse tier (days/weeks) → events;
   clicking an event opens the fine tier (min/hours) scoped to its location+window.
3. **Windowed-data contract** — every domain answers *"give me state in
   `[t_start, t_end]`"* and returns timestamped samples, storage-agnostic (§5).
4. **Layers render as a function of `t`.**

**The two tiers _are_ the two subsystems:** coarse = events (graph, has data),
fine = movements (Slice 0: existing mil-tracks; Slice 2: timeseries DB). The fine
tier nesting inside the coarse selection is what keeps A and B from diverging.

**Chosen design decisions (user):** two-tier scrubber · persistent long-term
movement archival (Slice 2) · Slice 0 includes a real mil-track replay · Slice 0
sequenced **after** the reliability refactor.

---

## 4. Temporal Vocabulary

Aligned with the existing Fusion-Core design (`fusion-core-design.md:158` already
defines `observed_at` as *"when the described thing happened or was measured"*) — we
do **not** redefine it.

| Field | Meaning | Nullability |
|---|---|---|
| `occurred_at` | Attested event time | nullable |
| `observed_at` | Source/sensor observation (Fusion semantics) | nullable |
| `published_at` | Publication time | nullable |
| `ingested_at` | Platform ingest — the honest always-present fallback | **always set** |
| `time_basis` | `occurred \| observed \| published \| ingested \| indexed` | always set |

**Canonical timeline anchor:** at write time the pipeline stamps a **denormalized,
indexed `timeline_at`** plus `time_basis`, by precedence
`occurred_at → observed_at → published_at → ingested_at`. Read queries filter on the
single indexed `timeline_at` — **never** a runtime `coalesce(...)` over four fields
(it defeats index usage).

**`ingested_at` is the always-present fallback, NOT `observed_at`** — reusing
`observed_at` for an ingest-time value would collide with Fusion-Core semantics and
fabricate an observation that never happened.

---

## 5. The Windowed-Data Contract

The single seam both subsystems implement. Modeled on the existing
`GET /graph/events/geo` (`services/backend/app/routers/graph.py:163-210`).

```
GET /api/timeline/window
  ?t_start=<ISO8601 UTC>      required
  &t_end=<ISO8601 UTC>        required
  &domain=events|movements    default events
  &tier=coarse|fine           default coarse
  &movement_kind=mil_aircraft|civil_aircraft|ship|satellite   REQUIRED when domain=movements
  &bbox=west,south,east,north  optional; anti-meridian: west>east wraps
                               (convention from ShipLayer.tsx:82)
  &limit=<int>                default 200
```

**Status codes (deterministic):**

- `422` — `t_end < t_start`; malformed ISO; malformed bbox; `limit ∉ [1,500]`;
  unknown `domain`/`tier`/`movement_kind`; **missing `movement_kind` when
  `domain=movements`**; unsupported combo (`domain=events & tier=fine`).
- `501` — `domain=movements` with a **known but not-yet-implemented**
  `movement_kind` (`civil_aircraft|ship|satellite` in Slice 0). `mil_aircraft` **is
  supported**.
- `503` — Neo4j unreachable (mirrors `aircraft.py:81`).

**Request matrix (explicit):**

| `domain` | `tier` | `movement_kind` | Result |
|---|---|---|---|
| events | coarse | absent | `200` |
| events | fine | — | `422` |
| events | (any) | present | `422` |
| movements | coarse | — | `422` |
| movements | fine | absent | `422` |
| movements | fine | `mil_aircraft` | `200` |
| movements | fine | `civil_aircraft` \| `ship` \| `satellite` | `501` |
| movements | fine | unknown value | `422` |

**`WindowSample` is a discriminated union** (no implicit `GeoEvent` reuse):

- `kind:"event"` → `{ id, title?, codebook_type?, severity?, time, time_basis,
  lat?, lon?, location_name?, country? }`, where `time` is **ISO-8601-UTC**.
  **GDELT reality:** GDELT event nodes carry `event_id` (not `id`) and **no
  `title`/`severity`** (`gdelt_raw/writers/neo4j_writer.py:21-46`). Therefore
  `title`/`severity` are nullable and `id` uses a fallback
  `coalesce(ev.id, ev.event_id, toString(elementId(ev)))` — note `elementId` is
  stable **only for the node's lifetime**; a canonical event identity is a Slice-1 concern.
- `kind:"track"` → `{ id, icao24?, callsign?, type_code?, military_branch?,
  registration?, points:[{ ts_ms, lat, lon, altitude_m?, speed_ms?, heading? }] }`
  (for `movement_kind=mil_aircraft`, `id` = `icao24`). Mil-track sampling is
  15-minute resolution (`ingestion-globe-layers-design.md:243`).

**Response envelope:**
`{ domain, tier, t_start, t_end, bbox|null, samples[], total_count, truncated }`
where `total_count` = matches in window before `limit` (for `domain=movements` it
counts **tracks, not points**) and `truncated = total_count > len(samples)`.

**Units — wire vs. query format are separated:**

- **Wire:** external `t_start`/`t_end` are ISO-8601-UTC; all track points are
  **epoch milliseconds (`ts_ms`)** in the response.
- **Query:** the router converts the window to epoch **seconds** for the
  `SPOTTED_AT` query (the stored `SPOTTED_AT.timestamp` is epoch seconds —
  `military_aircraft_collector.py:168`) and multiplies points by 1000 on the way
  out. Skipping this makes the `getTimeMs()` (ms) comparison draw the full track
  immediately.

**Movement bbox semantics:** a track is **selected** if at least one of its points
within the time window lies inside the bbox; the response then returns **all** of
that track's in-window points (not only the in-bbox points). Filtering individual
points would clip tracks and cause false interpolation jumps at the bbox edge.

---

## 6. Data Reality & Event Projection

Verified constraints that shape Slice 0:

- **RSS-pipeline events carry neither time nor coordinates.** The extraction schema
  gives locations only `name`+`country`, **no lat/lon**
  (`pipeline.py:162-173`), and the write loop does not link events to locations
  (`pipeline.py:376-397`).
- **GDELT events** carry `date_added` only; `published_at` lives on the
  `GDELTDocument`, **not** on the event (`gdelt_raw/schemas.py:15-47`). So
  `GDELTEvent.timeline_at = date_added`, `time_basis = "indexed"`.
- **Legacy events** have neither time nor coordinates → **not migrated in Slice 0**
  (backfill is a Slice-1 item; documented, not silently excluded).

**Event projection supported by Slice 0:** events whose `timeline_at` is set — i.e.
GDELT events (via the migration in §8) plus newly-ingested events after the pipeline
fix. The coarse tier is primarily a **time** axis.

**bbox coverage is intentionally partial in Slice 0:** because most events lack
coordinates, `bbox` constrains only events that have linked coordinates; without
`bbox` the query is global. Full event geo + legacy backfill are Slice-1 goals. The
fine tier (mil-tracks) has real lat/lon, so `bbox` is meaningful there.

---

## 7. Architecture

### 7.1 Clock seam (no live-mode regression)

`GlobeViewer.tsx:38-39` keeps `timeline:false, animation:false` (we render our own
scrubber). `Cesium.Clock` is the engine; `TimeContext` is the React facade.

- **Live:** `clockStep=SYSTEM_CLOCK`, `clockRange=UNBOUNDED`, `shouldAnimate=true` →
  reproduces today's behavior exactly.
- **Replay:** `clockStep=SYSTEM_CLOCK_MULTIPLIER` (speed via `multiplier`),
  `clockRange=CLAMPED` to `window`.

### 7.2 Hot-path vs. UI-state separation (critical)

A ref-getter alone does **not** prevent re-renders if the provider calls
`setState(t)` on every `onTick`. Therefore:

- `getTimeMs()` reads **only** from a stable `useRef` — each layer's imperative
  update loop calls it instead of `Date.now()` (`FlightLayer`'s `setInterval` at
  `:90,185` is the canonical pattern; the Slice-0 mil layer uses `clock.onTick`).
  Only the mil layer is converted in Slice 0.
- The scrubber's **display** React state updates **throttled (~4 Hz)**, not per
  frame.
- A rarely-updated **`discontinuityEpoch`** is incremented on **every explicit seek
  (including forward)**, every rewind, and every mode change → layers reset their
  per-layer render caches (e.g. `FlightLayer`'s `trailBuffersRef`/`sampleTimeMs` at
  `FlightLayer.tsx:41`; the Slice-0 mil layer resets its **own** track caches — it
  does not own those refs). This is the single most important Slice-0 invariant to
  test; it is where "no visible live-mode regression" silently breaks.

### 7.3 Layers as a function of `t` — mil-track replay edge behavior

`MilAircraftLayer` is already a controlled component (`tracks` prop, `:58,:63`,
`trackToPolylinePositions` `:48,:120`) but has **no imperative tick loop** today
(`:106` only rebuilds on prop change). Slice 0 adds a **`clock.onTick`**
subscription **with cleanup** (not an ad-hoc timer), drawing each track **up to
`getTimeMs()`** plus an interpolated marker. On `discontinuityEpoch` it resets the
**mil layer's own render caches** (`trailBuffersRef`/`sampleTimeMs` belong to
`FlightLayer.tsx:41`, not this layer).

**Replay edge behavior (spec-fixed):**

- Cursor **before** the first point → no marker.
- Cursor **between** points → linear interpolation (a visual estimate only).
- Cursor **after** the last point → marker at the last point, **no dead reckoning**.
- Event **without geo** → fine tier without bbox as a deliberate global fallback.

### 7.4 No dead code in the intelligence service

The read Cypher lives in the **backend** router `timeline.py` (parameter-bound via
`read_query`, exactly as `aircraft.py` and `graph.py` already do — read path, no
LLM-generated Cypher, CLAUDE.md-compliant). **No** new template is added to
`services/intelligence/agents/tools/graph_templates.py` — that would break the
`len(TEMPLATES) == 8` test (`test_graph_templates.py:14`) and be dead code without
intent routing. The `events_in_window` agent tool + intent routing ships in Slice 1
(template count 8→9 with its test update).

### 7.5 Canonical mil-track render model (live↔replay adapter)

Live and replay deliver **different shapes** for the same aircraft, and both feed
`MilAircraftLayer` (`tracks: AircraftTrack[]`, `onSelect`, `:56-60`) and the
inspector:

- **Live:** `AircraftTrack` with `icao24` and `points[].timestamp` in **epoch
  seconds** (`types/index.ts:80-87`; `useAircraftTracks`).
- **Replay:** the windowed `kind:"track"` with `id` and `points[].ts_ms` in **epoch
  milliseconds** (§5).

Slice 0 introduces a **single canonical adapter** that normalizes both into one
render model before the layer/inspector see it:
`{ icao24, callsign?, type_code?, military_branch?, registration?,
points:[{ lat, lon, altitude_m?, speed_ms?, heading?, ts_ms }] }`. It maps live
`timestamp` (s) → `ts_ms` (×1000) and replay `id` → `icao24`, so downstream code is
shape- and unit-agnostic. `MilAircraftLayer.tracks`/`onSelect` are retyped to this
render model (not raw `AircraftTrack`).

---

## 8. Slice 0 — Implementation Plan (TDD-first)

> **Precondition:** the reliability-first refactor has landed (`/api`,
> `usePeriodicJson`, real `AbortSignal` propagation). See §9.

Each file is preceded by its failing (RED) test.

### Backend (pytest)

| File | New/Mod | Purpose |
|---|---|---|
| `services/backend/tests/test_timeline_router.py` | NEW | RED: time filter on `timeline_at`; all 422 cases (§5); `domain=movements&tier=fine&movement_kind=mil_aircraft` with absolute window + bbox; `civil_aircraft`/`ship`/`satellite` → 501; `total_count`/`truncated` (tracks-not-points); GDELT sample with `title=null` + fallback id; anti-meridian bbox; ISO↔epoch-seconds conversion; `ts_ms` in response. |
| `services/backend/app/models/timeline.py` | NEW | `WindowResponse` + discriminated `WindowSample` union (`kind:"event"\|"track"`), nullable fields. No `GeoEvent` reuse. |
| `services/backend/app/routers/timeline.py` | NEW | Async, READ-ONLY. Events branch: filter `ev.timeline_at`, explicit projection (no `coalesce`), bbox + anti-meridian, fallback id. Movements branch: `SPOTTED_AT` with epoch-second window + bbox, ×1000 → `ts_ms`. Parameter-bound. |
| `services/backend/app/main.py` | MOD | Mount `timeline` router under `/api` only (post-refactor state). |

### Data-ingestion (pytest) — `timeline_at` + honest time semantics

| File | New/Mod | Purpose |
|---|---|---|
| `services/data-ingestion/tests/test_pipeline_timeline_at.py` | NEW | RED: `process_item` keyword time-args optional (old callers unaffected); `ingested_at` always; `timeline_at`/`time_basis` by precedence; **no `now()` as `occurred_at`**; **malformed LLM `occurred_at` → null**, fallback `ingested_at`; event write stamps the fields + `timeline_at`. |
| `services/data-ingestion/tests/test_collector_time_passthrough.py` | NEW | RED: RSS→`published_at`, USGS→`occurred_at`, FIRMS→`observed_at` passed through. |
| `services/data-ingestion/pipeline.py` | MOD | Signature (`:179`, optional keyword time-args) + write (`:380-396`): `timeline_at`/`time_basis`/four time fields instead of the dropped `timestamp`. Validator for the LLM `occurred_at` (schema `:141` allows arbitrary strings) — malformed → null; normalize tz-aware ISO; **precedence: structured collector time beats the LLM hint**. |
| `services/data-ingestion/feeds/{rss,usgs,firms}_collector.py` | MOD | Pass native time into `process_item(...)` (RSS `published_dt`→`published_at` at `:282`; USGS→`occurred_at`; FIRMS→`observed_at`). The other 8 callers stay unchanged (pass nothing → `timeline_at = ingested_at`). |
| `services/data-ingestion/gdelt_raw/writers/neo4j_writer.py` | MOD | `MERGE_EVENT` (`:21`) sets `timeline_at = date_added`, `time_basis="indexed"` on **`ON CREATE` *and* `ON MATCH`** (new writes). |
| `services/data-ingestion/gdelt_raw/migrations/phase3_timeline_at.cypher` + `apply.py` (`apply_phase3()`) + test | NEW | **Idempotent, batched, resumable backfill** for existing data (NOT in `pipeline.py`): `CREATE INDEX event_timeline_at IF NOT EXISTS FOR (e:Event) ON (e.timeline_at)` + `MATCH (e:GDELTEvent) WHERE e.timeline_at IS NULL AND e.date_added IS NOT NULL CALL { WITH e SET e.timeline_at=e.date_added, e.time_basis='indexed' } IN TRANSACTIONS OF 10000 ROWS`. **Run as a documented operational one-shot** (like the existing one-shots at `apply.py:32`), **not** wired into scheduler start; executed in **auto-commit** mode (`CALL {} IN TRANSACTIONS` cannot run inside an explicit transaction). |

### Frontend (Vitest)

| File | New/Mod | Purpose |
|---|---|---|
| `services/frontend/src/state/__tests__/TimeContext.test.tsx` | NEW | RED: live `getTimeMs()`≈now; UI state throttled (no per-frame update); `discontinuityEpoch`++ on seek (incl. forward)/rewind/mode change. Mock `Cesium.Clock`. |
| `services/frontend/src/state/TimeContext.tsx` | NEW | **Keystone.** Ref-based `getTimeMs()`; throttled (~4 Hz) UI state; `discontinuityEpoch`; `mode/playback/window`; `seek/play/pause/setSpeed/setMode`; SYSTEM_CLOCK ↔ SYSTEM_CLOCK_MULTIPLIER. |
| `services/frontend/src/hooks/useTimeWindow.ts` (+ `__tests__`) | NEW | The contract client, built on `usePeriodicJson` (sequence counter / `AbortSignal`). Test: params→query; abort on unmount/window change; `movement_kind=mil_aircraft` loads an absolute window. |
| `services/frontend/src/services/api.ts` | MOD | `getTimeWindow(params)` (`/api` only, no replay). |
| `services/frontend/src/components/time/TwoTierScrubber.tsx` (+ `__tests__`) | NEW | Scrubber shell. Coarse = real graph events; click → `seek(t)` + scope fine window; replay **empty state**. Hlíðskjalf `OverlayPanel` + theme tokens. |
| `services/frontend/src/components/layers/milTrackAdapter.ts` (+ `__tests__`) | NEW | Canonical adapter (§7.5): normalize live `AircraftTrack` (timestamp s) and windowed `kind:"track"` (ts_ms) into one render model; live→`ts_ms` ×1000; `id`→`icao24`. |
| `services/frontend/src/components/layers/MilAircraftLayer.tsx` | MOD | **`clock.onTick`** subscription with cleanup (none today, `:106`); draw track up to `getTimeMs()` + interpolated marker per §7.3; reset the mil layer's **own** render caches on `discontinuityEpoch`; retype `tracks`/`onSelect` to the §7.5 render model. The real replay proof. |
| `services/frontend/src/pages/WorldviewPage.tsx` | MOD | Wrap in `<TimeProvider viewer={viewer}>`; mount `<TwoTierScrubber/>` (bottom-center). **Live mode keeps the existing `useAircraftTracks` hook (`:364`); replay mode switches the mil-track source to `useTimeWindow('movements','fine','mil_aircraft')`** for the selected window, passed to `MilAircraftLayer`. |

**Visual design note:** the scrubber's _visual_ treatment goes through the
Hlíðskjalf-Noir system / a `frontend-design` pass — not invented ad hoc. Slice 0
builds the functional shell with existing tokens.

---

## 9. Dependencies & Sequencing

Slice-0 **code** is gated behind
`docs/superpowers/plans/2026-06-01-reliability-first-refactor.md`, which actively
reshapes the exact surfaces temporal tracking needs:

- Phase 5 removes `/api/v1` and rebuilds `api.ts` + mounts (`:247-268`). Temporal
  tracking uses **only `/api`**, no replay path.
- `usePeriodicJson` is introduced there (`:337-351`, with sequence counter +
  `AbortController`) and is **not yet present** in the tree. `useTimeWindow` builds
  on it.

**Therefore:** this spec may be written and committed now; Slice-0 implementation is
released only after the reliability refactor lands.

---

## 10. Slice 1 & Slice 2 — Forward Scope

**Slice 1 — Event evolution (B), own spec:** event MERGE/dedup (`CREATE_EVENT` has
no dedup → re-ingest duplicates the timeline), an event identity/correlation key, an
evolution model (mutate vs. versioned observation), **event geo backfill** (so bbox
fully applies), **legacy `timeline_at` backfill**, the remaining 8 collectors'
native times, and `events_in_window` as an agent tool with intent routing (template
count 8→9 + test).

**Slice 2 — Movement archive (A), own spec:** a TimescaleDB+PostGIS docker-compose
profile, hypertable + continuous aggregates (with **retention and aggregate-refresh
configured together** — wrongly overlapping refresh windows can drop historical
aggregates; real-time aggregates are off by default since TimescaleDB 2.13), the
movement collectors writing raw samples, `domain=movements` for civil
aircraft/ships/satellites, the satellite TLE-archive + re-propagation path, and
converting `SatelliteLayer`/`ShipLayer` to read `t`. Volume is ~50–150M rows/day, so
"persistent" means raw in a rolling window + downsampled forever; satellites archive
only TLEs (re-propagated at `t`).

---

## 11. Risks & Open Questions

- **Hard precondition:** the reliability refactor must land first (§9).
- **bbox coverage of the coarse tier is partial in Slice 0** (§6) — documented, not
  a silent truncation. Full event geo + legacy backfill are Slice 1.
- **Legacy events without `timeline_at`** appear on the axis only after the Slice-1
  backfill.
- Two-stage review (spec + quality) is mandatory per task; no shortcuts.

---

## 12. Verification (Slice 0, end-to-end)

1. **Backend:** `cd services/backend && uv run pytest tests/test_timeline_router.py`
   + `uv run ruff check app/`. Manually, against local Neo4j:
   `GET /api/timeline/window` returns time-filtered events (tolerating GDELT
   `title=null`) with correct `time_basis`; all 422/501 paths;
   `domain=movements&tier=fine&movement_kind=mil_aircraft&t_start=…&t_end=…` returns
   a real historical track in `ts_ms`.
2. **Data-ingestion:** `uv run pytest tests/test_pipeline_timeline_at.py
   tests/test_collector_time_passthrough.py`; existing collector tests stay green
   (non-breaking). Run the phase-3 migration on a copy, re-run idempotently (no
   double-write). After a short RSS+USGS run, new events carry `timeline_at` /
   `time_basis`; `occurred_at` is never the ingest time.
3. **Frontend:** `cd services/frontend && npm run test && npm run type-check &&
   npm run build`. In the browser (`npm run dev`): live mode is **identical**
   (Profiler shows no per-frame re-renders); the coarse tier shows real events;
   clicking scopes the fine tier; a **mil-track visibly scrubs a historical flight
   path**; rewind/mode-change clears buffers cleanly; "⏭ now" returns to live
   losslessly.
