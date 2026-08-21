# Spatial Scope — Implementation Plan Index

> **Status:** IN PROGRESS — alle regulären Pläne 00A–08 sind innerhalb ihrer
> akzeptierten Grenzen implementiert; ausschließlich der Sonderplan 05D bleibt
> blockiert offen (2026-08-10) · **Design gate:** PASS (2026-08-01)
>
> **Normative source:** [Spatial-Scope-Spec](../specs/2026-07-31-spatial-scope-drilldown-design.md)

## Purpose

This index turns the approved fourteen-part design into small, executable TDD work
orders. The normative specs remain organized by contract ownership; the plans are
vertical delivery units. Large canonical slices are split only at a real interface or
deployment seam, so an implementing agent normally loads this index, one plan, and
the plan's explicitly listed specs.

The nine slices in Spec 13 remain the review and PR boundaries. An `A/B` suffix means
sequential work orders inside the same slice PR. `05D` is different: it is a later
cleanup PR guarded by the Phase-D rollout decision.

## Plan set and dependency order

| Plan | Status | Canonical slice | Outcome | Requires |
|---|---|---:|---|---|
| [00A](2026-08-01-spatial-scope/00a-catalog-policy-and-contracts.md) | DONE | 0 | Identity, source lock, crosswalk, manifest contracts | approved spec |
| [00B](2026-08-01-spatial-scope/00b-boundary-builder-and-feasibility.md) | DONE | 0 | Deterministic assets, LODs, antimeridian, feasibility gate | 00A |
| [01](2026-08-01-spatial-scope/01-frontend-core-and-navigation.md) | DONE | 1 | Framework-free command store, URL port, React seam | 00A contract fixtures |
| [02](2026-08-01-spatial-scope/02-backend-catalog-and-http.md) | DONE | 2 | Runtime catalog service, safe HTTP, frontend adapter | 00B, 01 contracts |
| [03](2026-08-01-spatial-scope/03-cesium-country-migration.md) | DONE | 3 | World→country rendering, picking, breadcrumb, almanac | 01, 02 |
| [04](2026-08-01-spatial-scope/04-chronik-bbox-scope.md) | DONE | 4 | Honest bbox-scoped timeline with stale-data guards | 02, 03 |
| [05](2026-08-01-spatial-scope/05-admin1-and-prefetch.md) | DONE | 5 | Admin-1 drilldown, bounded cache and hover prefetch | 03 |
| [05D](2026-08-01-spatial-scope/05d-phase-d-legacy-cleanup.md) | BLOCKED | Phase D | Remove legacy country identity/renderer and build flag | TASK-123 + default-on release/soak/rollback decision |
| [06A](2026-08-01-spatial-scope/06a-neo4j-normalization-and-backfill.md) | DONE | 6 | Canonical Location fields, writers, indexes, repeatable jobs | 00B |
| [06B](2026-08-01-spatial-scope/06b-chronik-exact-scope.md) | DONE | 6 | Static exact Cypher and per-lane activation | 04, 06A |
| [07A](2026-08-01-spatial-scope/07a-qdrant-spatial-payload.md) | DONE | 7 | Spatial payload, indexes and repeatable re-enrichment | 06A |
| [07B](2026-08-01-spatial-scope/07b-munin-scope-enforcement.md) | DONE | 7 | Immutable run scope and capability-bound tools | 06B, 07A |
| [08](2026-08-01-spatial-scope/08-layers-admin2-and-3d.md) | DONE (BOUNDED) | 8 | Registry plus one strict point layer; unproved branches stopped/deferred | V1 gates from 03–07B |

`01` may start after 00A while 00B builds geometry. `06A` may proceed after Slice 0
while UI Slices 1–5 run, but exact activation still waits for `04` and its coverage
report. No other dependency is relaxed by parallel development.

## Verbleibender Planstand

Der kanonische Satz endet bei Plan 08. Genau ein Plan ist noch nicht ausgeführt:
Plan 05D. Er ist kein automatisch nächster Feature-Slice, sondern der gesperrte
Phase-D-Deployment-Cleanup.

