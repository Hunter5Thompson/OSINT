# Spatial Scope 05D — Phase-D Legacy Cleanup

> **Deployment cleanup PR; not part of the Slice-5 feature commit.**
>
> **Hard prerequisite:** Slice 5 accepted, flag-on canary green, default-on release
> completed, and one agreed soak period with no rollback trigger.
>
> **Load with:** [Spec 13 §23.2/Slice 5](../../specs/2026-07-31-spatial-scope-drilldown/13-implementation-and-tdd-slices.md),
> [Spec 14 §26](../../specs/2026-07-31-spatial-scope-drilldown/14-rollout-and-acceptance.md).

## Outcome and seam

Remove the temporary legacy country identity/render path and its build flag after the
deployment gate—not before. Circle Spotlight, operational entity selection, global
context borders, and the Spatial adapter remain. Rollback changes from flag-off to
deploying the immediately previous frontend artifact.

## Preflight decision record

- [ ] Link the accepted canary/default-on soak evidence: errors, primitive/listener/
  decoded-cache high water, scope latency, and user-visible regressions.
- [ ] Record release artifact identifier and tested rollback procedure.
- [ ] Confirm no open stop-rule incident, catalog budget exception, or unsupported
  mandatory theater.
- [ ] Obtain the explicit Phase-D release decision; absence is a blocker, not an
  implementation detail.

## Work order 1 — Prove the delete set

- [ ] **RED:** Add a static-import/bundle test that fails while production reaches
  `useCountryHitTest`, legacy `pointInPolygon`, `CountryTarget`, `_topoIndex`, or the
  `VITE_SPATIAL_SCOPE_ENABLED` conditional. Add behavioral tests preserving Circle
  Spotlight and entity picking.
- [ ] **GREEN:** Make `WorldviewPage` and `EntityClickHandler` unconditionally use the
  Spatial path. Remove `CountryTarget` from `SpotlightContext`, country rendering from
  `SpotlightOverlay`, and related Cartouche branches. Keep one Escape coordinator.
- [ ] **REFACTOR:** Remove dead props/imports before deleting files so TypeScript shows
  the complete dependency cut.
- [ ] **VERIFY:** Run the new static and Spotlight/page tests.
- [ ] **COMMIT:** `refactor(worldview): make spatial country path permanent`

## Work order 2 — Delete legacy identity artifacts

- [ ] **RED:** Strengthen the import test to scan production modules and the built
  manifest for legacy filenames/symbols. Keep catalog-pick fixtures proving Kosovo and
  every world feature uses canonical child-pack identity.
- [ ] **GREEN:** Delete `useCountryHitTest.ts`, old hook tests, the migrated legacy
  `pointInPolygon.ts` and test, `_topoIndex` from `country-endonyms.json`, and obsolete
  capital-coverage coupling. Retain only non-identity endonym data still consumed; if
  none remains, remove the entire asset.
- [ ] **REFACTOR:** Delete `VITE_SPATIAL_SCOPE_ENABLED` typing/config/tests and any
  legacy branch comments. Do not remove the independent global `CountryBorders`
  context layer unless proven unused.
- [ ] **VERIFY:** Run `rg` for every deleted symbol/path, production build, lint,
  type-check, and full frontend tests. Inspect output manifest for absence.
- [ ] **COMMIT:** `refactor(frontend): remove legacy country identity path`

## Work order 3 — Artifact rollback rehearsal

- [ ] **RED:** Deployment smoke must fail when pointed at a missing catalog and remain
  healthy for unrelated routes; it must pass after redeploying the previous frontend
  artifact against the additive backend/data state.
- [ ] **GREEN:** Update release/rollback notes to specify artifact rollback, not flag
  mutation. Exercise forward→previous→forward in the target environment without
  deleting additive catalog, Neo4j, or Qdrant data.
- [ ] **REFACTOR:** Remove obsolete feature-flag operational documentation.
- [ ] **VERIFY:** Attach smoke results and artifact IDs to the release record.
- [ ] **COMMIT:** `docs(worldview): record phase-d artifact rollback`

## Exit gate

No production source or bundle references the legacy renderer, hook, crosswalk, flag,
or `CountryTarget`; all retained selection/Spotlight behavior is green; the previous
artifact rollback is proven against current additive backend/data. Only now is Spec
14 Phase D complete.
