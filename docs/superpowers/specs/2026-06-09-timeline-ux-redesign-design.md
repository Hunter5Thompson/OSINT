# Timeline UX Redesign — Design Spec

- **Date:** 2026-06-09
- **Status:** Approved (brainstorm). Constraints below are **hard spec edges**, agreed with the user.
- **Supersedes (UX only):** the Slice-0 `TwoTierScrubber` *visual* shell. The Slice-0
  **backend/clock/contract are reused unchanged** — this is a UI replacement, not a rewrite.
- **Related:** `docs/superpowers/specs/2026-06-01-temporal-tracking-design.md` (Slice 0),
  `project_hlidskjalf_aesthetic` (design system).
- **Reference:** WorldView (spatialintelligence.ai / Bilawal Sidhu) — events as
  geolocated dots on a 3D globe + a thin bottom timeline + a *few* curated callouts.

---

## 1. Problem & Motivation

Slice 0 shipped a deliberately-functional **scrubber shell** to prove the data flow.
Fed real production data (**63,799 GDELT events** in window, almost none with a
`title`), `TwoTierScrubber` renders ~200 events as a flex-wrap of text buttons that
collapse to `codebook_type` → a wall of "conflict.armed / conflict.assault" stacked
~33 rows tall, **dead-center over the globe**. It is a list pretending to be a
timeline: no time axis, no aggregation, no density, no dedup. UX-unacceptable.

**Core reframe (the fix):**
- **The globe is the spatial axis** — events with coordinates are **dots on the globe**.
- **The bottom strip is the temporal axis** — a thin **density timeline**, not text.
- **No event text floats over the globe.** At most **one** callout (the selected event).

---

## 2. Scope & Non-Goals

**Reused unchanged (no edits):** `state/TimeContext.tsx` (clock seam, `getTimeMs`,
`seek`, `setMode`, `setReplayWindow`, `discontinuityEpoch`), `hooks/useTimeWindow.ts`,
`services/api.ts getTimeWindow`, the `GET /api/timeline/window` contract + models, the
time-aware `MilAircraftLayer` (fine-tier replay).

**Replaced:** the `TwoTierScrubber` UI → a new **`§ CHRONIK`** density-timeline
component. `ScrubberMount` is rewired to drive it (still owns the rolling coarse
window + the toggle/brush → `setReplayWindow`/`setMode` wiring it already does).

**New (small):** two read-only endpoints — **`/api/timeline/histogram`** (buckets +
notables + geo_events, all aggregated/capped server-side; required because the client
cannot bin 64k from the ≤500-sample `/window`) and **`/api/timeline/events/{id}`**
(callout detail) — plus a **globe event-dot layer** for geo-events.

**Non-goals (this redesign):** free zoom/pan beyond the 3 presets; event geo-backfill
(still Slice 1 — most events lack lat/lon, see §8); civil movements (Slice 2); the
intelligence-agent temporal tool (Slice 1). No change to ingestion or the graph schema.

---

## 3. Architecture & Reuse

```
TimeContext (unchanged) ─ getTimeMs/seek/pause/play/setMode/setReplayWindow ─┐
                                                                             │
ScrubberMount (rewired)                                                      │
   │  useTimeHistogram(range,buckets) ─► { buckets, notables, geo_events }   │
   ▼                       │                         │                       ▼
§ CHRONIK strip (NEW) ◄────┘                         ▼                MilAircraftLayer
  density bars (dominant_category)        EventLayer (MODIFIED:        (unchanged, fine tier)
  notable dots (≤40, severity/incident)    time-aware + fade, fed by
  click=pause+seek / drag=brush            geo_events; keeps category color)
        │ select dot
        ▼
  Callout ─ getEventDetail(id) ─► /api/timeline/events/{id}  (NEW)
```

Units, each one clear purpose:
- **`severity.py` / `severity.ts`** (NEW, shared) — `normalize_severity(raw)` mapping the
  messy real vocab (`low|moderate|medium|elevated|high|critical|warning|extreme|…`, null)
  onto one canonical ordered scale with a defined `unknown` sentinel + a deterministic
  tie-break. Used by the notable criteria/ranking + `by_severity` (backend) and the
  optional severity tick (frontend). **This is the data-integrity keystone (§12).**
- **`ChronikTimeline.tsx`** (NEW) — pure presentational strip: given `{buckets, notables,
  cursorMs, mode, playing, range}` + callbacks `{onSeek, onBrush, onSelectNotable,
  onPreset, onTogglePlay, onNow}`, renders bars + dots + playhead + controls. No fetching.
