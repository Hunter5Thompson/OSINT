# ODIN S1 Foundation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver Sprint 1 from `2026-04-14-odin-4layer-hlidskjalf-design.md`: Hlidskjalf foundation with design tokens + self-hosted fonts, singleton Orrery system, persistent App shell/top bar, and Landing page wired to real backend data (`/api/signals/stream` + existing APIs).

**Scope of this plan (S1 only):**
- New app shell and route skeleton (`/`, `/worldview`, `/briefing`, `/warroom`)
- Landing page (Astrolabe) with live signal feed
- Hlidskjalf design system baseline (tokens, typography, grain primitives)
- Backend signal SSE endpoint + replay semantics required for Landing
- Migration rule for legacy query links (`/?entity=...`, `/?layer=...` -> `/worldview?...`)

**Explicitly out of scope in this plan:**
- Worldview panel redesign (S2)
- Briefing Room implementation (S3)
- War Room implementation (S4)
- Playwright visual regression (follow-up spec)

**Primary spec:** `docs/superpowers/specs/2026-04-14-odin-4layer-hlidskjalf-design.md`

---

## File Map

**Frontend — Create**
- `services/frontend/src/app/router.tsx` — route tree + legacy query migration redirect
- `services/frontend/src/app/AppShell.tsx` — persistent top bar + outlet
- `services/frontend/src/pages/LandingPage.tsx` — S1 Astrolabe page
- `services/frontend/src/pages/BriefingPage.tsx` — placeholder shell
- `services/frontend/src/pages/WarRoomPage.tsx` — placeholder shell
- `services/frontend/src/pages/WorldviewPage.tsx` — wraps existing globe app for `/worldview`
- `services/frontend/src/components/hlidskjalf/OrreryProvider.tsx` — singleton rAF loop
- `services/frontend/src/components/hlidskjalf/Orrery.tsx` — S/M/L SVG orrery
- `services/frontend/src/components/hlidskjalf/TopBar.tsx` — persistent nav
- `services/frontend/src/components/hlidskjalf/NumericHero.tsx` — numeral tiles
- `services/frontend/src/components/hlidskjalf/SignalFeedItem.tsx` — live feed row
- `services/frontend/src/components/hlidskjalf/SectionHeading.tsx` — `§` headings
- `services/frontend/src/components/hlidskjalf/GrainOverlay.tsx` — panel grain primitive
- `services/frontend/src/hooks/useSignalFeed.ts` — SSE consumer + reconnect/replay/dedupe
- `services/frontend/src/types/signals.ts` — event envelope + feed item types
- `services/frontend/src/test/hlidskjalf/orrery.test.tsx` — SVG structure + reduced motion
- `services/frontend/src/test/routing/legacyRedirect.test.tsx` — migration rule tests
- `services/frontend/src/test/landing/signalFeed.test.tsx` — SSE parsing + dedupe tests

**Frontend — Modify**
- `services/frontend/src/main.tsx` — render RouterProvider
- `services/frontend/src/App.tsx` — keep existing globe implementation but export as world page content
- `services/frontend/src/index.css` — reduce to baseline resets + import hlidskjalf theme
- `services/frontend/src/services/api.ts` — add `/api/signals/*` helpers
- `services/frontend/package.json` — add `react-router-dom`, add `test` script if missing
- `services/frontend/vite.config.ts` — keep `/api` proxy, ensure tests include new suites

**Theme/Assets — Create**
- `services/frontend/src/theme/hlidskjalf.css` — tokens, type, utilities, motion-reduce
- `services/frontend/public/fonts/instrument-serif/InstrumentSerif-Italic.woff2`
- `services/frontend/public/fonts/instrument-serif/InstrumentSerif-Italic-Bold.woff2`
- `services/frontend/public/fonts/hanken-grotesk/HankenGrotesk-Variable.woff2`
- `services/frontend/public/fonts/martian-mono/MartianMono-Variable.woff2`

**Backend — Create**
- `services/backend/app/routers/signals.py` — `/api/signals/stream` + optional snapshot endpoint
- `services/backend/app/models/signals.py` — event envelope + DTOs
- `services/backend/app/services/signal_stream.py` — ring buffer + replay helper + Redis stream read adapter
- `services/backend/tests/unit/test_signals_stream.py` — SSE replay contract tests

**Backend — Modify**
- `services/backend/app/main.py` — include `signals` router at `/api`
- `services/backend/app/config.py` — add `redis_stream_events` and stream tuning settings
- `services/backend/app/services/cache_service.py` — add Redis stream helpers (`xread`, `xrevrange`) if needed
- `services/backend/pyproject.toml` — add ULID dependency for stable sortable IDs

---

## Task 1: Router + App Shell foundation

**Goal:** Introduce 4 top-level routes without rewriting Worldview internals in S1.

- [ ] **Step 1: Add routing dependency**

