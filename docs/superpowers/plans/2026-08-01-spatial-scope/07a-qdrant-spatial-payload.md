# Spatial Scope 07A — Qdrant Spatial Payload

> **Canonical slice:** 7 (retrieval half) · **Requires:** Plan 06A assignment contract
>
> **Load with:** [Spec 09](../../specs/2026-07-31-spatial-scope-drilldown/09-qdrant-retrieval.md),
> [Spec 02 §7.5](../../specs/2026-07-31-spatial-scope-drilldown/02-scope-identity-and-boundary-policy.md),
> [Spec 12 §22](../../specs/2026-07-31-spatial-scope-drilldown/12-errors-security-and-observability.md),
> [Spec 13 Slice 7](../../specs/2026-07-31-spatial-scope-drilldown/13-implementation-and-tdd-slices.md).

## Outcome and seam

Add relation-specific spatial payloads, authorized payload-index migration, a pure
Qdrant filter compiler, and restartable atomic re-enrichment. Existing analysis and
realtime corpus policies remain the outer filter; spatial is an additional nested
`must`. Search never creates indexes or falls back globally.

## File surface

Create intelligence `spatial.py`, `rag/spatial_reenrich.py`, and tests
`test_spatial.py` / `test_spatial_reenrich.py`. Modify `rag/qdrant_schema.py`,
`scripts/ensure_payload_indexes.py`, `rag/retriever.py`, `rag/indexer.py`, and active
Qdrant writers in `services/data-ingestion` (currently GDELT raw and NLM paths).
Update service-local schema tests/doctor checks with one shared checked-in vector set.

## Work order 1 — Payload/index contract

- [ ] **RED:** Require every Spec-09 keyword/geo/bool index and reject wrong Qdrant
  types. Test current corpus-policy fields remain present. Test the migration creates
  only missing indexes, waits for completion, is idempotent, and search preflight is
  read-only.
- [ ] **GREEN:** Extend `PAYLOAD_INDEXES` and the existing authorized
  `ensure_payload_indexes` path. Mirror expectations in ingestion's doctor through a
  shared JSON contract fixture, not runtime cross-service imports.
- [ ] **REFACTOR:** Keep one migration writer; retriever/writers only validate and
  report missing schema.
- [ ] **VERIFY:** Run intelligence Qdrant schema/index tests and ingestion doctor tests.
- [ ] **COMMIT:** `build(qdrant): add spatial payload indexes`

## Work order 2 — Deterministic payload projection

- [ ] **RED:** Test occurrence only from structured location/coordinate; about only
  from reviewed extracted entity and confidence gate; non-global ancestors only;
  separate arrays; multiple bases/audit derivations; conflict exclusion; raw code
  preservation; catalog/derivation/version separation; world omitted; and no substring
  geography inference.
- [ ] **GREEN:** Add a pure projection from Plan-06A assignments/provenance to the
  Spec-09 payload. Migrate active writers to use it, preserving existing provenance
  and corpus-lane fields. Unsupported source lanes report unavailable spatial
  derivation rather than inventing keys.
- [ ] **REFACTOR:** Source extractors produce evidence; one deterministic projector
  decides filterable keys. Keep test vectors identical across ingestion/intelligence.
- [ ] **VERIFY:** Run GDELT writer, NLM ingest, indexer and new projection tests.
- [ ] **COMMIT:** `feat(qdrant): write relation-specific spatial payloads`

## Work order 3 — Filter compiler and policy composition

- [ ] **RED:** Test world→`None`; about/occurrence/either exact model trees;
  compatibility revisions; conflict/stale exclusion; corpus-policy nesting without
  mutation or weakened `should/must_not`; both analysis/realtime lanes; allowlisted
  field names only; and one/two-box AOI adapter fixtures.
- [ ] **GREEN:** Implement `SpatialScopeTokenV1`, `RetrievalSpatialRelation`,
  `compile_qdrant_scope_filter`, and `combine_filters` with qdrant-client model
  objects. Extend retriever calls to accept the compiled filter and coverage snapshot,
  not region strings.
- [ ] **REFACTOR:** Filter construction is pure and independent of network/search.
  Existing lane validation/reranking remains after retrieval.
- [ ] **VERIFY:** `cd services/intelligence && uv run pytest tests/test_spatial.py tests/test_hybrid_retriever.py -v`
- [ ] **COMMIT:** `feat(intelligence): compile qdrant spatial filters`

## Work order 4 — Atomic recurring re-enrichment

- [ ] **RED:** Test dry-run zero writes, full replacement of every `spatial_*` field in
  one point update, cursor resume, idempotency, lane+target-revision checkpoint,
  conflict/stale accounting, interrupted batch, new derivation scheduling, and
  catalog carry-forward no-op.
- [ ] **GREEN:** Implement `rag/spatial_reenrich.py` with explicit dry-run/apply and
  machine-readable per-lane coverage. Update points atomically; never mix arrays and
  scalar revisions from different runs.
- [ ] **REFACTOR:** Reuse the batch/report semantics from Plan 06A through file-format
  contracts, while keeping service deployment independent.
- [ ] **VERIFY:** Run focused tests, create indexes in staging before apply, execute
  dry-run/reviewed apply, and capture lane coverage/stale snapshots.
- [ ] **COMMIT:** `feat(qdrant): reenrich spatial payloads restartably`

## Exit gate and handoff

Writer changes precede re-enrichment; indexes precede reindex; every lane exposes
coverage; stale rate is visible and at most 1% for promotion. `about`, `occurrence`,
and `either` compose without altering corpus policy. Empty/partial/unsupported never
triggers an unfiltered retry. Hand Plan 07B the compiled filter and coverage contract.
