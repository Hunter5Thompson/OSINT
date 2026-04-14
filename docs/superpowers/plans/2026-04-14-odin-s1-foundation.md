# ODIN S1 Foundation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver Sprint 1 from `2026-04-14-odin-4layer-hlidskjalf-design.md`: design tokens + self-hosted fonts, singleton Orrery, persistent AppShell + TopBar, and Landing page with real data (`/api/signals/stream`, `/api/signals/latest`, `/api/landing/summary`).

**S1 scope only:**
- Route skeleton (`/`, `/worldview`, `/briefing`, `/warroom`)
- Landing Astrolabe with live signal feed and four numerals
- Shared Hlidskjalf primitives + theme baseline
- Backend signal streaming and landing-summary contracts

**Out of scope in this plan:**
- Worldview panel redesign (S2)
- Briefing Room implementation (S3)
- War Room implementation (S4)
- Playwright visual regression (follow-up spec)

**Primary spec:** `docs/superpowers/specs/2026-04-14-odin-4layer-hlidskjalf-design.md`

---

## Execution Rule (Mandatory)

Every implementation task follows **Red -> Green -> Refactor**:
1. Write failing tests first.
2. Implement the minimum change to pass.
3. Refactor without breaking tests.

No task is considered complete without passing tests for that task.

---

## Decisions Locked For S1

1. **React Router:** use `react-router-dom@7` (major pinned).
2. **Signal producer:** existing ingestion pipeline remains producer (`events:new` via `process_item`); add explicit preflight verification and a manual Redis inject command for deterministic local testing.
3. **Landing numerals data source:** implement dedicated backend endpoint `/api/landing/summary?window=24h`.
   - `hotspots_24h`: count from FIRMS hotspots data source.
   - `conflict_24h`: count from UCDP/Conflict events in Neo4j.
   - `nuntii_24h`: count of ingested events/documents in the last 24h.
   - `libri_24h`: reports count (S1 fallback to `0` with `reports_not_available_yet=true` until S3 `/api/reports` exists).

---

## File Map

**Frontend — Create**
- `services/frontend/src/app/router.tsx` — route tree + legacy query migration
- `services/frontend/src/app/AppShell.tsx` — persistent shell (`TopBar` + `Outlet`)
- `services/frontend/src/pages/LandingPage.tsx` — S1 Astrolabe page
- `services/frontend/src/pages/WorldviewPage.tsx` — wraps existing globe app
- `services/frontend/src/pages/BriefingPage.tsx` — placeholder shell
- `services/frontend/src/pages/WarRoomPage.tsx` — placeholder shell
- `services/frontend/src/components/hlidskjalf/OrreryProvider.tsx`
- `services/frontend/src/components/hlidskjalf/Orrery.tsx`
- `services/frontend/src/components/hlidskjalf/TopBar.tsx`
- `services/frontend/src/components/hlidskjalf/NumericHero.tsx`
- `services/frontend/src/components/hlidskjalf/SignalFeedItem.tsx`
- `services/frontend/src/components/hlidskjalf/SectionHeading.tsx`
- `services/frontend/src/components/hlidskjalf/GrainOverlay.tsx`
- `services/frontend/src/hooks/useSignalFeed.ts`
- `services/frontend/src/types/signals.ts`
- `services/frontend/src/types/landing.ts`
- `services/frontend/src/test/routing/legacyRedirect.test.tsx`
- `services/frontend/src/test/layout/topBar.test.tsx`
- `services/frontend/src/test/hlidskjalf/orrery.test.tsx`
- `services/frontend/src/test/theme/hlidskjalfTheme.test.tsx`
- `services/frontend/src/test/landing/signalFeed.test.tsx`
- `services/frontend/src/test/landing/landingSummary.test.tsx`

**Frontend — Modify**
- `services/frontend/src/main.tsx` — `RouterProvider`
- `services/frontend/src/App.tsx` — export current globe app for `/worldview`
- `services/frontend/src/index.css` — keep base resets + Cesium overrides + theme import
- `services/frontend/src/services/api.ts` — add landing/signal endpoints
- `services/frontend/package.json` — add `react-router-dom@7`

