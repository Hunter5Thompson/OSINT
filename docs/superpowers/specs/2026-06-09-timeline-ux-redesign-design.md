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

**New (small):** a server-side **histogram aggregation endpoint** (§9) — required
because the client cannot bin 64k events from the ≤500-sample `/window` response.
A new **globe event-dot layer** for geo-events.

**Non-goals (this redesign):** free zoom/pan beyond the 3 presets; event geo-backfill
(still Slice 1 — most events lack lat/lon, see §8); civil movements (Slice 2); the
intelligence-agent temporal tool (Slice 1). No change to ingestion or the graph schema.

---

## 3. Architecture & Reuse

```
TimeContext (unchanged)  ──getTimeMs/seek/setMode/setReplayWindow──┐
                                                                   │
ScrubberMount (rewired) ── useTimeWindow('events','coarse') detail ┤
   │  + NEW useTimeHistogram(range,buckets)  ───────────────────┐  │
   ▼                                                            ▼  ▼
§ CHRONIK strip (NEW)          EventDotLayer on globe (NEW)   MilAircraftLayer (unchanged)
  density bars + notable dots    BillboardCollection dots       fine-tier replay
  cursor / brush / playback      severity color + fade rules
```

New units, each one clear purpose:
- **`ChronikTimeline.tsx`** — pure presentational strip: given `{buckets, notables,
  cursorMs, mode, range}` + callbacks `{onSeek, onBrush, onSelectNotable, onPreset,
  onTogglePlay}`, renders bars + dots + playhead + controls. No data fetching.
- **`useTimeHistogram.ts`** — fetches the aggregation endpoint for the active range.
- **`EventDotLayer.tsx`** — imperative Cesium `BillboardCollection` of geo-event dots
  with the fade rules (§7).
- Backend **`/api/timeline/histogram`** — aggregation (§9).

---

## 4. The § CHRONIK strip (coarse / temporal axis)

**Placement:** full-width, docked at the **very bottom**, ~90px tall. The globe above
stays clear. Existing bottom-left panels (Ticker etc.) get their `bottom` offset
raised so nothing overlaps the strip. Hlíðskjalf `OverlayPanel` chrome + theme tokens,
§ grammar label `§ CHRONIK`.

**Density histogram (HARD — bucket colour semantics, constraint #1):**
- `height = event count` in the bucket (the *only* thing height encodes).
- `colour = the bucket's **highest** severity present` (max-severity), NOT a blend that
  lets one Critical paint a 200-Low bucket as Critical. A bucket of 200 Low + 1 Critical
  is a **tall Low-coloured bar** — and the single Critical is **additionally** surfaced
  as a Notable-Dot above it. Count and severity are thus two independent readings.
- ~120 buckets across the active range; bucket width = range / 120.
- Severity → Hlíðskjalf palette (low → … → critical); exact tokens via a
  `frontend-design` pass, not invented here.

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

- **Click on the strip → `seek(timestamp)`** — a *point* cursor only. Moves the playhead
  / clock cursor. **Does not change mode** by itself (a click in live stays live but
  jumps the cursor; in replay it moves within the window).
- **Drag across the strip → `setReplayWindow(start, end)` + `setMode("replay")`** — a
  *range* brush. Scopes the fine tier (mil-tracks) and the globe event-dots to
  `[start, end]`, and plays it.
- **Preset change (24h/7d/30d)** sets the **coarse range only** (what the histogram
  spans). It must **not** reset the Inspector selection and **not** change live/replay
  mode or the brush window.

---

## 6. Single Callout (HARD — constraint, default #3)

At most **one** callout at a time — the **selected** event. **Selection happens only by
clicking a Notable-Dot or a globe event-dot** (a plain click on a bar / empty strip is a
`seek`, per §5 — never a selection, so the two gestures don't collide). The callout is a
compact Hlíðskjalf box (title | type · time · source · severity, with a `→ Inspector`
action) and, if the event has coordinates, a thin connector line to its globe location.
Selecting another event replaces it; never a wall of persistent boxes.

---

## 7. Globe event-dots (spatial axis) + fade rules (HARD — constraint #4)

Geo-events (those with `lat/lon`) render as **severity-coloured dots on the globe** via
an imperative Cesium **`BillboardCollection`** (NOT the Entity API — CLAUDE.md).

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

## 9. Data: server-side histogram endpoint (new)

The client cannot bin 64k events (the `/window` response is capped at 500 samples), so
density must be aggregated in Neo4j (the `event_timeline_at` index from Slice 0 makes
this cheap).

```
GET /api/timeline/histogram
  ?t_start=<ISO> &t_end=<ISO>          required
  &buckets=<int, default 120, max 240>
  &domain=events                       (events only for now)
  &bbox=west,south,east,north          optional (same anti-meridian convention)
→ {
    t_start, t_end, bucket_ms,
    buckets: [ { ts, count, by_severity: {low,medium,high,critical}, max_severity } ],
    notables: [ { id, time, time_basis, severity, title?, codebook_type?,
                  lat?, lon?, is_incident, rank } ],   // already capped+ranked server-side
    total_count, geo_located_count
  }
```

- READ-ONLY, parameter-bound Cypher, same 422/503 discipline as `/window`.
- `notables` is computed + **capped (≤40) and ranked server-side** per §4 so the client
  never receives or renders more.
- `total_count` / `geo_located_count` feed the §8 "X / Y located" honesty line.
- The existing `/window` endpoint is unchanged and still serves the **detail** samples
  (callout content, fine-tier tracks).

---

## 10. Aesthetic

Hlíðskjalf-Noir throughout (palette, Martian Mono, § grammar, `OverlayPanel`). Exact
severity colours, dot/bar styling, and the callout layout go through a **frontend-design
pass during implementation** — this spec fixes behaviour and structure, not pixels.

---

## 11. Testing

- **Backend:** histogram bucketing (counts per bucket, `max_severity`, `by_severity`),
  notable **cap (≤40) + ranking order**, `geo_located_count`, 422/503 paths.
- **Frontend:** bin→bar mapping (height=count, colour=max-severity, NOT blended);
  notable cap/ranking + overflow; **cursor=seek vs drag=brush** semantics; preset change
  does not reset selection/mode; globe-dot fade buckets (in-window full, near falloff,
  outside invisible); single-callout replacement.

---

## 12. Risks & Open Questions

- Histogram endpoint perf on ~64k events — mitigated by the `event_timeline_at` index;
  verify with `EXPLAIN`/timing in the plan.
- Bucket→pixel aliasing at 120 buckets on narrow viewports — clamp bucket count to width.
- The Slice-0 phase-3 migration's deprecated `CALL {}` Cypher is a **separate** tiny
  follow-up, not part of this redesign.
- Two-stage review (spec + quality) mandatory per task; no shortcuts.
