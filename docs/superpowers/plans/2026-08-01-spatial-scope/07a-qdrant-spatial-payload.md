# Spatial Scope 07A — Qdrant Spatial Payload

> **Canonical slice:** 7 (retrieval half) · **Requires:** Plan 06A assignment contract
>
> **Load with:** [Spec 09](../../specs/2026-07-31-spatial-scope-drilldown/09-qdrant-retrieval.md),
> [Spec 02 §7.5](../../specs/2026-07-31-spatial-scope-drilldown/02-scope-identity-and-boundary-policy.md),
> [Spec 12 §22](../../specs/2026-07-31-spatial-scope-drilldown/12-errors-security-and-observability.md),
> [Spec 13 Slice 7](../../specs/2026-07-31-spatial-scope-drilldown/13-implementation-and-tdd-slices.md).

## Outcome and seam

Add relation-specific, atomically paired scope/revision payloads, authorized
payload-index migration, a pure Qdrant filter compiler, and restartable atomic
re-enrichment. Existing analysis and realtime corpus policies remain the outer
filter; spatial is an additional nested `must`. Search never creates indexes or
falls back globally.

## File surface

Create intelligence `spatial.py`, `rag/spatial_reenrich.py`, and tests
`test_spatial.py` / `test_spatial_reenrich.py`. Modify `rag/qdrant_schema.py`,
`scripts/ensure_payload_indexes.py`, `rag/retriever.py`, `rag/indexer.py`, and active
Qdrant writers in `services/data-ingestion` (currently GDELT raw and NLM paths).
Update service-local schema tests/doctor checks with one shared checked-in vector set.

## Work order 0 — Ancestor-/revision contract

- [x] **RED:** An Admin-1-derived occurrence must match both its Admin-1 token and
  its Country-parent token, while a cross-pair poison point and incompatible
  revisions must not match.
- [x] **REVIEW:** Compare nested assignments, compound keywords and registry IDs.
  Select two relation-specific `sr1|ScopeKey|DerivationRevision` keyword arrays.
  The delimiter is excluded by both component grammars, so the encoding is
  injective without a hash-collision domain.
- [x] **GREEN:** Pin the representation and active UA-14 vector in
  `contracts/qdrant-spatial-payload-v1.json`; add the strict pure encoder.
- [x] **SPEC:** Correct Spec 02, Spec 09 and Slice 7 before defining final indexes.
  Qdrant has no record-wide scalar derivation revision. A separate projection
  fingerprint controls idempotent jobs and is never used for scope compatibility.
- [x] **COMMIT:** `docs(spatial): pair qdrant ancestor revisions`

## Work order 1 — Payload/index contract

- [x] **RED:** Require every Spec-09 keyword/geo/bool index from the shared contract
  and reject wrong Qdrant
  types. Test current corpus-policy fields remain present. Test the migration creates
  only missing indexes, waits for completion, is idempotent, and search preflight is
  read-only.
- [x] **GREEN:** Extend `PAYLOAD_INDEXES` and the existing authorized
  `ensure_payload_indexes` path. Mirror expectations in ingestion's doctor through a
  shared JSON contract fixture, not runtime cross-service imports.
- [x] **REFACTOR:** Keep one migration writer; retriever/writers only validate and
  report missing schema.
- [x] **VERIFY:** Run intelligence Qdrant schema/index tests and ingestion doctor tests.
- [x] **COMMIT:** `build(qdrant): add spatial payload indexes`

## Work order 2 — Deterministic payload projection

- [x] **RED:** Test occurrence only from structured location/coordinate; about only
  from reviewed extracted entity and confidence gate; non-global ancestors only;
  separate Pair-Token arrays with each Ancestor's own revision; multiple bases/audit
  derivations; relation-/scopespezifische Conflict-Admission statt recordweitem
  Recall-Verlust; raw code preservation;
  catalog/projection/deriver separation; world omitted; and no substring geography
  inference.
- [x] **GREEN:** Add a pure projection from Plan-06A assignments/provenance to the
  Spec-09 payload. Migrate active writers to use it, preserving existing provenance
  and corpus-lane fields. Unsupported source lanes report unavailable spatial
  derivation rather than inventing keys.
- [x] **REFACTOR:** Source extractors produce evidence; one deterministic projector
  decides filterable keys. Keep test vectors identical across ingestion/intelligence.
- [x] **VERIFY:** Run GDELT writer, NLM ingest, indexer and new projection tests.
- [x] **COMMIT:** `feat(qdrant): write relation-specific spatial payloads`

## Work order 3 — Filter compiler and policy composition

- [x] **RED:** Test world→`None`; about/occurrence/either exact model trees;
  compatibility revisions encoded with the requested ScopeKey; cross-pair,
  conflict and stale exclusion; corpus-policy nesting without
  mutation or weakened `should/must_not`; both analysis/realtime lanes; allowlisted
  field names only; and one/two-box AOI adapter fixtures.