**Theme/Assets — Create**
- `services/frontend/src/theme/hlidskjalf.css`
- `services/frontend/public/fonts/instrument-serif/InstrumentSerif-Italic.woff2`
- `services/frontend/public/fonts/instrument-serif/InstrumentSerif-Italic-Bold.woff2`
- `services/frontend/public/fonts/hanken-grotesk/HankenGrotesk-Variable.woff2`
- `services/frontend/public/fonts/martian-mono/MartianMono-Variable.woff2`
- `services/frontend/public/fonts/README.md` — source and license provenance

**Backend — Create**
- `services/backend/app/models/signals.py`
- `services/backend/app/models/landing.py`
- `services/backend/app/services/signal_stream.py`
- `services/backend/app/routers/signals.py` — `/api/signals/stream`, `/api/signals/latest`
- `services/backend/app/routers/landing.py` — `/api/landing/summary`
- `services/backend/tests/unit/test_signals_stream.py`
- `services/backend/tests/unit/test_landing_summary.py`

**Backend — Modify**
- `services/backend/app/main.py` — include `signals` + `landing` routers at `/api`
- `services/backend/app/config.py` — stream and summary settings
- `services/backend/app/services/cache_service.py` — Redis stream read helpers if needed
- `services/backend/pyproject.toml` — add `python-ulid>=3.0.0`

---

## Task 0: Preflight checks (no feature code yet)

- [ ] **Step 1: Verify style-path convention**

Run:
```bash
cd /home/deadpool-ultra/ODIN/OSINT
ls services/frontend/src
```

If no existing `theme` convention exists, create `src/theme/` and document it in PR notes.

- [ ] **Step 2: Verify legacy query usage before migration code**

Run:
```bash
cd /home/deadpool-ultra/ODIN/OSINT
rg -n "useSearchParams|window\\.location\\.search|URLSearchParams" services/frontend/src
```

Record whether existing code already consumes `entity` / `layer` query params.

- [ ] **Step 3: Verify signal producer contract**

Run:
```bash
cd /home/deadpool-ultra/ODIN/OSINT
rg -n "xadd\\(|redis_stream_events|events:new" services/data-ingestion
```

Acceptance for this step:
- confirm at least one active collector path reaches an `XADD` write to `events:new` (directly or via `process_item`).
- if no active path is found, create a temporary dev-only publisher helper before Task 4 (`scripts/dev_publish_signal.py` or equivalent) and use that as producer for S1 testing.
- document deterministic local test injector command for S1 acceptance:
```bash
redis-cli XADD events:new * title "s1 smoke" codebook_type "signal.test" severity "low" source "manual" url "about:blank"
```

---

## Task 1: Router + AppShell (TDD first)

- [ ] **Step 1: Write failing routing tests (Red)**

`legacyRedirect.test.tsx` must fail first with assertions:
- `/?entity=sinjar` redirects to `/worldview?entity=sinjar`
- `/?layer=firmsHotspots` redirects to `/worldview?layer=firmsHotspots`
- `/` stays Landing
- AppShell/TopBar is persistent across route transitions

- [ ] **Step 2: Add router dependency (still Red if implementation missing)**

```bash
cd /home/deadpool-ultra/ODIN/OSINT/services/frontend
npm install react-router-dom@7
```

- [ ] **Step 3: Implement router + shell (Green)**

Implement routes:
- `/` -> Landing
- `/worldview` -> existing globe
- `/briefing` and `/briefing/:reportId` -> placeholder
- `/warroom` and `/warroom/:incidentId` -> placeholder

Placeholder minimum content (to avoid empty-route ambiguity):
- Briefing page center text: `§ Briefing · pending sprint 3`
- War Room page center text: `§ War Room · pending sprint 4`
- typography: Instrument Serif italic, color Stone, no additional interactive controls in S1

Migration rule:
- root loader handles `entity` / `layer` query migration to `/worldview`

- [ ] **Step 4: Run tests and refactor**

```bash
cd /home/deadpool-ultra/ODIN/OSINT/services/frontend
npx vitest run src/test/routing/legacyRedirect.test.tsx
```

---

## Task 2: Theme + Fonts baseline (TDD first)

- [ ] **Step 1: Write failing theme smoke test (Red)**

`hlidskjalfTheme.test.tsx` assertions:
- CSS variables exist (`--void`, `--obsidian`, `--amber`, ...)
- `.serif`, `.mono`, `.eyebrow` classes resolve to expected family names
- reduced-motion class behavior toggles as expected

- [ ] **Step 2: Implement theme + font assets (Green)**