```bash
cd /home/deadpool-ultra/ODIN/OSINT/services/frontend
npm install react-router-dom
```

- [ ] **Step 2: Create route tree**

Implement `src/app/router.tsx` with:
- `/` -> `<LandingPage />`
- `/worldview` -> `<WorldviewPage />`
- `/briefing` and `/briefing/:reportId` -> placeholder page
- `/warroom` and `/warroom/:incidentId` -> placeholder page
- shared wrapper `<AppShell />` containing top bar + `<Outlet />`

- [ ] **Step 3: Wire router from entrypoint**

Replace `src/main.tsx` root render from `<App />` to `<RouterProvider router={router} />`.

- [ ] **Step 4: Keep existing globe behavior intact under `/worldview`**

Move or wrap current `App.tsx` globe output into `WorldviewPage` so zero layer regressions occur in S1.

- [ ] **Step 5: Implement migration redirect rule**

In root route loader/component:
- if path is `/` and query contains `entity` or `layer`, redirect to `/worldview` preserving query
- otherwise render Landing

- [ ] **Step 6: Add routing tests**

`legacyRedirect.test.tsx` assertions:
- `/?entity=sinjar` => navigates to `/worldview?entity=sinjar`
- `/?layer=firmsHotspots` => navigates to `/worldview?layer=firmsHotspots`
- `/` without query stays on Landing

---

## Task 2: Hlidskjalf tokens + typography baseline

**Goal:** Replace tactical green base style with Hlidskjalf Noir foundation.

- [ ] **Step 1: Add self-hosted fonts under `public/fonts`**

Use WOFF2 only, with deterministic filenames.

- [ ] **Step 2: Create `src/theme/hlidskjalf.css`**

Must include:
- palette vars from spec section 2.1
- `@font-face` for Instrument Serif / Hanken Grotesk / Martian Mono (`font-display: swap`)
- type utilities (`.serif`, `.mono`, `.eyebrow`, `.hair`, color helpers)
- minimum readable text guardrails (10px mono min, body >= 12px)
- `prefers-reduced-motion: reduce` rules for all shared animation classes

- [ ] **Step 3: Trim `index.css` to app baseline + imports**

Keep Cesium layout overrides; remove old tactical theme colors and font stack; import `hlidskjalf.css`.

- [ ] **Step 4: Verify font loading behavior**

Manual check in DevTools (cold load): all families load from local `public/fonts/*`, no external font requests.

---

## Task 3: Shared Hlidskjalf component primitives

**Goal:** Build reusable presentation components before page composition.

- [ ] **Step 1: Implement `OrreryProvider` singleton loop**

Requirements:
- exactly one `requestAnimationFrame` loop globally
- subscribers receive monotonic `t` seconds
- stop loop when no subscribers remain
- static mode when `prefers-reduced-motion: reduce`

- [ ] **Step 2: Implement `Orrery` component**

Requirements:
- S/M/L sizes (`40`, `110`, `220`)
- 3 independent bodies (Munin/Hugin/Sentinel)
- per-body depth transform (opacity + scale) from orbital angle
- no Three.js / no external animation deps

- [ ] **Step 3: Implement shell primitives**

Create presentational components:
- `TopBar`
- `SectionHeading`
- `NumericHero`
- `SignalFeedItem`
- `GrainOverlay`

- [ ] **Step 4: Add orrery tests**

`orrery.test.tsx`:
- snapshot of static SVG structure
- reduced-motion mode renders deterministic static constellation
- provider does not create duplicate loops across multiple mounted Orreries

---

## Task 4: Backend signal stream for Landing

**Goal:** Provide `/api/signals/stream` with S1-compatible replay semantics.

- [ ] **Step 1: Add signal stream config knobs**

In `services/backend/app/config.py`:
- `redis_stream_events` default `"events:new"`
- `signals_replay_window_seconds` default `900`
- `signals_poll_interval_ms` default `1000`
- `signals_ring_buffer_size` default `2000`

- [ ] **Step 1b: Add ULID dependency**

In `services/backend/pyproject.toml`, add:
- `ulid-py>=1.1`

- [ ] **Step 2: Implement signal envelope model**

`models/signals.py`:
- `event_id` (ULID string)
- `ts` (UTC ISO8601)
- `type` (e.g. `signal.firms`)
- `payload` object with title/source/severity/location/url fields (nullable where needed)

- [ ] **Step 3: Implement ring buffer + replay service**

`services/signal_stream.py`:
- in-memory append-only deque for last 15 minutes
- lookup events newer than given `last_event_id`
- dedupe by `event_id`
- helper to map Redis stream entries (`events:new`) -> envelope

- [ ] **Step 4: Implement `signals` router**

`/api/signals/stream` (SSE):
- supports `Last-Event-ID`
- replays buffered events where `event_id > last`
- emits keepalive comments/heartbeat
- if replay window exceeded, emits explicit `reset` event before resuming

