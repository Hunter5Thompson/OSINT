# Bugfix Log (Agent Handover)

Updated: 2026-03-05

This document captures concrete bugs found during repository analysis and the implemented fixes, so follow-up agents can continue without re-discovery.

## Scope

- Backend (`services/backend`)
- Data ingestion (`services/data-ingestion`)
- Frontend (`services/frontend`)
- Repo hygiene (`.gitignore`)

## Fixes Applied

1. Flight military flag detection was incorrect.
- Symptom: military aircraft were under-detected for ADS-B records with multiple `dbFlags` bits set.
- Root cause: exact comparison `dbFlags == 1`.
- Fix: switched to bitmask parsing and evaluation (`bool(db_flags & 1)`), with defensive int conversion.
- File: `services/backend/app/services/flight_service.py`

2. Hotspot ingestion and backend API were not aligned.
- Symptom: backend returned static/default hotspots instead of ingestion-updated data.
- Root cause: ingestion wrote `hotspot:index`/`hotspot:{id}`, while backend read `hotspots:all`.
- Fix: ingestion now also writes `hotspots:all`; backend now supports both cache formats.
- Files:
  - `services/data-ingestion/feeds/hotspot_updater.py`
  - `services/backend/app/routers/hotspots.py`

3. Hotspot schema mismatch between services.
- Symptom: potential runtime validation errors when consuming ingestion data.
- Root cause: ingestion used `lat/lon`, lowercase threat levels, `updated_at`; backend model expects `latitude/longitude`, uppercase enum, `last_updated`.
- Fix: normalization added in backend hotspot router; ingestion writes normalized records to `hotspots:all`.
- Files:
  - `services/backend/app/routers/hotspots.py`
  - `services/data-ingestion/feeds/hotspot_updater.py`

4. Hotspot mention counting logic was too strict.
- Symptom: mention counts were near zero and threat adjustments skewed.
- Root cause: exact value matching on title text.
- Fix: moved to text matching with `MatchText`.
- File: `services/data-ingestion/feeds/hotspot_updater.py`

5. Frontend vessel layer mostly stayed empty.
- Symptom: `vessels` layer often displayed no data.
- Root cause: frontend used REST polling (`/api/v1/vessels`) but cache population happens in vessel websocket flow.
- Fix: frontend now consumes `/ws/vessels` via `WebSocketManager` and tracks freshness timestamp.
- File: `services/frontend/src/App.tsx`

6. Frontend type-check/build failed due to nullable Cesium API.
- Symptom: `TS18048` on `viewer.scene.skyAtmosphere`.
- Root cause: property can be undefined in Cesium type definitions.
- Fix: null guard before assigning `brightnessShift`.
- File: `services/frontend/src/components/globe/GlobeViewer.tsx`

7. Data-ingestion test suite expected at least 50 hotspots.
- Symptom: `TestHotspots.test_minimum_hotspot_count` failed (49 entries).
- Fix: added one curated hotspot (`western-sahara`) to restore threshold.
- File: `services/data-ingestion/feeds/hotspot_updater.py`

8. Frontend lint command failed with ESLint v9.
- Symptom: `eslint.config.(js|mjs|cjs)` missing.
- Root cause: project had ESLint 9 script but no flat config.
- Fix: added flat config and TypeScript ESLint dependencies.
- Files:
  - `services/frontend/eslint.config.js`
  - `services/frontend/package.json`

9. Local build/test artifacts were polluting git status.
- Symptom: frequent untracked noise (`__pycache__`, `.venv`, `node_modules`, lock/build files).
- Fix: added repo-level `.gitignore`.
- File: `.gitignore`

## Validation Snapshot

Executed in local environment without Ollama/vLLM runtime dependencies:

- Backend tests: `8 passed`
- Data-ingestion tests: `34 passed`
- Intelligence tests: `2 passed`
- Frontend:
  - `npm run type-check`: pass
  - `npm run build`: pass
  - `npm run lint`: pass

## Known Remaining Notes

1. Backend tests still emit deprecation warnings for `datetime.utcnow()` usage in models.
- Current status: warning only, not failing tests.
- Impact: low now, should be migrated to timezone-aware UTC timestamps later.

2. This validation did not exercise live LLM inference (Ollama/vLLM not installed in this environment).
- Impact: integration behavior for intelligence runtime still requires target-system validation.
