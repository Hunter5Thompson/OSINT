# Spatial Scope 03 — Cesium Country Migration

> **Status:** IN PROGRESS (2026-08-06) · **Canonical slice:** 3 · **Requires:** Plans 01 and 02
>
> **Load with:** [Spec 06 §§12–13](../../specs/2026-07-31-spatial-scope-drilldown/06-cesium-and-layer-semantics.md),
> [Spec 11 §18](../../specs/2026-07-31-spatial-scope-drilldown/11-ux-and-3d-metrics.md),
> [Spec 14 §26](../../specs/2026-07-31-spatial-scope-drilldown/14-rollout-and-acceptance.md),
> [Spec 13 Slice 3](../../specs/2026-07-31-spatial-scope-drilldown/13-implementation-and-tdd-slices.md).

## Outcome and seam

Make the committed semantic scope drive one batched Cesium presenter, deterministic
catalog picking, breadcrumb, camera fit, and canonical country almanac lookup. During
Phases B/C the composition root mounts exactly one country path: flag-off legacy or
flag-on spatial. Selection and scope remain distinct states.

Before the first red test, revalidate the frontend facts in Spec 01 §3.1 if relevant
WorldView work landed after the 2026-08-01 review. Any changed seam is reconciled in
the owning spec/plan before implementation; it is not silently adapted in Cesium code.

## File surface

Create `src/spatial/geometry.ts` and `src/spatial/cesium/{CesiumSpatialScopeAdapter.ts,buildScopePrimitives.ts,resolveWorldviewPick.ts}`
with focused tests. Modify `WorldviewPage`, `EntityClickHandler`, Spotlight files,
`CountryBorders`, `LayersPanel`, Inspector/CountryHeader, and backend
`routers/almanac.py`. Move pure point-in-polygon fixtures from the legacy hook to
`spatial/__tests__/geometry.test.ts`.

## Work order 1 — Geometry and pick contract

- [x] **RED:** Test holes, multipolygons, dateline unwrapping, duplicate RBush spans,
  boundary-uncertain, operational primitive over child surface, child over terrain,
  blank click, stale generation, and catalog IDs including Kosovo (never XKX). Add the
  deliberately divergent overview/regional fixture and pin expected pick to
  `childrenLods[preferredLod]` before/after camera LOD change. Fixed containment
  points must also return the same result through every camera LOD swap. Assert one
  `drillPick(position, 16)` per frame and a saturation metric at exactly 16 hits.
- [x] **GREEN:** Move/harden geometry helpers; implement tagged primitive pick
  resolution. Pick surfaces are built once per `stateRevision` from the preferred
  child asset and are never reindexed by camera movement.
- [x] **REFACTOR:** `_topoIndex`, labels, and local ISO maps are absent from all spatial
  imports. Camera LOD applies only to non-pickable render geometry.
- [x] **VERIFY:** Run `geometry.test.ts` and `resolveWorldviewPick.test.ts`.
- [x] **COMMIT:** `feat(frontend): resolve deterministic spatial picks`

## Work order 2 — Generation-safe Cesium presenter

- [x] **RED:** Test build→ready swap, old-container visibility until semantic commit,
  stale build disposal, presentation failure without semantic rollback, reduced-motion
  zero flight, dateline camera fit, listener removal, and constant primitive/container
  counts across 100 synthetic transitions and LOD swaps. CPU conversion yields after
  8,000 vertices or 8 ms, rechecks abort after each frame, and never leaves a main-
  thread task above the 50 ms release gate.
- [x] **GREEN:** Implement chunked primitive construction in per-revision
  `PrimitiveCollection`s, using batched geometry/appearance rather than Entity API.
  Abort/dispose by generation; release asset leases after readiness; derive camera
  bounds from Cartesian points. Report visual state only for the matching revision.
- [x] **REFACTOR:** Keep Cesium types inside `spatial/cesium`. Controller sees one
  presentation port and never camera state.
- [x] **VERIFY:** `cd services/frontend && npm test -- src/spatial/__tests__/cesiumAdapter.test.ts`
- [x] **COMMIT:** `feat(frontend): present spatial scope with cesium primitives`

## Work order 3 — Mutually exclusive migration and UX

- [x] **RED:** Test flag-off only Legacy and flag-on only Spatial; never two renderers
  or click handlers, and a Legacy hit has no Spatial dispatch access. Test country
  click dispatches both scope and separate selection, failed resolve changes neither,
  scope commit clears unverified operational selection, blank click preserves scope,
  search/pin keeps Circle Spotlight unless an explicit “open area” action commits,
  breadcrumb/ascend, pending truth, and exactly one
  priority-ordered Escape action. An old `SelectionEnvelope` is hidden on the first
  render of a new `stateRevision`. Breadcrumb tests cover semantic nav, `aria-current`,
  keyboard activation and focus retention.
- [x] **GREEN:** Wire the adapter through a viewer bridge within the provider. Keep
  `CountryTarget` writable/renderable only in the legacy branch; Circle Spotlight
  remains shared. Add revision-tagged selection, accessible breadcrumb and scope
  error/pending presentation without moving state into `WorldviewPage`. Treat
  `VITE_SPATIAL_SCOPE_ENABLED` strictly as build-time configuration.
- [x] **REFACTOR:** Centralize Escape arbitration and primitive ownership. Do not
  delete legacy files or the build flag before Plan 05D.
- [x] **VERIFY:** Run spatial, Spotlight, page, and StrictMode suites.
- [x] **COMMIT:** `feat(frontend): enable flagged country scope drilldown`

## Work order 4 — Canonical almanac adapter and canary evidence

- [x] **RED:** Backend tests resolve `scope_key + catalog_revision` before existing
  almanac lookup, reject invalid/unserved keys, support reviewed legacy aliases, and
  never alter scope on missing dossier. Frontend tests ignore stale almanac responses.
- [x] **GREEN:** Add `/api/almanac/country?scope_key=&catalog_revision=` as a thin
  catalog-to-`CountryAlmanacStore` adapter. Change Inspector/Header to request only
  from the committed query token.
- [x] **REFACTOR:** Almanac supplies display/capital data but never identity.
- [x] **VERIFY:** Run focused backend almanac tests; frontend full quality commands;
  then capture a flag-on canary run with primitive/listener/cache counters.
- [x] **COMMIT:** `feat(worldview): load almanac by canonical scope`

## Work order 5 — Cartographic provenance

- [x] **RED:** Test an accessible Layers-panel link renders the active boundary policy,
  catalog revision, exact source releases, representation/dispute note and all
  reviewed attributions as text. Reject stale/malformed attribution, external author
  handles, and every `dangerouslySetInnerHTML` path.
- [x] **GREEN:** Load `attribution.json` through the validated catalog metadata and add
  the matching committed catalog revision's compact Data/Boundary-policy view to the
  existing Cartography section. It is presentation-only and cannot alter identity or
  scope.
- [x] **REFACTOR:** Reuse existing Hlíðskjalf typography/theme tokens; no copied HUD or
  hard-coded external-template styling.
- [x] **VERIFY:** Run Layers-panel accessibility tests and frontend full quality
  commands.
- [x] **COMMIT:** `feat(worldview): expose boundary provenance and attribution`

## Exit gate

The same point resolves the same catalog child at every camera LOD; exactly one
country path is mounted; all primitive/lease/listener lifetimes are bounded; and
presenter or almanac failure cannot roll back/relabel semantic scope. Production may
remain default-off while the separate flag-on artifact begins its canary.
