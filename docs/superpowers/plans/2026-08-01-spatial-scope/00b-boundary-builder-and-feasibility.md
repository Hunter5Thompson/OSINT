# Spatial Scope 00B — Boundary Builder and Feasibility

> **Canonical slice:** 0 (second half) · **Requires:** [Plan 00A](00a-catalog-policy-and-contracts.md)
>
> **Load with:** [Spec 04 §10.5–10.6](../../specs/2026-07-31-spatial-scope-drilldown/04-spatial-catalog-contracts.md),
> [Spec 05](../../specs/2026-07-31-spatial-scope-drilldown/05-boundary-build-and-antimeridian.md),
> [Spec 12 §21](../../specs/2026-07-31-spatial-scope-drilldown/12-errors-security-and-observability.md),
> [Spec 13 Slice 0](../../specs/2026-07-31-spatial-scope-drilldown/13-implementation-and-tdd-slices.md).

## Outcome and seam

Build a deterministic, offline-only compiler from hash-verified boundary inputs to
ODIN `BoundaryGeometryV1`, `BoundaryPackV1`, manifests, attribution, and feasibility
reports. The compiler owns topology and representation; the backend in Plan 02 only
validates and serves opaque reviewed artifacts.

No runtime service downloads or simplifies geometry. `fetch` is the sole networked
command and writes only to an explicit cache; `build`, `verify`, and `audit` must run
offline from locked inputs.

## File surface

Create in `services/data-ingestion/spatial_catalog/`:

- `__main__.py`, `compiler.py`, `normalize.py`, `topology.py`, `lod.py`, `emit.py`,
  `audit.py`

Create tests:

- `tests/test_spatial_catalog_normalize.py`
- `tests/test_spatial_catalog_topology.py`
- `tests/test_spatial_catalog_emit.py`
- `tests/test_spatial_catalog_feasibility.py`
- `tests/fixtures/spatial_catalog/` with minimal dateline, hole, multipolygon and
  shared-border sources

Generated reviewed output goes only to
`services/backend/data/spatial/catalogs/<catalog-revision>/`.

## Work order 1 — Geometry normal form

- [x] **RED:** Add fixtures for open/reversed/duplicate rings, holes, orphan holes,
  self-intersection, degenerate area, non-finite/range-invalid coordinates, Fiji,
  Aleutians, Russia, Antarctica, and points at `179/-179`. Assert canonical closure,
  orientation, six-decimal containment precision, and one/two-span `GeoExtent`.
- [x] **GREEN:** Implement strict parsing and normalization in `normalize.py`; implement
  largest-longitude-gap extent calculation and query/ring unwrapping in
  `topology.py`. Invalid input fails or produces an explicit reviewed audit drop—never
  an undocumented repair.
- [x] **REFACTOR:** Keep geometry functions pure and free of Pydantic/file concerns.
  Export fixtures usable later by frontend `geometry.ts` parity tests.
- [x] **VERIFY:** `cd services/data-ingestion && uv run pytest tests/test_spatial_catalog_normalize.py tests/test_spatial_catalog_topology.py -v`
- [x] **COMMIT:** `feat(spatial-catalog): normalize topology and dateline geometry`

## Work order 2 — Topology-aware LOD and containment

- [x] **RED:** Test shared-border preservation, parent dissolve from complete
  children, protected junction/island/enclave anchors, per-LOD error and vertex
  budgets, containment max error `<= 50 m`, and strict-containment build failure.
  Include intentionally impossible fixtures to prove there is no silent coarse LOD.
- [x] **GREEN:** Wrap the exactly pinned topology tool in `lod.py`; its subprocess
  receives explicit files/arguments and produces validated intermediate output.
  Generate containment independently from render LODs and calculate geodesic maximum
  deviation plus the boundary-uncertain band.
- [x] **REFACTOR:** Isolate the external-tool adapter behind one function while ODIN
  owns validation, metrics, protected-feature policy, and output encoding.