Create `src/theme/hlidskjalf.css` with:
- palette tokens from spec 2.1
- `@font-face` with `font-display: swap`
- typography utilities and minimum-readable-size rules
- reduced-motion overrides

Add WOFF2 assets and `public/fonts/README.md`.

- [ ] **Step 3: Wire theme import and clean old tactical theme**

Keep only essential global/Cesium styles in `index.css`; import Hlidskjalf theme.

- [ ] **Step 4: Run test and refactor**

```bash
cd /home/deadpool-ultra/ODIN/OSINT/services/frontend
npx vitest run src/test/theme/hlidskjalfTheme.test.tsx
```

---

## Task 3: Orrery primitives (TDD first)

- [ ] **Step 1: Write failing Orrery tests (Red)**

`orrery.test.tsx`:
- static SVG structure snapshot
- reduced-motion renders deterministic static configuration
- multiple Orreries share one provider loop

- [ ] **Step 2: Implement `OrreryProvider` + `Orrery` + small primitives (Green)**

Requirements:
- one global rAF loop
- S/M/L sizes
- 3 independent orbiting bodies and depth transforms
- no Three.js

- [ ] **Step 3: Run tests and refactor**

```bash
cd /home/deadpool-ultra/ODIN/OSINT/services/frontend
npx vitest run src/test/hlidskjalf/orrery.test.tsx
```

---

## Task 4: Backend signals contract (TDD first)

- [ ] **Step 1: Write failing backend stream tests (Red)**

Create:
- `tests/unit/test_signals_stream.py`

Must fail initially with:
- replay by `Last-Event-ID` returns only `event_id > last`
- dedupe for duplicate IDs
- stale replay window returns `reset` event
- `/api/signals/latest?limit=6` returns latest in descending recency

- [ ] **Step 2: Add config + dependency**

In backend config:
- `redis_stream_events="events:new"`
- `signals_replay_window_seconds=900`
- `signals_poll_interval_ms=1000`
- `signals_ring_buffer_size=2000`

In `pyproject.toml`:
- `python-ulid>=3.0.0`

- [ ] **Step 3: Implement signal models/services/routers (Green)**

Implement event envelope:
- `event_id` (ULID)
- `ts`
- `type`
- `payload`

Required Redis-stream -> Envelope mapping contract in `signal_stream.py`:
- input record: Redis Stream entry `record_id` (`<ms>-<seq>`) + fields (`title`, `codebook_type`, `severity`, `source`, `url`, ...)
- `ts`: derived from `record_id` ms component (UTC ISO8601)
- `event_id`: ULID generated from the record timestamp with monotonic handling for same-ms records
- `type`: `fields.codebook_type` (fallback: `signal.unknown`)
- `payload`: `{ title, severity, source, url, redis_id: record_id, ...remaining fields }`
- `lastEventId` on SSE frames must always use envelope `event_id` (never raw Redis ID)

Implement endpoints:
- `GET /api/signals/stream` (SSE + replay + heartbeat + `reset`)
- `GET /api/signals/latest?limit=6` (**required**, not optional)

- [ ] **Step 4: Run tests and refactor**

```bash
cd /home/deadpool-ultra/ODIN/OSINT/services/backend
uv run pytest -q tests/unit/test_signals_stream.py
```

---

## Task 5: Landing numerals backend summary (TDD first)

- [ ] **Step 1: Write failing summary tests (Red)**

`tests/unit/test_landing_summary.py` assertions:
- endpoint returns all four metrics with source metadata
- respects `window=24h`
- `libri_24h` returns `0` and `reports_not_available_yet=true` in S1 when reports backend missing

- [ ] **Step 2: Implement `/api/landing/summary` (Green)**

Add endpoint:
- `GET /api/landing/summary?window=24h`

Response fields:
- `hotspots_24h`
- `conflict_24h`
- `nuntii_24h`
- `libri_24h`
- `reports_not_available_yet`

- [ ] **Step 3: Run tests and refactor**

```bash
cd /home/deadpool-ultra/ODIN/OSINT/services/backend
uv run pytest -q tests/unit/test_landing_summary.py
```

---

## Task 6: Landing wiring + feed hook (TDD first)

- [ ] **Step 1: Write failing frontend landing tests (Red)**

Create failing tests for:
- `useSignalFeed`: parse, dedupe, reconnect backoff
- Landing renders 4 numerals from `/api/landing/summary`
- Landing shows feed items immediately from `/api/signals/latest` before live SSE
- on SSE `reset` event: hook clears dedupe memory and re-hydrates from `/api/signals/latest`