Optional S1 helper endpoint:
- `/api/signals/latest?limit=6` for initial hydration if FE connects before first SSE frame

- [ ] **Step 5: Register router**

In `main.py`, include router with `/api` prefix (not `/api/v1`).

- [ ] **Step 6: Backend tests**

`tests/unit/test_signals_stream.py`:
- connect, receive N, reconnect with last id -> only `>` last
- dedupe behavior on duplicate source entries
- stale `Last-Event-ID` beyond replay window -> `reset` emitted

---

## Task 5: Landing page wiring (real data)

**Goal:** Landing shows four numerals + live signal feed with zero fake data.

- [ ] **Step 1: Add signal types + API helpers**

In frontend:
- add `SignalEventEnvelope` types
- add stream URL constant `/api/signals/stream`
- add optional `getLatestSignals(limit)` helper if endpoint exists

- [ ] **Step 2: Implement `useSignalFeed` hook**

Behavior:
- connect via `EventSource`
- parse envelope
- reconnect with exponential backoff: `1s, 2s, 4s ... max 30s`
- preserve `lastEventId`
- maintain dedupe `Set<event_id>` with cap 500
- expose status (`live` | `reconnecting` | `down`) + latest 6 feed rows

- [ ] **Step 3: Implement `LandingPage` layout**

Render:
- index eyebrow + correlation metric slot
- 4 `NumericHero` tiles
- signal feed list from `useSignalFeed`
- Orrery M anchor

S1 data wiring:
- use existing endpoints for count metrics (hotspots/events/etc.)
- use `/api/signals/stream` for feed rows

- [ ] **Step 4: Wire tile/feed interactions**

- numeral click -> navigate `/worldview` with query filter
- feed click -> navigate `/worldview?entity=...` (or canonical query key from payload)

- [ ] **Step 5: Landing tests**

`signalFeed.test.tsx`:
- incoming events render in order
- duplicate `event_id` ignored
- reconnecting status line appears on disconnect

---

## Task 6: Top bar + shared shell behavior

**Goal:** Persistent top navigation and clock with Hlidskjalf style.

- [ ] **Step 1: Build `TopBar` in shell**

Must include:
- left: Orrery S + wordmark
- middle: route tabs (`HOME`, `WORLDVIEW`, `BRIEFING`, `WAR ROOM`)
- right: UTC timestamp in mono

- [ ] **Step 2: Active tab styling + nav semantics**

- active route highlights parchment + dot
- keyboard/ARIA semantics for navigation links
- no hover-heavy animation; keep transitions minimal

- [ ] **Step 3: Reduced-motion compliance**

Ensure:
- no pulse animations when `prefers-reduced-motion`
- landing reveal disabled under reduced motion

---

## Task 7: Verification + acceptance checklist (S1)

- [ ] **Step 1: Frontend unit tests**

```bash
cd /home/deadpool-ultra/ODIN/OSINT/services/frontend
npm run lint
npm run type-check
npx vitest run
```

- [ ] **Step 2: Backend tests**

```bash
cd /home/deadpool-ultra/ODIN/OSINT/services/backend
uv run pytest -q tests/unit/test_signals_stream.py
```

- [ ] **Step 3: Manual acceptance walk**

1. Open `/` -> Landing appears, top bar persistent.
2. Open `/worldview` -> existing globe still functions (no S1 regression).
3. Trigger ingestion event (or inject into Redis stream) -> Landing feed updates without reload.
4. Disconnect backend stream -> `reconnecting` state shown, auto-retry occurs.
5. Reload with `/?entity=foo` -> redirected to `/worldview?entity=foo`.

- [ ] **Step 4: Performance smoke**

- verify local fonts loaded from `public/fonts`
- verify no visible FPS drop from idle grain/top-bar on globe route

---

## Suggested commit slices

1. `feat(frontend): add router shell and legacy query redirect to worldview`
2. `feat(frontend): add hlidskjalf theme tokens fonts and shared primitives`
3. `feat(backend): add /api/signals/stream with replay ring buffer`
4. `feat(frontend): add landing astrolabe with live signal feed`
5. `test: add routing orrery and signal stream contract tests`

---

## Risks and mitigations (S1)

- **Risk:** Existing globe route regresses during router migration.  
  **Mitigation:** Keep current globe implementation encapsulated in `WorldviewPage` with no functional layer changes.

- **Risk:** Redis stream unavailable in local env.  
  **Mitigation:** backend stream emits heartbeat + explicit empty state; FE shows `reconnecting`/`stale` states without white screen.

- **Risk:** Font licensing/provenance unclear.  
  **Mitigation:** add `public/fonts/README.md` documenting source and license before merge.

- **Risk:** Multiple animation loops from many Orreries.  
  **Mitigation:** singleton provider + unit test asserting single rAF registration.
