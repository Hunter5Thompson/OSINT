# Spatial Scope 08 — Additional Layers, Admin-2 and 3D

> **Canonical slice:** 8 · **Start gate:** V1 performance and truthfulness accepted
>
> **Load with:** [Spec 06 §13](../../specs/2026-07-31-spatial-scope-drilldown/06-cesium-and-layer-semantics.md),
> [Spec 11 §19](../../specs/2026-07-31-spatial-scope-drilldown/11-ux-and-3d-metrics.md),
> [Spec 12](../../specs/2026-07-31-spatial-scope-drilldown/12-errors-security-and-observability.md),
> [Spec 14 §27/§29](../../specs/2026-07-31-spatial-scope-drilldown/14-rollout-and-acceptance.md).

## Outcome and seam

Expand only capabilities justified by V1 evidence: registered layer semantics,
selected Admin-2 depth within proven pack budgets, and at most one data-driven 3D
metric adapter. These are three independently activatable work orders; none is a
license to decorate the globe. Each activation declares relation, precision,
coverage, time basis and fail-closed behavior.

## Mandatory start record

- [ ] Attach Slice 3–7 performance/soak, catalog, Neo4j and Qdrant coverage evidence.
- [ ] Inventory every candidate layer and select only those with an authoritative
  spatial relation and generation-safe invalidation seam.
- [ ] Select Admin-2 theaters through a reviewed catalog-plan change and prove raw
  feature/ring/cardinality feasibility before implementation.
- [ ] Select one 3D metric only if it has a unit, time basis, defensible scale,
  missing-value semantics, legend, and analyst use case. Otherwise mark 3D deferred
  and complete only layer/Admin-2 work.

Any failed item stops that branch without blocking unrelated accepted branches.

## Work order 1 — Layer capability registry and point adapter

- [ ] **RED:** Add a closed capability-matrix test for every enabled layer: relation,
  mode, precision, stale policy and unsupported behavior. For the first strict point
  layer, test old containment index invalidates at semantic commit before first new
  render, building/unavailable hides old results, inside/outside/boundary-uncertain
  counts, world behavior, and camera LOD independence.
- [ ] **GREEN:** Implement/extend `layerScopePolicy.ts` and one imperative point-layer
  adapter over `SpatialContainmentPort`. Use `BillboardCollection` for bulk points and
  filter outside React render; do not write containment results back to semantic data.
- [ ] **REFACTOR:** The registry owns claims; layer components cannot self-label an
  approximation exact.
- [ ] **VERIFY:** Focused layer tests plus a high-cardinality frame/memory benchmark.
- [ ] **COMMIT:** `feat(worldview): scope registered point layers`

## Work order 2 — Track/polygon/raster semantics

- [ ] **RED:** For each selected layer, encode its actual relation: track intersection
  preserves all original track points (no misleading clipping), polygons declare
  intersects/contained/unsupported, raster/global reference layers remain explicitly
  unfiltered or unavailable. Test stale generation and response accounting.
- [ ] **GREEN:** Add one adapter at a time using existing bulk Cesium primitives and
  the capability registry. Server-side filters use static allowlisted compilers;
  client approximations carry their mode/completeness.
- [ ] **REFACTOR:** Shared generation guards are reused; geometry relation logic stays
  layer-specific where semantics differ.
- [ ] **VERIFY:** Per-layer truthfulness fixtures, backend query-plan smoke, then full
  frontend/backend quality commands.
- [ ] **COMMIT:** `feat(worldview): add truthful scoped layer adapters`

## Work order 3 — Selected Admin-2 drilldown

- [ ] **RED:** Extend build tests for canonical lineage, complete child set, preferred
  pick LOD, containment, post-expansion feature/wire/heap/ring/vertex/error budgets,
  direct deep link, picking invariance, cache/primitive high water, and disabled
  affordance outside selected theaters. A >256 pack must fail—not page implicitly.
- [ ] **GREEN:** Add reviewed Admin-2 sources/coverage to lock and catalog plan, rebuild
  artifacts, and reuse the generic core/backend/Cesium path. Materialize/query Admin-2
  only where its Plan-06/07 coverage gate is independently met.
- [ ] **REFACTOR:** No Admin-2 special case in controller or picker. If tiling is
  required, stop and design a separate versioned contract before continuing.
- [ ] **VERIFY:** Double-build/audit, direct-link and Cesium soak, Neo4j/Qdrant plans
  and accounting for each activated theater.
- [ ] **COMMIT:** `feat(spatial-scope): enable reviewed admin2 theaters`

## Work order 4 — One truthful 3D metric adapter (optional)

- [ ] **RED:** Test metric value→height scale, unit/time basis, clamping, zero,
  negative/invalid/missing behavior, legend, snapshot revision, scope generation,
  reduced motion, pick accessibility, and no height when data is absent. Assert arcs
  or extrusion are absent unless the selected metric explicitly requires them.
- [ ] **GREEN:** Implement a separate metric presenter over already scoped data and
  batched Cesium geometry. Height/colour encode documented values only; tooltip and
  legend expose value, unit, timestamp and provenance.
- [ ] **REFACTOR:** Metric presentation never enters `SpatialScopeModule`; disabling it
  leaves navigation/query semantics unchanged.
- [ ] **VERIFY:** Golden data-to-visual tests, analyst readability review, GPU/frame
  benchmark, reduced-motion/accessibility check, and long-session disposal soak.
- [ ] **COMMIT:** `feat(worldview): visualize scoped <metric-name> in 3d`

## Final gate

Every activated layer has a truthful capability row and stale guard; Admin-2 meets
catalog and data coverage budgets; 3D (if selected) exposes real metric semantics and
adds no decorative height or arcs. Any unsupported/partial path is visible and no
non-global request falls back to global data. Then run the whole-program verification
from the plan index and close Spec 14 §29 with attached evidence.
