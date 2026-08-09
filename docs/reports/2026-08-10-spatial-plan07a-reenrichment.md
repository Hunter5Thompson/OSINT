# Spatial Scope Plan 07A — Restartbares Qdrant-Re-Enrichment

**Datum:** 2026-08-10

**Status:** Code-Gate bestanden; operatives Staging-/Apply-Gate bewusst offen

**Zielrevision des aktiven Katalogs:** `spatial-projection-v1-a5ce3a4f4657`

## Ergebnis

`services/intelligence/rag/spatial_reenrich.py` implementiert einen unabhängigen,
restartbaren Batch-Seam für die räumliche Qdrant-Projektion. Source-spezifische,
deterministische Projectors liefern pro Point eine vollständige Projektion; der
Batch-Seam besitzt ausschließlich Pagination, Validierung, atomaren Vollersatz,
Checkpointing und Coverage-Accounting.

Ein Apply ersetzt einen Point mit genau einem vollständigen Qdrant-Upsert. Vektor und
alle nicht-räumlichen Payload-Felder bleiben erhalten. Vorherige `spatial_*`-Felder,
`geo` und die rohen räumlichen Codefelder werden vollständig entfernt und nur aus
der neuen Projektion wieder eingesetzt. Damit können Pair-Token-Arrays und
Projektionsprovenance nicht aus unterschiedlichen Läufen stammen. Der verbotene
Qdrant-Scalar `spatial_derivation_revision` wird am Projector-Seam fail-closed
abgewiesen.

## Restart- und Freigabevertrag

- Der Modus ist als `dry-run` oder `apply` explizit.
- Ein Dry-run ignoriert vorhandene Apply-Checkpoints, scannt immer die vollständige
  Lane und schreibt weder Qdrant noch Checkpoint.
- Ein Apply-Checkpoint ist durch `lane|target_projection_revision` identifiziert.
- Der gespeicherte Cursor bezeichnet die nächste Seite nach dem letzten vollständig
  bestätigten Batch. Bei einem Fehler bleibt er auf dem letzten bestätigten Stand.
- Ein bereits als vollständig markierter Apply-Job wird idempotent nicht erneut
  ausgeführt.
- `validate_dry_run_approval` akzeptiert nur einen vollständigen Full-Lane-Dry-run
  mit gültigem kanonischem SHA-256-Fingerprint und weist Drift gegen einen frischen
  Dry-run zurück.
- Der produktionsnahe Qdrant-Adapter scrollt ausschließlich mit einem explizit
  injizierten Corpus-Lane-Filter und schreibt per `upsert(wait=True)`. Er erstellt
  keine Collection und keine Payload-Indizes.

Der gemeinsame, aber runtime-unabhängige Dateivertrag liegt in
`contracts/spatial-batch-file-formats-v1.json`. Er pinnt die gemeinsamen
Plan-06A-/Plan-07A-Semantiken sowie die getrennten Checkpointformate der beiden
Services.

## Projektionsrevision und Scheduling

Der Intelligence-Vertrag berechnet die Zielrevision aus kanonischem JSON über:

1. Projection-Schema-Version,
2. Pair-Token-Version `sr1`,
3. Deriver-Version `spatial-deriver-v1`,
4. versioniertem About-Gate,
5. vollständiger, lexikalisch sortierter Scope→Derivationsrevision-Menge.

Der aktive 204-Scope-Manifestvektor ergibt weiterhin exakt
`spatial-projection-v1-a5ce3a4f4657`. Eine veränderte Scope-Revision plant einen Job
je eindeutiger Lane. Ein Catalog-Carry-forward mit identischer vollständiger
Scope→Revisionsmenge plant keinen Rewrite. Eine separat persistierte vorherige
Projektionsrevision kann Änderungen an Token-/Deriver-/Gate-Semantik auch bei
unveränderter Scope-Menge auslösen.

## Coverage-Vertrag

Jeder Bericht enthält vor und nach der geplanten Projektion einen
`SpatialCoverageSnapshotV1` für genau eine Lane mit:

- `total_points`
- `filterable_points`
- `conflict_points`
- `stale_points`
- `unsupported_points`

Fehlende beziehungsweise noch nicht angereicherte Points bleiben als Differenz zum
Total sichtbar. Explizit `unavailable` markierte Legacy-Points zählen auch ohne alte
Projektionsrevision als `unsupported`. Stale-Zahl und Stale-Rate sind separat
sichtbar. Der hermetische Contract-Vektor weist vor der Projektion
`4 / 1 / 1 / 1 / 1` und danach `4 / 2 / 1 / 0 / 1` aus; die Stale-Rate fällt von
`0.25` auf `0.0`.

## TDD- und Verifikationsevidenz

Der erste fokussierte Lauf war erwartungsgemäß rot: sieben Tests scheiterten wegen
des fehlenden Re-Enrichment-Moduls, einer wegen des fehlenden
Projektionsfingerprints. Weitere isolierte REDs belegten den fehlenden gemeinsamen
Dateivertrag, die fehlende Dry-run-Approval-Prüfung, das fehlerhafte Wiederverwenden
eines abgeschlossenen Apply-Checkpoints im Dry-run und die zunächst fehlende
Stale-Rate.

Nach GREEN/REFACTOR:

```text
cd services/intelligence
uv run pytest tests/test_spatial.py tests/test_hybrid_retriever.py tests/test_spatial_reenrich.py -q
37 passed

cd services/data-ingestion
uv run pytest tests/test_spatial_batch.py tests/test_qdrant_spatial_projection.py -q
23 passed
```

Die fokussierten Ruff-Prüfungen beider Services sind grün. Alle Qdrant-Aufrufe in
diesen Tests laufen gegen hermetische Fakes beziehungsweise den lokalen In-Memory-
Client; es gab keine externe Mutation.

## Offenes operatives Gate

Nicht ausgeführt wurden:

- Payload-Index-Erstellung in Staging,
- Dry-run gegen einen realen Staging-Corpus,
- Review/Freigabe dieses realen Reports,
- Re-Enrichment-Apply,
- reale Analysis-/Realtime-Coverage- und Stale-Snapshots.

Diese Schritte benötigen gemäß Handoff eine ausdrückliche operative Autorisierung.
Bis dahin wird keine Exact-Capability auf Basis einer behaupteten realen Coverage
promoted.