- **`useTimeHistogram.ts`** (NEW) — fetches `/api/timeline/histogram` for the active range.
- **`EventLayer.tsx`** (MODIFIED) — the **existing** category-coloured globe dot layer,
  made time-aware: fed by `geo_events`, gated by the §7 fade rules; keeps its
  `EVENT_COLORS` palette + stacking. No new parallel layer.
- **`EventCallout`** + **`getEventDetail(id)`** (NEW) — single callout, content from
  `/api/timeline/events/{id}` (§6/§9.2).
- Backend **`/api/timeline/histogram`** (§9.1) + **`/api/timeline/events/{id}`** (§9.2),
  both using the shared severity normalizer.

---

## 4. The § CHRONIK strip (coarse / temporal axis)

**Placement:** full-width, docked at the **very bottom**, ~90px tall. The globe above
stays clear. Existing bottom-left panels (Ticker etc.) get their `bottom` offset
raised so nothing overlaps the strip. Hlíðskjalf `OverlayPanel` chrome + theme tokens,
§ grammar label `§ CHRONIK`.

**Density histogram (HARD — bucket colour semantics, constraint #1):**
- `height = event count` in the bucket (the *only* thing height encodes).
- `colour = the bucket's **dominant category**` — the codebook **category** (first
  segment of `codebook_type`, e.g. `military`, `conflict`, `civil`) that the **plurality**
  of the bucket's events fall in (modal), **NOT** any single-outlier rule. A bucket of 200
  `civil` + 1 `military` is a **tall civil-coloured bar** (`dominant_category = civil`).
  - **Why category, not severity (data reality, §9):** GDELT events — the bulk — carry
    `codebook_type` but **no severity**. Category is present on essentially all events;
    severity is sparse. Colouring by severity would leave most bars/dots neutral.
  - Reuses the existing **`EVENT_COLORS`** category palette from `EventLayer.tsx` (single
    source of truth, shared with the globe dots in §7).
- The full `by_category` breakdown is returned alongside for an optional richer treatment.
- **Severity is not discarded:** it drives the **Notable-Dots** (below) and an **optional
  thin severity tick** on bars where severity is present. Count (height), category
  (colour), and severity (dots/tick) are three independent readings.
- ~120 buckets across the active range; bucket width = range / 120.

**Notable-Dots (HARD — cap + ranking, constraint #2):**
- **Criteria:** severity ∈ {high, critical} OR the event is an **auto-promoted
  incident**.
- **Cap: at most 40 visible dots.**
- **Ranking (descending):** `critical > promoted-incident > high > recency`.
- **Overflow:** when more than the cap qualify, show only the top-ranked; the rest are
  represented by their bucket's bar (and reachable via Inspector/Ticker). Optionally
  cluster adjacent overflow into a single "+N" dot. Never render >40 dots.
- A dot sits above its bucket with a faint connector; hover → tooltip (title|type,
  time, severity). Dots are the **only** prominent markers on the strip.

**Controls:** play/pause (▶/⏸), speed ×1/×5/×60, step ⏮/⏭ (jump bucket), current
timestamp, `● LIVE` badge, and range presets **24h / 7d / 30d** (default **7d**).

---

## 5. Cursor vs Brush semantics (HARD — constraint #3)

These must be unambiguous and are the heart of "intuitive":

- **Click on the strip → `pause()` + `seek(timestamp)`** — a *point* cursor (inspect).
  The `pause()` is **load-bearing**: in **live** mode Cesium runs `SYSTEM_CLOCK`, so
  without pausing the next `onTick` yanks the cursor back to *now* and the seek would not
  hold (the fragility flagged in review). Pausing freezes the follow so the cursor stays
  where clicked. This changes the **playing** state (→ paused), **not** the live/replay
  **mode** (so it stays consistent with "click does not change mode"). A `⏭ NOW` control
  resumes live-follow (calls `play()` in live and re-pins to now). In replay, click
  pauses + moves the playhead within the window; `play()` resumes forward from there.
- **Drag across the strip → `setReplayWindow(start, end)` + `setMode("replay")`** — a
  *range* brush. Scopes the fine tier (mil-tracks) and the globe event-dots to
  `[start, end]`, and plays it.
- **Preset change (24h/7d/30d)** sets the **coarse range only** (what the histogram
  spans). It must **not** reset the Inspector/callout selection and **not** change
  live/replay mode, the playing state, or the brush window.

---

## 6. Single Callout (HARD — constraint, default #3)

At most **one** callout at a time — the **selected** event. **Selection happens only by
clicking a Notable-Dot or a globe event-dot** (a plain click on a bar / empty strip is a
`seek`, per §5 — never a selection, so the two gestures don't collide). The callout is a
compact Hlíðskjalf box (title | type · time · source · severity, with a `→ Inspector`
action) and, if the event has coordinates, a thin connector line to its globe location.
Selecting another event replaces it; never a wall of persistent boxes.

**Detail source (HARD — review finding #3):** the callout content is fetched on
selection from a dedicated **`GET /api/timeline/events/{id}`** endpoint (§9) returning
the full payload (title, codebook_type, severity, time, time_basis, **source, url**,
location_name, country, lat, lon). This is robust + uniform: it works for **any**
selected dot regardless of whether that event is in the (sampled, ≤500) `/window`
response, and keeps the `notables`/`geo_events` lists lean (they carry only what a dot +
hover-tooltip need). The callout shows a brief loading state until the detail resolves.

---

## 7. Globe event-dots (spatial axis) + fade rules (HARD — constraint #4)

**Reuse, don't duplicate:** the codebase already has **`EventLayer.tsx`** — an imperative
Cesium `BillboardCollection` of geo-events coloured by **category** (`EVENT_COLORS`) with
position-stacking/declutter, but it is **not time-aware**. This redesign **makes
`EventLayer` time-aware** (drives it from the timeline window/cursor with the fade rules
below) rather than adding a parallel layer (two event layers = worse clutter). It keeps
the **category** colouring (consistent with the §4 bars; grounded — see §4) and its
stacking. Still imperative `BillboardCollection`, NOT the Entity API (CLAUDE.md).

**Data source (HARD — review finding #2):** the layer is **NOT** fed by `/window`
(capped ≤500, cannot represent 64k). It is fed by the histogram endpoint's **`geo_events`**
array (§9): geo-located events across the active coarse range, **capped at ≤200, ranked by
`severity` then `recency`**, with a `geo_truncated` flag and a `geo_located_count`. (This
replaces `EventLayer`'s current un-scoped `/graph/events/geo` poll.) ≤200 ranked dots over
the range — gated further by the
fade rules below — is bounded and salient (never a 64k flood). If geo-events exceed the
cap, the lowest-severity/oldest are dropped (reflected by `geo_truncated`); the strip's
buckets still count **all** events, so nothing silently disappears from the totals.

**Fade rules (so it never looks random):**
- Events whose time is inside the **current cursor time-window** → **full opacity**.
- Events temporally **near** the cursor → short **temporal falloff opacity** (linear
  fade over a small ± band, e.g. ±N minutes/hours scaled to the range).
- Events **outside the active brush/replay window** → **invisible**.
- (Live mode: the "window" is a trailing band ending at `now`; replay: the brush window.)

Click a globe dot → the same single callout (§6) + `seek` to that event's time.

---

## 8. Non-geo events — explicit, never lost (HARD — constraint #5)

Most current events have **no coordinates** (Slice-0 reality; geo-backfill is Slice 1).
These events:
- **ARE** counted in the histogram buckets and **ARE** reachable via the Ticker and the
  Inspector / callout.
- **ARE NOT** plotted on the globe.

This is documented in the UI (e.g. the strip can show "globe-located: X / Y in window")
so the timeline is never perceived as incomplete just because the globe is sparse.

---

## 9. Data: new endpoints

The client cannot bin 64k events (the `/window` response is capped at 500 samples), so
density, notables, and geo-dots are aggregated/curated in Neo4j (the `event_timeline_at`
index from Slice 0 makes this cheap). Two new READ-ONLY endpoints; both parameter-bound,
same 422/503 discipline as `/window`. The existing `/window` is **unchanged**.

### 9.1 `GET /api/timeline/histogram` — strip + globe data

```
GET /api/timeline/histogram
  ?t_start=<ISO> &t_end=<ISO>          required
  &buckets=<int, default 120, max 240>
  &domain=events                       (events only for now)
  &bbox=west,south,east,north          optional (same anti-meridian convention)
→ {
    t_start, t_end, bucket_ms,
    buckets: [ { ts, count,
                 by_category: { <category>: n, ... },     // codebook 1st-segment counts
                 dominant_category,                        // colour = modal category (§4)
                 by_severity: { low, medium, high, critical, unknown } } ],  // for optional tick
    notables: [ { id, time, time_basis, severity, title?, codebook_type?,
                  lat?, lon?, is_incident, rank } ],   // cap ≤40, ranked (§4) — dots+tooltip only
    geo_events: [ { id, time, codebook_type, severity, lat, lon, is_incident } ],  // cap ≤200 (§7)
    total_count, geo_located_count, geo_truncated
  }
```

- `buckets[].dominant_category` = the **modal** (plurality) codebook category in the
  bucket (bar colour, via `EVENT_COLORS`); `by_category` is the full breakdown (§4). One
  outlier category can never repaint the bar. `by_severity` is included for the optional
  severity tick (severity is sparse — most GDELT events land in `unknown`).
- `notables` = **cap ≤40, ranked `critical > promoted-incident > high > recency`** (§4),
  computed server-side so the client never receives or renders more. Lean payload
  (enough for a dot + hover tooltip). Source = severity high/critical `:Event` nodes
  **plus** `:Incident` nodes in the window (GDELT has no severity, so incidents are a
  distinct notable source — see §12).
- `geo_events` = geo-located events, **cap ≤200, ranked `severity` then `recency`** (§7);
  `geo_truncated` true when more existed. Carries `codebook_type` for the category colour.
- `total_count` / `geo_located_count` feed the §8 "X / Y located" honesty line.

### 9.2 `GET /api/timeline/events/{id}` — callout detail (review finding #3)

```
GET /api/timeline/events/{id}
→ { id, title?, codebook_type?, severity?, time, time_basis,
    source?, url?, location_name?, country?, lat?, lon? }    // 404 if unknown id
```

Resolves the full callout payload for any selected event by the same identity the lists
use (`coalesce(ev.id, ev.event_id, toString(elementId(ev)))`). Robust + uniform: works
whether or not the event was in a sampled list; keeps `notables`/`geo_events` lean.

### 9.3 Unchanged

`GET /api/timeline/window` still serves the windowed **samples** (fine-tier mil-tracks;
and any direct event-sample use). No changes.

---

## 10. Aesthetic

Hlíðskjalf-Noir throughout (palette, Martian Mono, § grammar, `OverlayPanel`). Exact
severity colours, dot/bar styling, and the callout layout go through a **frontend-design
pass during implementation** — this spec fixes behaviour and structure, not pixels.

---

## 11. Testing

- **Severity normalizer (keystone):** `normalize_severity` maps every real-world value
  (`low|moderate|medium|elevated|high|critical|warning|extreme`, mixed case, null,
  unknown garbage) to the canonical scale; assert each mapping + that null/unknown →
  `unknown` sentinel (never a random colour/rank); assert the deterministic tie-break.
- **Backend (histogram):** bucketing (counts per bucket, `by_category`,
  `dominant_category` = **modal not outlier** — assert a 200-`civil`+1-`military` bucket
  yields `dominant_category = civil`); `by_severity` (incl. `unknown`); notable **cap ≤40
  + ranking** (`critical > promoted > high > recency`) over `:Event`+`:Incident` sources;
  `geo_events` **cap ≤200 + ranking + `geo_truncated`**; `geo_located_count`; 422/503.
- **Backend (detail):** `events/{id}` returns the full payload for a known id (incl.
  source/url/location); 404 for an unknown id.
- **Frontend:** bin→bar mapping (height=count, colour=`dominant_category` via
  `EVENT_COLORS`, NOT blended); notable cap/ranking + overflow; **click = `pause()`+`seek`
  (cursor holds in live) vs drag = brush** semantics; preset change does not reset
  selection/mode/playing; `EventLayer` time-aware fade (in-window full, near falloff,
  outside invisible); single-callout replacement + detail-fetch loading state.

---

## 12. Risks & Open Questions

- **Severity vocabulary is genuinely inconsistent** across the codebase (hotspots use
  `{low,moderate,elevated,high,critical}`; incidents `{low,elevated,high,critical}`;
  RSS extraction `{low,medium,high,critical}`; GDACS numeric; GDELT **none**). The shared
  `normalize_severity` + deterministic tie-break is **Task 1** of the plan; everything
  severity-touching (notables, ranking, `by_severity`, tick) derives from it. Without it,
  colours/rankings would be non-deterministic.
- **Notables span two node types.** Because GDELT (the bulk) has no severity, the notable
  set = high/critical `:Event` nodes **∪** `:Incident` nodes in the window (the
  auto-promoter's curated set). The histogram query unions both, dedupes, then caps/ranks.
- **`EventLayer` is being repurposed** from an un-scoped poll (`/graph/events/geo`) to the
  timeline-scoped `geo_events`. Verify no other consumer depends on its old behaviour
  (it is mounted only in `WorldviewPage`); keep the `layers.events` toggle working.
- Histogram endpoint perf on ~64k events — mitigated by the `event_timeline_at` index;
  verify with `EXPLAIN`/timing in the plan.
- Bucket→pixel aliasing at 120 buckets on narrow viewports — clamp bucket count to width.
- The Slice-0 phase-3 migration's deprecated `CALL {}` Cypher is a **separate** tiny
  follow-up, not part of this redesign.
- Two-stage review (spec + quality) mandatory per task; **lean/solo by default** (token
  cost); multi-agent review only with a cost heads-up + opt-in.
