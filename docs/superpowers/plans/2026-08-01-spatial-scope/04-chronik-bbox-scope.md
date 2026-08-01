# Spatial Scope 04 — CHRONIK BBox Scope

> **Canonical slice:** 4 · **Requires:** Plans 02 and 03
>
> **Load with:** [Spec 07](../../specs/2026-07-31-spatial-scope-drilldown/07-chronik-query-contract.md),
> [Spec 04 §10.8](../../specs/2026-07-31-spatial-scope-drilldown/04-spatial-catalog-contracts.md),
> [Spec 12](../../specs/2026-07-31-spatial-scope-drilldown/12-errors-security-and-observability.md),
> [Spec 13 Slice 4](../../specs/2026-07-31-spatial-scope-drilldown/13-implementation-and-tdd-slices.md).

## Outcome and seam

Bind CHRONIK's time window to the committed `SpatialQueryRef` while truthfully
labeling the first implementation `bbox_approximate`. The backend—not the browser—
projects catalog extents to one/two bbox branches. Hooks never show data whose echoed
scope/revision/generation differs from current props, even for the first render before
effects run.

## File surface

Backend: create `app/services/spatial_filters.py`; modify timeline models/router and
tests. Frontend: modify `types/index.ts`, `services/api.ts`, `useTimeWindow.ts`,
`useTimeHistogram.ts`, `ScrubberMount.tsx`, and their tests; create
`src/spatial/layerScopePolicy.ts` and its focused test. Preserve the legacy bbox
request as a mutually exclusive AOI mode.

## Work order 1 — Request/response contract

- [ ] **RED:** Model tests cover structured scope, `scope_key + bbox` 422, invalid
  revision, a new-client world token versus a legacy tokenless global request, echoed
  query reference, relation, mode,
  completeness, distinct included count, excluded counts, and unknown enum/schema.
- [ ] **GREEN:** Implement the Spec-07 models including `SpatialApplicationV1`.
  Define `included_count` as distinct top-level records before sample limit and keep
  `samples.length` separate.
- [ ] **REFACTOR:** Import the shared conceptual symbols; do not redeclare a second
  `SpatialQueryRef` normative shape in timeline code.
- [ ] **VERIFY:** Run `test_timeline_models.py` and `test_timeline_params.py`.
- [ ] **COMMIT:** `feat(backend): define scoped timeline contract`

## Work order 2 — Catalog extent compiler

- [ ] **RED:** Test server-side resolution, active/previous revision pinning,
  world/unscoped behavior, Fiji two-span projection, polar full longitude, invalid
  extent, event `occurs-in` versus movement `intersects`, parameter binding, and no
  global fallback on catalog failure.
- [ ] **GREEN:** Implement a static bbox compiler in `spatial_filters.py`; it returns
  fixed query IDs plus parameter dictionaries, never dynamic property names or raw
  Cypher fragments. Wire event/histogram/movement handlers to resolve through the
  loader and return `bbox_approximate + partial` accounting.
- [ ] **REFACTOR:** Keep current timeline query shapes and movement semantics. One
  extent adapter owns conversion from `GeoExtent` to the legacy Neo4j bbox convention.
- [ ] **VERIFY:** Run timeline router/histogram and new spatial-filter unit tests.
- [ ] **COMMIT:** `feat(backend): scope chronik through catalog extents`

## Work order 3 — Frontend API and stale envelope guards

- [ ] **RED:** Hook tests cover A→B immediate hide, first B render rejecting stored A
  before an effect, late A response, echoed token mismatch, abort, backend failure,
  and no fallback request without scope. Preserve timeline cursor/range/mode/speed
  across scope; preserve scope across seek.
- [ ] **GREEN:** Send `SpatialQueryRef` with window/histogram calls and store a typed
  response envelope. Derive visible data synchronously from current props plus echoed
  token/generation; reset loading/error explicitly rather than silently retaining old
  data.
- [ ] **REFACTOR:** Share one token-equality helper and request-generation pattern
  between both hooks. Do not copy catalog bounds into frontend types.
- [ ] **VERIFY:** Run both hook suites and `ScrubberMount` tests.
- [ ] **COMMIT:** `feat(frontend): bind chronik requests to spatial scope`

## Work order 4 — Honest UX and observability

- [ ] **RED:** Test the scrubber badge/text for global, loading, partial
  `bbox_approximate`, unavailable, and differing movement relation. Ensure stale data
  cannot remain visible under a new breadcrumb.
- [ ] **GREEN:** Surface application mode/completeness/excluded counts compactly and
  emit request/reject/latency metrics with scope kind/revision—not raw user content.
  Seed `layerScopePolicy.ts` with the Spec-06 initial capability matrix so global
  context, unsupported, approximate and strict layers cannot share a misleading UI.
- [ ] **REFACTOR:** Keep precision labels response-driven; the UI never infers exactness
  from the presence of a scope key.
- [ ] **VERIFY:** Run full backend and frontend quality commands.
- [ ] **COMMIT:** `feat(worldview): expose chronik spatial precision`

## Exit gate

Every non-global CHRONIK request is server-resolved and fail-closed. Dateline scopes
use the correct static branches. A breadcrumb can never coexist visibly with an old
scope's samples/histogram. The response explicitly says approximation, relation, and
coverage; semantic-key activation remains disabled until Plan 06B.
