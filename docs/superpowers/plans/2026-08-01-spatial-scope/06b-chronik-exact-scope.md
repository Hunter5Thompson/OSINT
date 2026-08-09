# Spatial Scope 06B — CHRONIK Exact Scope

> **Canonical slice:** 6 (query half) · **Requires:** Plans 04 and 06A exit gates
>
> **Load with:** [Spec 07 §14.2–14.5](../../specs/2026-07-31-spatial-scope-drilldown/07-chronik-query-contract.md),
> [Spec 08 §15.2/§15.5](../../specs/2026-07-31-spatial-scope-drilldown/08-neo4j-normalization.md),
> [Spec 14 §26.1/§26.3](../../specs/2026-07-31-spatial-scope-drilldown/14-rollout-and-acceptance.md).

## Outcome and seam

Promote eligible CHRONIK event lanes from catalog-bbox approximation to exact
materialized scope-key queries. Static templates are selected by scope kind and
relation, with revision compatibility and conflict/stale accounting. Activation is
server-side per lane/kind; rollback explicitly returns to `bbox_approximate`.

## File surface

Extend backend `app/services/spatial_filters.py`, timeline models/router/tests, config
activation settings, and observability. No Cypher is assembled from property names or
LLM output.

## Work order 1 — Static template registry

- [x] **RED:** Test a closed registry for country/admin1/admin2 event occurrence;
  parameter binding; compatible derivation revisions; conflict exclusion; no dynamic
  property names; unknown kind/relation unsupported; antimeridian irrelevant to exact
  key matching. Add an event with two matching `OCCURRED_AT` locations and require one
  top-level event.
- [x] **GREEN:** Add complete fixed Cypher templates. Collapse with deterministic
  `ORDER BY ... WITH ev, collect(l)[0] AS l` before `LIMIT`; count with
  `count(DISTINCT ev)`. Select the registry entry through enums only.
- [x] **REFACTOR:** Share predicates conceptually but keep full query strings static so
  Neo4j can plan the matching composite index.
- [x] **VERIFY:** `cd services/backend && uv run pytest tests/unit/test_spatial_filters.py tests/unit/test_timeline_router.py -v`
- [x] **COMMIT:** `feat(backend): compile exact spatial event templates`

## Work order 2 — Accounting and mixed coverage

- [x] **RED:** Fixture tests distinguish total, included distinct records, samples,
  unlocated, conflict, stale revision and unsupported. Verify `complete` only when the
  lane contract permits it; multi-location rows never inflate counts.
- [x] **GREEN:** Execute count/sample queries against one pinned token and map results
  to `SpatialApplicationV1(mode=SpatialFilterMode.SEMANTIC_KEY)`. Echo
  scope/catalog/derivation compatibility and keep exclusions visible.
- [x] **REFACTOR:** One response-accounting function serves window/histogram endpoints
  and prevents divergent count semantics.
- [x] **VERIFY:** Run timeline model/router/histogram suites.
- [x] **COMMIT:** `feat(backend): report exact chronik coverage`

## Work order 3 — Per-lane activation and rollback

- [ ] **RED:** Test default-off exact gate, eligible lane/kind on, ineligible lane
  remaining bbox with explicit mode, missing/stale coverage blocking promotion, new
  derivation revision automatically disabling exact until re-enrichment, and rollback
  returning visibly to approximation without global fallback. Once an exact lane is
  active, an execution failure returns `503/SPATIAL_FILTER_UNAVAILABLE`; it never
  retries as bbox or global inside that request.
- [ ] **GREEN:** Add an allowlisted activation registry tied to coverage revision and
  derivation revision. Resolve a request once, choose exact or bbox explicitly, and
  emit activation/rejection metrics.
- [ ] **REFACTOR:** Gates are deployment config/data, not query parameters and never
  client-controlled.
- [ ] **VERIFY:** Run full backend tests/lint/mypy; execute staging `EXPLAIN` and
  accounting smoke for every promoted lane/kind.
- [ ] **COMMIT:** `feat(chronik): activate exact scope per covered lane`

## Exit gate

Approved lanes meet Spec-08 coverage and index-plan gates; duplicate locations do not
duplicate events or consume row limit; all exclusion counts reconcile; non-approved
lanes remain honestly approximate. `exact` names only the activation gate; successful
responses report `semantic_key`. Disabling exact never yields an unfiltered query.
