# Spatial Scope 06A — Neo4j Normalization and Backfill

> **Canonical slice:** 6 (data half) · **Requires:** Plan 00B artifacts
>
> **Load with:** [Spec 02 §7.5](../../specs/2026-07-31-spatial-scope-drilldown/02-scope-identity-and-boundary-policy.md),
> [Spec 08](../../specs/2026-07-31-spatial-scope-drilldown/08-neo4j-normalization.md),
> [Spec 12 §22](../../specs/2026-07-31-spatial-scope-drilldown/12-errors-security-and-observability.md),
> [Spec 13 Slice 6](../../specs/2026-07-31-spatial-scope-drilldown/13-implementation-and-tdd-slices.md).

## Outcome and seam

Materialize canonical spatial fields and `geo` on `:Location` through one pure
normalizer, forward writers, deterministic indexes, and repeatable dry-run/apply jobs.
Raw source codes/provenance remain; ambiguous records become explicit conflicts and
are excluded from exact queries. This plan does not activate exact CHRONIK.

## File surface

Create `graph_integrity/spatial_normalizer.py`, `backfill_spatial_scope.py`,
`reenrich_spatial_scope.py`, tests, and
`migrations/location_spatial_scope_indexes.cypher`. Modify GDELT and other existing
Location writers incrementally, beginning with
`gdelt_raw/writers/neo4j_writer.py`; extend graph-integrity CLI/reporting. Reuse the
catalog's crosswalk and containment artifacts—do not create a second geo model.

## Work order 1 — Pure deterministic normalizer

- [x] **RED:** Test paired code/system and coordinate validation, zero values, real
  `(0,0)`, GDELT GEC `UP→country:UKR`, ISO/M49/ISO-3166-2, raw preservation,
  country-only without invented point/Admin-1, coordinate-only interior assignment,
  boundary ambiguity, explicit source-code precedence, contradictory sources, unknown
  codes, and derivation/catalog/version separation.
- [x] **GREEN:** Implement strict `RawLocationIdentity` and output models plus a pure
  normalizer over reviewed crosswalk/containment indexes. Return values, basis,
  precision, conflict candidates and revisions; never Cypher.
- [x] **REFACTOR:** Codesystem adapters are explicit allowlisted functions. Free names
  never become keys. Reuse normal-form fixtures from Slice 0.
- [x] **VERIFY:** `cd services/data-ingestion && uv run pytest tests/test_spatial_normalizer.py -v`
- [x] **COMMIT:** `feat(data-ingestion): normalize canonical location scopes`

## Work order 2 — Forward writers and atomic transaction

- [x] **RED:** Writer tests assert `geo=point(...)`, all scope/audit/conflict fields in
  one parameter-bound transaction, rollback on partial error, country-only records,
  no truthiness loss at zero, and unchanged raw fields. Assert no dynamic Cypher or
  interpolated values.
- [x] **GREEN:** Call the shared normalizer before `MERGE_LOCATION`; extend existing
  deterministic templates/parameter builders. Start with live GDELT raw, then migrate
  every currently active Neo4j `Location` producer enumerated by `rg` and
  record unsupported lanes in the report rather than silently skipping them.
- [x] **REFACTOR:** One parameter projection maps normalizer output to properties;
  writers retain source-specific extraction only.
- [x] **VERIFY:** Run all affected writer suites and `ruff` on changed ingestion code.
- [x] **COMMIT:** `feat(data-ingestion): write spatial location fields atomically`

## Work order 3 — Index migration and plan smoke

- [x] **RED:** Static tests require the three composite range indexes and exactly one
  existing point index, all `IF NOT EXISTS`; reject duplicate or renamed properties.
  Integration smoke uses `EXPLAIN`/staging plan to prove the intended index for each
  scope kind.
- [x] **GREEN:** Add the deterministic migration and consolidate the existing
  `location_geo` declaration instead of duplicating it.
- [x] **REFACTOR:** Migration is additive and independently deployable before writers.
- [ ] **VERIFY:** Run migration tests; attach Neo4j plan evidence to the slice record.
- [x] **COMMIT:** `build(neo4j): add spatial location indexes`

> Hermetischer Stand: Migrationstests und der read-only `EXPLAIN`-Evidence-Collector
> sind grün. Der **VERIFY**-Punkt bleibt bis zum freigegebenen Staging-Lauf samt
> realer Neo4j-Plan-Evidence offen.

## Work order 4 — Backfill and recurring re-enrichment

- [ ] **RED:** Test dry-run zero writes, apply idempotency, stable cursor resume,
  lane+target-revision checkpointing, conflict/unresolved preservation, configurable
  batches, report accounting, interrupted restart, new derivation scheduling, and
  catalog carry-forward producing no rewrite.
- [ ] **GREEN:** Implement CLI jobs with explicit `--dry-run/--apply`, checkpoint and
  machine-readable report. Apply only deterministic results and retain old fields.
  Re-enrichment is triggered per affected lane for a new derivation revision.
- [ ] **REFACTOR:** Share batch engine/report schema between initial backfill and
  recurring re-enrichment; isolate deterministic parameterized Cypher constants.
- [ ] **VERIFY:** Run focused tests, then dry-run against staging and review total,
  already-normalized, resolvable, unresolved, conflict, invalid and by-source/system.
- [ ] **COMMIT:** `feat(graph-integrity): backfill spatial scope revisions`

## Exit gate and handoff

Forward writers are deployed before apply. Backup/restore point exists. Per lane,
recognized codes are either normalized or conflict; no unknown defaults; country
coverage is at least 95%; stale compatible-revision rate is at most 1%; query plans use
the indexes. Hand Plan 06B the approved coverage report and exact property contract.
