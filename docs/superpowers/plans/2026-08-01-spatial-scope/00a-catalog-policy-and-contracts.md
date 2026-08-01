# Spatial Scope 00A — Catalog Policy and Contracts

> **Canonical slice:** 0 (first half) · **PR boundary:** Slice 0 with Plan 00B
>
> **Load with:** [Spec 02](../../specs/2026-07-31-spatial-scope-drilldown/02-scope-identity-and-boundary-policy.md),
> [Spec 04 §10.1–10.8](../../specs/2026-07-31-spatial-scope-drilldown/04-spatial-catalog-contracts.md),
> [Spec 05 §11.1–11.3](../../specs/2026-07-31-spatial-scope-drilldown/05-boundary-build-and-antimeridian.md),
> [Spec 13 Slice 0](../../specs/2026-07-31-spatial-scope-drilldown/13-implementation-and-tdd-slices.md).

## Outcome and seam

Create the offline catalog's policy core: one canonical country crosswalk, strict
scope/revision types, source-lock validation, catalog-plan validation, and stable
manifest lineage. This plan deliberately emits no geometry. Its handoff is a set of
pure models and reviewed fixtures that Plan 00B can consume without knowing almanac
or frontend internals.

Current seams to replace are
`infra_atlas/data/crosswalk.json` and the hard-coded `KOSOVO_ISO3 = "XKX"` path in
`infra_atlas/build_country_almanac.py`. `country-endonyms.json._topoIndex` remains a
flag-off legacy projection and is never an input to this module.

## File surface

Create under `services/data-ingestion/spatial_catalog/`:

- `__init__.py`, `models.py`, `identity.py`, `source_lock.py`, `manifest.py`
- `data/country_crosswalk.json`, `catalog-plan.json`

Modify/remove:

- `infra_atlas/build_country_almanac.py`
- remove `infra_atlas/data/crosswalk.json` in the same migration commit
- create the reviewed deployment lock at
  `services/backend/data/spatial/source-lock.json`

Tests live in `services/data-ingestion/tests/test_spatial_catalog_contracts.py`,
`test_spatial_catalog_identity.py`, and the existing almanac-builder test module.

## Work order 1 — Strict public models

- [ ] **RED:** Add table-driven tests for every accepted/rejected `ScopeKey`,
  `CatalogRevision`, `DerivationRevision`, asset ID, lineage depth, parent relation,
  `children_available/preferred_lod`, and the ninth compatible derivation revision.
  Include traversal, encoded slash, oversize, display-name, `country:XKX`, and
  malformed hash cases.
- [ ] **GREEN:** Implement frozen strict models and parsers in `models.py` and
  `identity.py`. Keep identity, catalog provenance, derivation compatibility, and
  geometry descriptors separate. Validation errors must be deterministic and must
  not repair input.
- [ ] **REFACTOR:** Centralize regexes and parent-kind rules here. Other build modules
  import these symbols; they do not redeclare them.
- [ ] **VERIFY:** `cd services/data-ingestion && uv run pytest tests/test_spatial_catalog_contracts.py tests/test_spatial_catalog_identity.py -v`
- [ ] **COMMIT:** `feat(spatial-catalog): define canonical identity contracts`

## Work order 2 — Single reviewed crosswalk

- [ ] **RED:** Add fixtures for Ukraine/FIPS `UP`, Kosovo, Northern Cyprus,
  Somaliland, Antarctica/M49 `010`, aliases, non-scope features, duplicate canonical
  keys, and unresolved Natural-Earth features. Prove a scope key cannot be generated
  from a label, that almanac/catalog resolve through the same file, and that
  `country-endonyms.json._topoIndex` is never read by a spatial catalog build.
- [ ] **GREEN:** Migrate and extend the existing crosswalk into
  `spatial_catalog/data/country_crosswalk.json`. Records retain source system/code,
  canonical ISO3/M49 where policy permits, aliases, provenance, and explicit reviewed
  special-feature disposition. Change `build_country_almanac.py` to consume this
  registry and remove its XKX constant and old crosswalk path.
- [ ] **REFACTOR:** Expose one pure resolver in `identity.py`; almanac and catalog
  builders call it rather than maintaining local maps. Delete the old crosswalk only
  after both callers' tests are green.
- [ ] **VERIFY:** Run the two new identity suites plus the focused existing
  `build_country_almanac` tests, then `rg -n "infra_atlas/data/crosswalk|KOSOVO_ISO3" services/data-ingestion` and expect no production hit.
- [ ] **COMMIT:** `refactor(data-ingestion): unify country identity crosswalk`

## Work order 3 — Source lock and catalog plan

- [ ] **RED:** Test missing/placeholder releases, mutable or malformed URLs, unknown
  license IDs, duplicate source IDs, wrong SHA-256, absent attribution, unknown plan
  scopes, implicit coverage, and unreviewed special geometry. A source hash mismatch
  must fail before parsing its payload.
- [ ] **GREEN:** Implement strict lock loading/hash verification in `source_lock.py`.
  Commit real immutable release metadata for Natural Earth, selected gbOpen inputs,
  the crosswalk, and the exactly pinned topology tool. Implement `catalog-plan.json`
  as the only reviewable activation/representation/strict-containment policy.
- [ ] **REFACTOR:** Separate the network-capable fetch contract from offline
  validation. This plan may define its interface, but only Plan 00B supplies the CLI.
- [ ] **VERIFY:** `cd services/data-ingestion && uv run pytest tests/test_spatial_catalog_source_lock.py -v`
- [ ] **COMMIT:** `build(spatial-catalog): lock reviewed boundary sources`

## Work order 4 — Manifest lineage and deterministic metadata

- [ ] **RED:** Test unknown parents, incomplete paths, cycles, inconsistent
  `children_available`, assets missing from the manifest, duplicate asset IDs,
  catalog-only carry-forward, incompatible derivations, and nondeterministic key or
  record ordering. Add a doc-owner gate for shared contract symbols from the spec
  registry.
- [ ] **GREEN:** Implement manifest construction/validation in `manifest.py` using
  canonical JSON bytes, sorted records, normalized numeric representation, and no
  volatile timestamp in revision inputs. Derive `derivation_revision` only from
  assignment inputs and `catalog_revision` from the complete stable manifest.
- [ ] **REFACTOR:** Keep hashing/serialization as pure byte-level functions so Plan
  00B can prove byte-identical output without mocking filesystems.
- [ ] **VERIFY:** `cd services/data-ingestion && uv run pytest tests/test_spatial_catalog_manifest.py -v`
- [ ] **COMMIT:** `feat(spatial-catalog): validate manifest lineage and revisions`

## Exit gate and handoff

All policy fixtures are reviewed; no source-lock placeholders remain; all Admin-0
features are canonical scopes or explicit reviewed non-scope records; almanac and
catalog share one resolver; the manifest model rejects broken lineage and silent
revision truncation. Hand Plan 00B the frozen models, lock, plan, crosswalk, and
canonical serializer. Do not approve Slice 0 yet: geometry feasibility is still red.