- [x] **GREEN:** Implement `SpatialScopeTokenV1`, `RetrievalSpatialRelation`,
  `compile_qdrant_scope_filter`, and `combine_filters` with qdrant-client model
  objects. Extend retriever calls to accept the compiled filter and coverage snapshot,
  not region strings.
- [x] **REFACTOR:** Filter construction is pure and independent of network/search.
  Existing lane validation/reranking remains after retrieval.
- [x] **VERIFY:** `cd services/intelligence && uv run pytest tests/test_spatial.py tests/test_hybrid_retriever.py -v`
- [x] **COMMIT:** `feat(intelligence): compile qdrant spatial filters`

## Work order 4 — Atomic recurring re-enrichment

- [x] **RED:** Test dry-run zero writes, full replacement of every `spatial_*` field in
  one point update, cursor resume, idempotency, lane+target-projection-revision checkpoint,
  conflict/stale accounting, interrupted batch, new derivation scheduling, and
  catalog carry-forward no-op.
- [x] **GREEN:** Implement `rag/spatial_reenrich.py` mit einer mutationsfreien
  öffentlichen Preview und einem Apply, der einen genehmigten vollständigen Dry-run
  als Pflichtargument verlangt und dessen Fingerprint im Checkpoint bindet. Emit
  machine-readable per-lane coverage. Update points atomically; never mix arrays and projection
  provenance from different runs. Derive the target projection revision from the
  Pair-Token version, deriver version, About-Gate policy and complete sorted
  Scope→Derivationsrevisionen; catalog-only carry-forward keeps it stable.
- [x] **REFACTOR:** Reuse the batch/report semantics from Plan 06A through file-format
  contracts, while keeping service deployment independent.
- [x] **VERIFY (code):** Run focused Intelligence/Ingestion tests and hermetic
  Qdrant-adapter tests; capture the machine-readable report contract.
- [ ] **VERIFY (authorized staging):** Create indexes in staging before apply, execute
  dry-run/reviewed apply, and capture real lane coverage/stale snapshots. This remains
  an explicit operational authorization gate and was not performed during implementation.
- [x] **COMMIT:** `feat(qdrant): reenrich spatial payloads restartably`

## Review remediation — 2026-08-10

- [x] Apply ist strukturell approval-gated: Die öffentliche mutierende Funktion
  verlangt `approved_report`; der interne Mode-Switch ist keine öffentliche API.
  Resume akzeptiert ausschließlich denselben im Checkpoint gespeicherten
  Report-Fingerprint.
- [x] Coverage benennt `unprojected_points`, `audit_only_points` und
  `inconsistent_points`; alle sieben
  Statuszähler ergeben exakt `total_points`. Der Promotions-Stale-Gap zählt alte
  nie projizierte **und** intern widersprüchliche Points, sodass ein leerer oder
  kaputter Spatial-Korpus nicht `0 %` meldet. Die vorher konstruktiv immer null
  bleibende `projected_stale_rate` entfällt.
- [x] Pair-Tokens sind die positive Retrieval-Berechtigung. Conflict-Evidenz erzeugt
  keine Tokens/Geo; ein Conflict unterdrückt nur denselben Scope derselben Relation.
  Andere valide Scopes/Relationen bleiben auffindbar. Die beiden recordweiten
  Conflict-Felder sind unindizierte Auditfelder und der Compiler liest sie nicht.
- [x] Die geänderte Admission-Semantik ist als `spatial-deriver-v2` im
  Projektionsfingerprint enthalten und erzwingt vor Promotion ein vollständiges
  Re-Enrichment.
- [x] Der dokumentierte Grenzwert von 229 ASCII-Bytes wird in beiden unabhängigen
  Pair-Token-Encodern erzwungen.
- [x] **COMMIT:** `f41d43d fix(spatial): harden Plan 07A review gates`
- [x] **RE-REVIEW:** Pristine Checkpoints roundtrippen und alte durable States ohne
  Approval bleiben fail-closed; inkonsistente aktuelle Payloads besitzen einen
  eigenen Coverage-Bucket; Conflict-Status, -Flag und -Keys werden am Projector-Seam
  als eine Invariante validiert.
- [x] **COMMIT:** `c8571ba fix(spatial): close Plan 07A re-review gaps`

## Exit gate and handoff

Writer changes precede re-enrichment; indexes precede reindex; every lane exposes
coverage; stale rate is visible and at most 1% for promotion. `about`, `occurrence`,
and `either` compose without altering corpus policy. Empty/partial/unsupported never
triggers an unfiltered retry. Hand Plan 07B the compiled filter and coverage contract.