Vor seiner Freigabe müssen die sieben noch offenen Kriterien 1–5, 7 und 8 aus
`TASK-123`, ein abgeschlossener Default-on-Release, der vereinbarte Soak, ein
getesteter Artefakt-Rollback und die explizite Phase-D-Entscheidung vorliegen. Dieses
Readiness-Paket ist kein zusätzlicher Plan 09. Die in Plan 08 belegbar gestoppt,
blockiert oder deferred gebliebenen Work Orders werden ebenfalls nicht als offene
Planpflichten umetikettiert; jede spätere Aktivierung braucht eine neue ausdrückliche
Produkt-/Evidenzentscheidung.

Die verbindliche TASK-123-Ausführung steht im
[dedizierten Handoff](../HANDOFF-spatial-scope-task123-2026-08-10.md): ein
Mandatory Start Record, vier Code-Work-Orders und ein Abschlussrecord innerhalb
eines einzigen begrenzten Implementierungsplans. Plan 05D bleibt davon als echter
Release-/Deployment-Seam getrennt.

## Normative-spec coverage

| Spec part | Implemented primarily by plans |
|---:|---|
| 01 Architecture/invariants | 01, 03, all exit gates |
| 02 Identity/policy | 00A, 06A, 07A |
| 03 Frontend core/navigation | 01, then consumed by 03/04/07B |
| 04 Catalog contracts | 00A, 00B, 01, 02 |
| 05 Boundary build | 00A, 00B, 05, 08 |
| 06 Cesium/layer semantics | 03, 05, 08 |
| 07 CHRONIK contract | 04, 06B |
| 08 Neo4j normalization | 06A, 06B, 07B graph templates |
| 09 Qdrant retrieval | 07A, 07B |
| 10 Munin enforcement | 07B |
| 11 UX/3D | 03, 04, 08 |
| 12 Errors/security/observability | all plans; primary work in 01/02/04/07B |
| 13 TDD slices | this entire plan set |
| 14 Rollout/acceptance | 03/05 canary, 05D cleanup, 08 final gate |

## Execution protocol

For every task in every plan:

1. Run the named focused test and capture the expected red failure.
2. Add only the minimal implementation needed to make that interface green.
3. Refactor while the focused test remains green; do not add speculative ports.
4. Run the plan's service-local verification commands.
5. Commit with the listed conventional-commit boundary.

The canonical slice is not complete until all of its subplans and exit gates are
green. Generated catalog assets are reviewed outputs, not hand-edited source. Never
run the networked `fetch` phase as part of tests, builds, service startup, or runtime.
Every work-order document is below 1,000 words so a review agent can load its listed
contract set without ingesting the rest of the program.

## Shared stop and handoff rules

- All stop rules in Spec 14 §27 apply. A hit stops implementation and returns to the
  design spec; it is not worked around inside a plan.
- No non-global consumer may fall back to global data.
- Every producer hands off a versioned fixture plus its validator, not an informal
  JSON example.
- Catalog and derivation revisions remain separate throughout all services.
- New Cypher writes are deterministic templates with parameter binding. Scoped graph
  reads use allowlisted templates only.
- Frontend production code uses no `any`; Cesium scope rendering uses batched
  primitives, never the Entity API.
- Backfills and re-enrichment have dry-run/apply modes, durable cursoring,
  idempotency, conflict accounting, and machine-readable reports.
- Do not delete the legacy country path before Plan 05D's deployment gate. After 05D,
  rollback is by prior frontend artifact, not by the removed build flag.

## Whole-program verification

Run commands from each service directory, as required by `AGENTS.md`:

```bash
cd services/frontend && npm run lint && npm run type-check && npm test
cd services/backend && uv run pytest && uv run ruff check app/ && uv run mypy app/
cd services/intelligence && uv run pytest
cd services/data-ingestion && uv run pytest
```

Slice 8 and the final rollout additionally require the Cesium performance/soak
evidence, Neo4j and Qdrant coverage reports, catalog audit, and the acceptance matrix
from Spec 14 §29. A green unit suite is necessary but not sufficient for activation.
