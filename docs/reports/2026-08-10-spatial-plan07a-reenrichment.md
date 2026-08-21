# Spatial Scope Plan 07A — Restartbares Qdrant-Re-Enrichment

**Datum:** 2026-08-10

**Status:** Code-Gate bestanden; operatives Staging-/Apply-Gate bewusst offen

**Zielrevision des aktiven Katalogs:** `spatial-projection-v1-47fec701a2a2`

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

- Die öffentliche Preview besitzt keine Mutationsfähigkeit. Die öffentliche
  Apply-Funktion verlangt einen genehmigten vollständigen Dry-run als Pflichtargument;
  ein frei wählbarer öffentlicher Mode-Switch existiert nicht.
- Eine Preview ignoriert vorhandene Apply-Checkpoints, scannt immer die vollständige
  Lane und schreibt weder Qdrant noch Checkpoint.
- Ein Apply-Checkpoint ist durch `lane|target_projection_revision` identifiziert.
- Jeder persistierte Apply-Checkpoint trägt zusätzlich den Fingerprint des
  genehmigten Reports; ein Resume mit einem anderen Report scheitert vor Read/Write.
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
3. Deriver-Version `spatial-deriver-v2`,
4. versioniertem About-Gate,
5. vollständiger, lexikalisch sortierter Scope→Derivationsrevision-Menge.

Der aktive 204-Scope-Manifestvektor ergibt weiterhin exakt
`spatial-projection-v1-47fec701a2a2`. Eine veränderte Scope-Revision plant einen Job
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
- `unprojected_points`
- `audit_only_points`
- `inconsistent_points`

Die sieben Statuszähler ergeben exakt `total_points`; fehlende beziehungsweise noch
nicht angereicherte Points heißen `unprojected_points`, und eine gültige aktuelle,
aber tokenlose Ableitung heißt `audit_only_points`. Ein aktuelles Payload mit
widersprüchlichen Status-/Token-/Conflict-Feldern heißt `inconsistent_points`.
Explizit `unavailable` markierte Legacy-Points zählen auch ohne alte
Projektionsrevision als `unsupported`.
`stale_rate` ist für das Promotionsgate
`(stale_points + unprojected_points + inconsistent_points) / total_points`; der
heutige unangereicherte oder ein intern kaputter Korpus kann daher nicht als
`0 % stale` erscheinen. Die konstruktiv stets null bleibende
`projected_stale_rate` wurde durch getrennte Filterable-/Unprojected-Raten ersetzt.

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

Der anschließende vollständige Service-Gate ergab:

```text
services/intelligence
uv sync
uv run pytest
398 passed
uv run ruff check .
All checks passed

services/data-ingestion
uv sync
uv run pytest
1368 passed, 1 skipped, 17 deselected
uv run ruff check .
All checks passed
```

Die 17 Deselections entsprechen dem bestehenden `-m "not live"` aus `pytest.ini`.
Der eine Skip ist der bereits vorhandene, umgebungsabhängige GDELT-Integrationstest
für nicht laufende Dev-Compose-Services.

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
