# Photorealistic 3D Tiles Loading-Performance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate the constant 3D-tile loading sluggishness by replacing the over-aggressive `maximumScreenSpaceError = 2` with a balanced value and a larger tile cache, encapsulated in a testable config module.

**Architecture:** A new, runtime-Cesium-free module `tilesetConfig.ts` exports the two real tuning values (`maximumScreenSpaceError: 8`, `cacheBytes: 1 GiB`) and an `applyTilesetPerformanceConfig(tileset)` function. `GlobeViewer.tsx`'s shared tileset handler (`addBuildingsTileset`, used for both the Google photoreal tileset and the OSM-buildings fallback) calls this function instead of setting the SSE inline.

**Tech Stack:** React 19 + TypeScript + Vite 6 + CesiumJS (package range `^1.132.0`, locally 1.139.1), Vitest.

## Global Constraints

- Cesium package range `^1.132.0`; behaviour verified against locally installed **1.139.1**.
- No `any` types in TypeScript — always typed (project rule).
- TDD mandatory: failing test first, then minimal implementation.
- Existing frontend tests must stay green (VS Code Test-Panel must not break).
- Conventional commit messages (`feat(...)`, `refactor(...)`, etc.).
- Do NOT set properties that already equal the Cesium 1.139.1 defaults (no dead tuning code): `dynamicScreenSpaceError*`, `cullRequestsWhileMoving`, `maximumCacheOverflowBytes`, `RequestScheduler.maximumRequestsPerServer` are all out of scope.
- Do NOT touch `src/components/globe/GoogleTiles.tsx` (inactive legacy path, not part of this change).

---

### Task 1: `tilesetConfig` module + unit test

**Files:**
- Create: `services/frontend/src/components/globe/tilesetConfig.ts`
- Test: `services/frontend/src/components/globe/tilesetConfig.test.ts`

**Interfaces:**
- Consumes: nothing (leaf module).
- Produces:
  - `PHOTOREAL_TUNING` — `{ readonly maximumScreenSpaceError: number; readonly cacheBytes: number }` (values `8` and `1073741824`).
  - `applyTilesetPerformanceConfig(tileset: Cesium.Cesium3DTileset): void` — sets `tileset.maximumScreenSpaceError` and `tileset.cacheBytes` from `PHOTOREAL_TUNING`.

- [ ] **Step 1: Write the failing test**

Create `services/frontend/src/components/globe/tilesetConfig.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import type * as Cesium from "cesium";
import { applyTilesetPerformanceConfig, PHOTOREAL_TUNING } from "./tilesetConfig";

describe("applyTilesetPerformanceConfig", () => {
  it("sets maximumScreenSpaceError and cacheBytes from PHOTOREAL_TUNING", () => {
    // Minimal stub — type-only Cesium import means no WebGL/runtime is loaded.
    const tileset = {
      maximumScreenSpaceError: 0,
      cacheBytes: 0,
    } as unknown as Cesium.Cesium3DTileset;

    applyTilesetPerformanceConfig(tileset);

    expect(tileset.maximumScreenSpaceError).toBe(8);
    expect(tileset.maximumScreenSpaceError).toBe(PHOTOREAL_TUNING.maximumScreenSpaceError);
    expect(tileset.cacheBytes).toBe(1024 * 1024 * 1024);
    expect(tileset.cacheBytes).toBe(PHOTOREAL_TUNING.cacheBytes);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/frontend && npm run test -- src/components/globe/tilesetConfig.test.ts`
Expected: FAIL — cannot resolve `./tilesetConfig` (module does not exist yet).

- [ ] **Step 3: Write minimal implementation**

Create `services/frontend/src/components/globe/tilesetConfig.ts`:

```ts
import type * as Cesium from "cesium";

/**
 * Stage-1 photoreal-tiles performance tuning — the ONLY two values that differ
 * from the Cesium 1.139.1 defaults. See
 * docs/superpowers/specs/2026-06-18-photoreal-tiles-loading-perf-design.md.
 *
 * - maximumScreenSpaceError: 8 (Cesium default 16; the old code used 2, which
 *   demanded ~8x finer tiles everywhere → constant loading sluggishness).
 * - cacheBytes: 1 GiB (Cesium default 512 MiB; reduces re-downloads when
 *   panning back to a previously visited area).
 */
export const PHOTOREAL_TUNING = {
  maximumScreenSpaceError: 8,
  cacheBytes: 1024 * 1024 * 1024, // 1 GiB
} as const;

/**
 * Apply the Stage-1 tuning to a 3D tileset. Tileset-type-neutral: used for both
 * the Google photoreal tileset and the OSM-buildings fallback.
 */
export function applyTilesetPerformanceConfig(tileset: Cesium.Cesium3DTileset): void {
  tileset.maximumScreenSpaceError = PHOTOREAL_TUNING.maximumScreenSpaceError;
  tileset.cacheBytes = PHOTOREAL_TUNING.cacheBytes;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/frontend && npm run test -- src/components/globe/tilesetConfig.test.ts`