- [x] **VERIFY:** Run the focused topology/LOD tests twice, including with network
  disabled. Both runs must produce identical normalized geometry bytes.
- [x] **COMMIT:** `feat(spatial-catalog): build bounded topology-aware lods`

## Work order 3 — Canonical asset emission

- [x] **RED:** Test exact wire schema, stripped source properties/URLs, canonical
  scope keys in every pickable feature, context-feature reasons, descriptor byte/
  vertex/feature counts, SHA-addressing, stable manifest order, attribution, and
  two byte-identical builds. Explicitly count post-arc-expansion repeated borders and
  ring closure.
- [x] **GREEN:** Implement `emit.py` with the serializer from 00A. Hash the exact bytes
  written; construct descriptors from the same counters used by gates; emit assets,
  manifest, attribution, and revisions into a temporary revision directory before an
  atomic publish into the explicit output path. `BoundaryPackV1` omits the
  `catalog_revision`; its Asset-ID is revision-bound by the manifest, avoiding a
  cryptographic self-reference.
- [x] **REFACTOR:** One traversal computes wire counters and descriptors. Do not keep a
  second TopoJSON-point estimate that can drift from enforcement.
- [x] **VERIFY:** `cd services/data-ingestion && uv run pytest tests/test_spatial_catalog_emit.py -v`
- [x] **COMMIT:** `feat(spatial-catalog): emit content-addressed boundary packs`

## Work order 4 — CLI, audit and feasibility gate

- [x] **RED:** Test CLI argument validation, hash failure before parse, offline build,
  verify of corrupt/missing assets, deterministic audit output, mandatory-theater and
  top-ten-ring coverage, every emitted world child LOD, 4 MiB wire/16 MiB heap/ring/
  feature/LOD-vertex limits, and the 25 MiB seed-catalog ceiling.
- [x] **GREEN:** Implement `fetch`, `build`, `verify`, and `audit` commands. Emit
  `containment-feasibility.json` with separate `containment` and
  `world_child_packs` sections using the production gate counters. Build the real
  world/Admin-0 seed plus only catalog-plan-selected Admin-1 fixtures.
  The pinned topology tool is consumed from one hash-verified offline archive that
  includes its complete ODIN GeoJSON runtime dependency closure and license manifest.
- [x] **REFACTOR:** Make command handlers thin over pure pipeline stages. Fetch never
  runs implicitly; build never accepts an unhashed input.
- [x] **VERIFY:** From `services/data-ingestion`, run the focused suite, then two real
  offline builds to separate temporary output roots and byte-compare every file.
  Run `uv run python -m spatial_catalog verify --catalog <first-root>` and audit it.
- [x] **COMMIT:** `build(spatial-catalog): gate deterministic seed catalog`

## Slice 0 exit gate

Review licenses, attribution, representation policy, pinned tool metadata, crosswalk
exceptions, and both feasibility-report sections. The build is green only if every
mandatory strict-containment scope and every emitted world child-pack LOD meets the
same counters used in its descriptor. Any violation invokes Spec 14 stop rules; it is
not deferred to Cesium. Finally run all `services/data-ingestion` tests. Handoff is a
reviewed immutable seed revision plus validators and minimal fixtures for Plans 01/02.

## Post-review release hardening

- [x] The committed Mapshaper bundle has a documented regeneration script that
  independently verifies every npm integrity and reproduces the source-lock SHA-256.
- [x] The adapter validates the actual Node engine, invokes that exact runtime, and
  records its version outside revision identity.
- [x] Atomic publication normalizes revision directories to `0755` and files to
  `0644`, including an already-identical destination.
- [x] The Spatial compiler is an explicit checkout/build extra; the production
  ingestion wheel and image exclude it, Shapely, Node, and the tool bundle. They ship
  only the Shapely-free identity/manifest interface required by `odin-infra-atlas`;
  an isolated built-wheel import test gates that seam.

This explicitly accepts Node as a controlled compiler-host dependency. It does not
relax the runtime boundary: no deployed service downloads, imports, or runs the
geometry compiler.
