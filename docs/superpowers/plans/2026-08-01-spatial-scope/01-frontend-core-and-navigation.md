# Spatial Scope 01 — Frontend Core and Navigation

> **Canonical slice:** 1 · **Requires:** [Plan 00A](00a-catalog-policy-and-contracts.md) contract fixtures
>
> **Load with:** [Spec 01](../../specs/2026-07-31-spatial-scope-drilldown/01-architecture-and-invariants.md),
> [Spec 03](../../specs/2026-07-31-spatial-scope-drilldown/03-frontend-core-and-navigation.md),
> [Spec 04 §10.9](../../specs/2026-07-31-spatial-scope-drilldown/04-spatial-catalog-contracts.md),
> [Spec 12 §20](../../specs/2026-07-31-spatial-scope-drilldown/12-errors-security-and-observability.md).

## Outcome and seam

Implement the renderer-free `SpatialScopeModule`: immutable snapshots, commands,
race-safe resolution, URL/history coordination, and a thin React adapter. The camera,
Cesium, timeline, and intelligence remain consumers. Tests use `MemorySpatialCatalog`
and `MemoryScopeNavigation`; no backend or WebGL is required.

`WorldviewPage` will own one provider near its composition root, but it will not lift
scope state into page state. `scope` has one URL owner; the page's existing
`layer/filter/entity` parsing remains untouched.

## File surface

Create `services/frontend/src/spatial/{contracts.ts,scopeController.ts,catalog.ts,navigation.ts,react.tsx}`
and tests under `src/spatial/__tests__/`. Modify `src/app/router.tsx`, add
`src/app/__tests__/router.test.tsx`, and minimally mount the provider in
`src/pages/WorldviewPage.tsx`. No Cesium files change in this slice.

## Work order 1 — Contracts and memory adapters

- [ ] **RED:** Port shared JSON contract vectors from Slice 0 and test branded scope
  parsing, immutable discriminated snapshots, path invariants, problem mapping, and
  stable object identity between publications.
- [ ] **GREEN:** Implement the public types exactly once in `contracts.ts`. Add strict
  runtime parsers plus `MemorySpatialCatalog` in `catalog.ts` and an injectable-clock
  `MemoryScopeNavigation` in `navigation.ts`.
- [ ] **REFACTOR:** Keep wire decoding out of public commands. `SpatialQueryRef` is the
  only query-facing token; geometry never enters a snapshot.
- [ ] **VERIFY:** `cd services/frontend && npm test -- src/spatial/__tests__/catalog.test.ts`
- [ ] **COMMIT:** `feat(frontend): define spatial scope contracts`

## Work order 2 — Command store and generations

- [ ] **RED:** Test deep-link hydration without a world query flash, world→country→
  admin1→ascend, sibling lineage reconstruction, current/root no-ops, A→B supersede,
  caller cancellation, pending ascend from committed parent, shared in-flight resolve,
  catalog failure, semantic-only commit, and presentation completion for a stale
  `stateRevision`.
- [ ] **GREEN:** Implement `createSpatialScopeController` with cached frozen snapshots,
  monotonic foreground intent and state revisions, ref-counted loads, separate
  presentation lifetime, and idempotent `start/stop`. Validate generation and abort
  after every await. Operation failures return results; only programmer misuse throws.
- [ ] **REFACTOR:** Keep transition bookkeeping private. Expose only `getSnapshot`,
  `subscribe`, and `dispatch`; lifecycle stays with the provider owner.
- [ ] **VERIFY:** `cd services/frontend && npm test -- src/spatial/__tests__/scopeController.test.ts`
- [ ] **COMMIT:** `feat(frontend): add race-safe spatial scope controller`

## Work order 3 — Router navigation coordinator

- [ ] **RED:** Test push versus replace, popstate without history echo, preservation of
  all foreign query/hash/state fields, stale A write after B, pending navigation-ID
  echo suppression, historical reuse of an old ID, world without visible `scope`,
  revision only in validated router state, reload against active versus Back against
  the pinned served revision, invalid initial link repair, and the two-second
  `URL_SYNC_FAILED` path with fake time and explicit retry.
- [ ] **GREEN:** Implement the framework-free coordinator in `navigation.ts` and its
  React-Router bridge in `react.tsx`. `writeScope` resolves only on the matching bridge
  echo. It serializes writes and repairs a superseded location to the latest committed
  or desired scope.
- [ ] **REFACTOR:** Do not import the router singleton from `spatial/`; the bridge owns
  `useLocation/useNavigate`. The controller alone parses the untrusted candidate.
- [ ] **VERIFY:** Run `navigation.test.ts`, then the new router test proving `/` keeps
  `scope` and all other parameters when redirecting to `/worldview`.
- [ ] **COMMIT:** `feat(frontend): synchronize spatial scope with router history`

## Work order 4 — React provider and composition root

- [ ] **RED:** Test `useSyncExternalStore` stable wrappers, hook-outside-provider
  failure, hydrating singleton, StrictMode `start→stop→start`, one router subscription,
  one initial resolve, and full cleanup of requests/listeners/leases.
- [ ] **GREEN:** Implement `SpatialScopeProvider` and `useSpatialScope`; instantiate
  the module once per provider and mount it in `WorldviewPage`. The provider is inert
  behind the default-off `VITE_SPATIAL_SCOPE_ENABLED` gate and creates no renderer.
- [ ] **REFACTOR:** Type the Vite flag in `src/vite-env.d.ts`. Keep existing page query
  concerns and all Spotlight behavior unchanged.
- [ ] **VERIFY:** Run all spatial/router/page focused tests, then
  `npm run lint`, `npm run type-check`, and `npm test` from `services/frontend`.
- [ ] **COMMIT:** `feat(frontend): mount spatial scope provider`

## Exit gate

All Slice-1 red cases are green with memory adapters only. URL, committed scope, and
query token change together; failed/superseded work cannot mutate them. A deep link
publishes no query before resolution. StrictMode leaves one live module. No React or
Cesium type appears in `scopeController.ts`.

## Post-integration 409 hardening

- [x] `ScopeProblem` carries a branded active catalog revision and the memory/HTTP
  adapters expose one shared explicit `rehydrate` port.
- [x] The parameterless controller command re-resolves only the committed scope,
  performs a replace navigation, and checks generation/abort around every await.
- [x] A production alert renders exactly one recovery action; controller, navigation,
  React and router-composition tests cover 404, repeated 409, network failure,
  pre-abort, supersession and Back/Forward without a global-data fallback.