Expected: PASS (1 test).

- [ ] **Step 5: Type-check the new module**

Run: `cd services/frontend && npm run type-check`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add services/frontend/src/components/globe/tilesetConfig.ts services/frontend/src/components/globe/tilesetConfig.test.ts
git commit -m "feat(globe): add tilesetConfig with balanced photoreal tuning (SSE 8, 1GiB cache)"
```

---

### Task 2: Wire `applyTilesetPerformanceConfig` into `GlobeViewer`

**Files:**
- Modify: `services/frontend/src/components/globe/GlobeViewer.tsx` (import at top; line 79 inside `addBuildingsTileset`)

**Interfaces:**
- Consumes: `applyTilesetPerformanceConfig` from `./tilesetConfig` (Task 1).
- Produces: nothing new (behavioural change only).

- [ ] **Step 1: Add the import**

In `services/frontend/src/components/globe/GlobeViewer.tsx`, after the existing
`import { applyCRTShader, ... } from "../shaders/shaderUtils";` line (line 5), add:

```ts
import { applyTilesetPerformanceConfig } from "./tilesetConfig";
```

- [ ] **Step 2: Replace the inline SSE assignment**

In the `addBuildingsTileset` handler (around line 79), replace:

```ts
      tileset.maximumScreenSpaceError = 2;
```

with:

```ts
      applyTilesetPerformanceConfig(tileset);
```

(Leave the surrounding lines — `tileset.show = ...`, `_odinPhotoreal`, `primitives.add`, refs — unchanged.)

- [ ] **Step 3: Type-check**

Run: `cd services/frontend && npm run type-check`
Expected: no errors.

- [ ] **Step 4: Lint**

Run: `cd services/frontend && npm run lint`
Expected: no errors.

- [ ] **Step 5: Run the full test suite (no regressions)**

Run: `cd services/frontend && npm run test`
Expected: all tests pass, including the new `tilesetConfig.test.ts`.

- [ ] **Step 6: Commit**

```bash
git add services/frontend/src/components/globe/GlobeViewer.tsx
git commit -m "refactor(globe): apply tilesetConfig tuning instead of inline SSE=2"
```

---

### Task 3: Manual before/after measurement (operator step)

> Not automatable — this is the honest proof the change worked. Run after Task 2 builds. Record results in the commit/PR description or session notes.

**Files:** none.

- [ ] **Step 1: Build and serve the frontend**

Run: `cd services/frontend && npm run build && npm run preview`
(Or `npm run dev` for the dev server.) Open the app in a browser with the Network tab open, filtered to the Google tile host.

- [ ] **Step 2: Capture the two scenarios**

For each of (a) the default Europe overview (15°E/45°N, 15,000 km) and (b) a zoom-in onto a city, note: number of tile requests until the view settles, and the subjective time until "sharp enough".

- [ ] **Step 3: Sanity-check the outcome**

Expected: noticeably fewer tile requests and faster settle vs. the old SSE=2 behaviour, without visibly missing detail at typical viewing height. If a city looks too soft up close, the first knob back is `PHOTOREAL_TUNING.maximumScreenSpaceError` toward 4–6 (in `tilesetConfig.ts`). If still sluggish, evaluate Stage 2 (`skipLevelOfDetail`) per the spec.

---

## Self-Review

**Spec coverage:**
- Root cause (SSE=2) → Task 2 replaces it. ✓
- `tilesetConfig.ts` module with `PHOTOREAL_TUNING` + `applyTilesetPerformanceConfig` → Task 1. ✓
- Two real levers only (SSE 8, cacheBytes 1 GiB), no no-op defaults → Task 1 implementation + Global Constraints. ✓
- Integration in shared `addBuildingsTileset` handler → Task 2. ✓
- TDD test → Task 1. ✓
- Measurement protocol (Europe overview + city zoom) → Task 3. ✓
- Stage 2 documented-only, not built → absent from plan by design; referenced in Task 3 sanity-check. ✓
- `GoogleTiles.tsx` untouched → Global Constraints. ✓

**Placeholder scan:** No TBD/TODO/"handle edge cases"; all code blocks complete. ✓

**Type consistency:** `applyTilesetPerformanceConfig` / `PHOTOREAL_TUNING` names and signatures identical across Task 1 (definition), Task 1 test, and Task 2 (usage). `cacheBytes` value `1024*1024*1024` consistent with `PHOTOREAL_TUNING`. ✓
