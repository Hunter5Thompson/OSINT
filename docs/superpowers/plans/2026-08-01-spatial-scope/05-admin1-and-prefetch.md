# Spatial Scope 05 — Admin-1 and Prefetch

> **Canonical slice:** 5 · **Requires:** Plan 03
>
> **Load with:** [Spec 04 §10.5/§10.9](../../specs/2026-07-31-spatial-scope-drilldown/04-spatial-catalog-contracts.md),
> [Spec 05 §11.3–11.4](../../specs/2026-07-31-spatial-scope-drilldown/05-boundary-build-and-antimeridian.md),
> [Spec 06 §12.5–12.9](../../specs/2026-07-31-spatial-scope-drilldown/06-cesium-and-layer-semantics.md),
> [Spec 13 Slice 5](../../specs/2026-07-31-spatial-scope-drilldown/13-implementation-and-tdd-slices.md).

## Outcome and seam

Extend the proven country path to catalog-plan-selected Admin-1 children. Hover may
warm the same ref-counted catalog/asset load later adopted by click, but cannot mutate
semantic state, URL, camera, or foreground generation. A direct Admin-1 deep link
resolves without prior parent navigation.

> **Commit record (2026-08-07):** The four work-order checkpoints were consolidated
> after the full independent exit-gate review in baseline commit `6a929a3`.

## File surface

Extend the Slice-0 catalog plan/assets and existing builder fixtures. Modify frontend
`scopeController.ts`, `catalog.ts`, `CesiumSpatialScopeAdapter.ts`,
`resolveWorldviewPick.ts`, and their tests. Add no second cache or hover-specific HTTP
client.

## Work order 1 — Selected-theater Admin-1 artifacts

- [x] **RED:** For each V1 theater, test complete direct-child membership, canonical
  lineage, valid preferred child LOD, parent dissolve/provenance, strict containment,
  budget descriptors, and deep resolution from the root manifest. A country disabled
  by plan must expose `children_available=false` and no child asset.
- [x] **GREEN:** Add only approved gbOpen releases/records to source lock and catalog
  plan, then rebuild the immutable catalog. Produce selected Admin-1 bundles and
  updated audit/feasibility reports using the existing compiler.
- [x] **REFACTOR:** Theater coverage remains declarative in `catalog-plan.json`; no
  country list enters frontend/backend code.
- [x] **VERIFY:** Run the full spatial-catalog suite and byte-identical double build.
- [x] **COMMIT:** `data(spatial-catalog): add selected admin1 theaters`

## Work order 2 — Prefetch scheduler and shared leases

- [x] **RED:** With fake time/network, test 200 ms dwell, leave-before/after-start,
  maximum concurrency two, queue replacement, click adoption without duplicate HTTP,
  hover cancellation while click lease remains, LRU eviction, active-lease immunity,
  exact cache budgets (256 metadata entries; 8 decoded bundles/64 MiB), and no
  state/URL/camera publication.
- [x] **GREEN:** Add a bounded scheduler over the existing catalog store. `prefetch`
  gets no foreground intent/commit rights and releases its lease after validated
  decode; click adopts the shared in-flight load by reference count.
- [x] **REFACTOR:** Keep scheduling separate from cache ownership. Aborts remove only
  that consumer and never cancel another live lease.
- [x] **VERIFY:** Run controller/catalog tests with fake timers; no real sleeps.
- [x] **COMMIT:** `feat(frontend): prefetch spatial children with bounded leases`

## Work order 3 — Admin-1 picking, drill and direct links

- [x] **RED:** Test country→Admin-1 click, sibling jump, breadcrumb/ascend, canonical
  child pick ID, direct Admin-1 deep link, unavailable child geometry, stale generation,
  blank click, and camera LOD invariance. Assert the query token changes only after
  URL echo and successful resolve.
- [x] **GREEN:** Reuse the existing preferred-LOD pick surface and dispatch
  `enter(child.scopeKey, "child-click")`. Build outline/children primitives from the
  resolved Admin-1 bundle; fit camera from its extent; show no affordance where the
  catalog says children unavailable.
- [x] **REFACTOR:** Country and Admin-1 use one adapter path parameterized by validated
  bundle descriptors—no `if country === ...` theater code.
- [x] **VERIFY:** Run Cesium adapter, pick, controller, router, and page tests.
- [x] **COMMIT:** `feat(worldview): drill into catalog admin1 scopes`

## Work order 4 — Input capability and soak gates

- [x] **RED:** Test hover prefetch disabled for touch/coarse pointer and
  `saveData=true`; reduced motion changes camera duration only; cache/primitive/
  listener counters return to baseline after long synthetic navigation.
- [x] **GREEN:** Bind pointer dwell only when capability policy permits. Add the
  Spec-12 prefetch/cache/primitive metrics and run the Slice-5 canary/default-on
  acceptance scenario.
- [x] **REFACTOR:** Capability detection is injectable and testable; it does not enter
  semantic scope state.
- [x] **VERIFY:** Run frontend full quality commands and record the real Cesium soak,
  catalog audit, cache high-water, cached commit under 50 ms, cold local p95 under
  800 ms, no task over 50 ms, and no-growth evidence.
- [x] **COMMIT:** `test(worldview): gate admin1 prefetch and soak`

## Exit gate

Selected Admin-1 scopes work by click and direct link, with complete lineage and no
runtime data fetch outside ODIN. Prefetch stays side-effect free and bounded. Catalog,
GPU, decoded-cache, and listener budgets pass. This permits Phase C/default-on review;
it does not itself authorize legacy deletion—that is Plan 05D.
