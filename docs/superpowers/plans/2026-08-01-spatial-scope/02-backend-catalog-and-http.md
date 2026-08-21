# Spatial Scope 02 — Backend Catalog and HTTP

> **Status:** DONE (2026-08-06) · **Canonical slice:** 2 · **Requires:** Plans 00B and 01 contracts
>
> **Load with:** [Spec 04](../../specs/2026-07-31-spatial-scope-drilldown/04-spatial-catalog-contracts.md),
> [Spec 12 §§20–22](../../specs/2026-07-31-spatial-scope-drilldown/12-errors-security-and-observability.md),
> [Spec 13 Slice 2](../../specs/2026-07-31-spatial-scope-drilldown/13-implementation-and-tdd-slices.md).

## Outcome and seam

Serve the reviewed local catalog through a strict async FastAPI adapter, then replace
the frontend memory catalog in production with `HttpSpatialCatalog`. The backend owns
runtime resolution and validation; it never rebuilds, downloads, or guesses geometry.
A corrupt/missing catalog degrades only spatial capability and does not take down
health or unrelated routes.

## File surface

Create backend `app/models/spatial.py`, `app/services/spatial_catalog.py`,
`app/routers/spatial.py`, and unit tests `test_spatial_catalog.py` /
`test_spatial_router.py`. Modify `app/config.py` and `app/main.py`. Complete frontend
`src/spatial/catalog.ts` and its tests. Use catalog fixtures generated in Slice 0.

## Work order 1 — Loader and strict models

- [x] **RED:** Test active+previous loading, revision/hash/schema/lineage validation,
  missing/corrupt catalog, undeclared assets, bad relative paths, declared byte-length
  mismatch, and compatibility-list rules. Prove startup opens no network connection.
- [x] **GREEN:** Implement strict Pydantic models and `SpatialCatalogLoader`. Load
  manifests and metadata via `asyncio.to_thread`, index scopes/assets by served
  revision, cache successful immutable hash checks, and expose an unavailable state
  instead of crashing app startup.
- [x] **REFACTOR:** Loader methods return domain values/problems; no FastAPI exception
  or response object enters the service.
- [x] **VERIFY:** `cd services/backend && uv run pytest tests/unit/test_spatial_catalog.py -v`
- [x] **COMMIT:** `feat(backend): load versioned spatial catalogs`

## Work order 2 — Safe HTTP adapter

- [x] **RED:** Test bootstrap/scope/asset success; 404 unknown; 409 unserved revision;
  422 invalid scope, revision, asset ID, slash/backslash/traversal; 503 corrupt/unready;
  stable `ScopeProblem` body; ETag/304; immutable/range headers; and no internal path
  or source URL leakage. Bootstrap contains exactly one attribution entry per served
  revision; its bounds and malformed-metadata behavior match Spec 04 §10.4/§10.10 and
  Spec 12 §20.1 exactly.
- [x] **GREEN:** Implement `/api/spatial/catalog`, `/api/spatial/scope`, and
  `/api/spatial/assets/{asset_id}`. Resolve asset paths only through validated manifest
  records and reuse cache/range semantics from `CachedStaticFiles` where applicable.
  Project validated attribution for every served revision into the existing bootstrap;
  add no free file path. Register the router under the centralized `/api` prefix.
- [x] **REFACTOR:** Keep status/problem mapping in one closed table. Handler functions
  remain async and perform blocking file I/O through `asyncio.to_thread`.
- [x] **VERIFY:** `cd services/backend && uv run pytest tests/unit/test_spatial_router.py -v`
- [x] **COMMIT:** `feat(backend): serve spatial catalog endpoints`

## Work order 3 — Asset saturation and lifecycle

- [x] **RED:** With a deterministic fake file opener/clock, saturate the configured
  semaphore and assert `429 ASSET_BUSY`, `Retry-After: 1`, zero file opens for the
  rejected request, `finally` release, and no leak on cancellation/client disconnect.
  Test loader cache disposal at shutdown.
- [x] **GREEN:** Add validated settings `spatial_catalog_path`,
  `spatial_asset_max_concurrency=8`, and acquire timeout. Construct one loader in the
  lifespan at `app.state.spatial_catalog`; own the semaphore and verified-asset cache
  there.
- [x] **REFACTOR:** Preserve the trusted-LAN posture explicitly; do not invent auth in
  this slice. Emit the Spec-12 readiness, busy, hash, and resolve metrics/events.
- [x] **VERIFY:** Run spatial tests plus backend lifespan/mount tests.
- [x] **COMMIT:** `fix(backend): bound spatial asset reads`

## Work order 4 — Frontend HTTP catalog and asset store

- [x] **RED:** Test strict snake_case→camelCase decode, unknown fields/schema,
  descriptor/response mismatch, hash/byte/vertex/feature budgets, 304 reuse, 409/429
  problem mapping, abort, in-flight dedupe, ref-counted leases, and no eviction while
  leased. With injected clock/randomness, prove a 30-second 404 negative cache; at
  most one current-generation jittered retry for network/5xx; one `Retry-After` retry
  for active presentation after 429; no prefetch retry; and visible 409 rehydrate
  rather than silent revision replacement.
- [x] **GREEN:** Implement `HttpSpatialCatalog` and `BoundaryAssetStore` using only the
  fixed `/api/spatial/...` routes. Validate before cache insertion. Pin all subsequent
  navigation/prefetch calls to the committed catalog revision. Implement the bounded
  retry policy in this adapter/controller seam and re-check generation before retry.
- [x] **REFACTOR:** Memory and HTTP adapters satisfy one port; controller code remains
  unchanged. Cache owns decoded geometry, not React state.
- [x] **VERIFY:** Run frontend spatial tests, then full backend lint/mypy/tests and
  frontend lint/type-check/tests.
- [x] **COMMIT:** `feat(frontend): resolve spatial scopes from backend catalog`

## Exit gate

Active and previous revisions are concurrently served; arbitrary filesystem paths are
unreachable; rejected busy requests do not open files; corruption is a visible 503;
and frontend runtime decoding enforces the same budgets as the build. No third-party
URL exists in either runtime path.

## Post-integration 409 recovery

- [x] The HTTP problem adapter preserves `active_catalog_revision` as a branded value
  rather than message text, and malformed responses remain fail-closed.
- [x] Only the explicit `rehydrate` port resolves and re-pins that revision; ordinary
  409 resolution performs no replacement or hidden retry.