- [ ] **Step 2: Implement API helpers + hook + Landing page (Green)**

Required FE data flow:
1. Fetch `/api/landing/summary?window=24h`
2. Fetch `/api/signals/latest?limit=6`
3. Connect SSE `/api/signals/stream` and merge updates idempotently
4. On SSE `reset` event: clear local event-id cache and re-fetch `/api/signals/latest?limit=6` before continuing live updates

Navigation behavior:
- numeral click -> `/worldview` with canonical query filter
- feed click -> `/worldview?entity=...` when entity present, else `/worldview`

- [ ] **Step 3: Run tests and refactor**

```bash
cd /home/deadpool-ultra/ODIN/OSINT/services/frontend
npx vitest run src/test/landing/signalFeed.test.tsx src/test/landing/landingSummary.test.tsx
```

---

## Task 7: TopBar details and S1-specific tab behavior (TDD first)

- [ ] **Step 1: Write failing TopBar tests (Red)**

Assertions:
- right side contains absolute UTC timestamp and coarse location text
- War Room tab dot in S1 is present but **not pulsing**
- reduced-motion keeps all tab indicators static

- [ ] **Step 2: Implement TopBar behavior (Green)**

S1 behavior:
- show timestamp + coarse location string (browser-derived if available, otherwise fallback string)
- War Room dot remains static in S1 (pulse deferred to S4 incident-state wiring)

- [ ] **Step 3: Run tests and refactor**

```bash
cd /home/deadpool-ultra/ODIN/OSINT/services/frontend
npx vitest run src/test/layout/topBar.test.tsx
```

---

## Task 8: Final verification and acceptance

- [ ] **Step 1: Frontend full checks**

```bash
cd /home/deadpool-ultra/ODIN/OSINT/services/frontend
npm run lint
npm run type-check
npx vitest run
```

- [ ] **Step 2: Backend full checks**

```bash
cd /home/deadpool-ultra/ODIN/OSINT/services/backend
uv run pytest -q tests/unit/test_signals_stream.py tests/unit/test_landing_summary.py
```

- [ ] **Step 3: Manual acceptance walk**

1. Open `/` -> Landing appears with populated numerals and initial feed rows.
2. Open `/worldview` -> existing globe behavior unchanged.
3. Inject one Redis event via `redis-cli XADD events:new ...` -> feed updates without reload.
4. Simulate stream interruption (choose one deterministic method):
   - Docker path: `cd /home/deadpool-ultra/ODIN/OSINT && docker compose stop backend && sleep 3 && docker compose start backend`
   - Browser path: DevTools -> Network -> Offline for ~5s, then Online
   Expected: `reconnecting` state appears and then recovers automatically.
5. Open `/?entity=foo` -> redirects to `/worldview?entity=foo`.

- [ ] **Step 4: Performance protocol (spec-aligned)**

Use Lighthouse or Chrome Performance profile:
- baseline run: camera rotation on worldview without GrainOverlay
- comparison run: same scenario with GrainOverlay enabled
- acceptance target: **>= 55 FPS** during rotation, no material regression vs baseline

Verify fonts load from local assets with cold cache:
- target: all three families loaded locally, no third-party font requests

---

## Suggested commit slices

1. `test(frontend): add failing routing and shell tests`
2. `feat(frontend): add router v7 app shell and legacy redirect`
3. `test(frontend): add failing theme and orrery tests`
4. `feat(frontend): add hlidskjalf theme fonts and shared primitives`
5. `test(backend): add failing signals stream and landing summary tests`
6. `feat(backend): add /api/signals and /api/landing summary contracts`
7. `test(frontend): add failing landing feed and topbar tests`
8. `feat(frontend): wire landing numerals feed and topbar details`

---

## Risks and mitigations

- **Risk:** stream quiet periods cause empty feed perception on first load.  
  **Mitigation:** required `/api/signals/latest` hydration + explicit live/reconnecting status line.

- **Risk:** producer path drifts in ingestion changes.  
  **Mitigation:** keep preflight grep + manual `XADD` smoke in S1 acceptance checklist.

- **Risk:** font licensing uncertainty.  
  **Mitigation:** `public/fonts/README.md` required before merge.

- **Risk:** animation overhead from multiple Orreries.  
  **Mitigation:** singleton provider test and reduced-motion fallback.
