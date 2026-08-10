# Spatial Scope Plan 07A — Review-Remediation

**Datum:** 2026-08-10

**Branch:** `feat/spatial-plan03`

**Code-Commit:** `f41d43d fix(spatial): harden Plan 07A review gates`

**Status:** Alle fünf Reviewpunkte code-/vertragsseitig geschlossen; operative
Qdrant-Promotion bleibt offen und nicht autorisiert

## Ergebnis

### 1. Apply ist strukturell approval-gated

Der öffentliche freie Mode-Switch wurde entfernt. Es gibt jetzt zwei getrennte
Interfaces:

```text
preview_spatial_reenrichment(store, projector, job)
apply_spatial_reenrichment(store, projector, checkpoints, job,
                           approved_report=...)
```

Preview besitzt keine Checkpoint- oder Write-Capability. Apply verlangt einen
vollständigen genehmigten Dry-run als Pflichtargument, vergleicht ihn vor dem ersten
Write mit einem frischen Vollscan und speichert dessen SHA-256-Fingerprint in jedem
Checkpoint. Ein Resume mit einem anderen Report scheitert vor Read und Write.

### 2 und 4. Coverage ist benannt, exakt und promotionswirksam

`SpatialLaneCoverageV1` enthält jetzt:

```text
total_points
filterable_points
conflict_points
stale_points
unsupported_points
unprojected_points
audit_only_points
```

Die sechs Statuszähler müssen exakt `total_points` ergeben. Nie projizierte Points
und aktuelle, aber tokenlose Audit-Projektionen sind damit nicht länger ein
unbenannter Rest. Der promotionswirksame `stale_rate` ist
`(stale_points + unprojected_points) / total_points`; ein vollständig
unangereicherter Korpus meldet daher 100 statt 0 Prozent Gap. Die konstruktiv stets
null bleibende `projected_stale_rate` entfiel zugunsten expliziter Filterable- und
Unprojected-Raten.

### 3. Conflict-Admission ist relations- und scopespezifisch

Drei Entwürfe wurden verglichen:

1. rein evidenzlokale flache Pair-Tokens;
2. flache writerseitige Admission je Relation und Scope;
3. ein neues Nested Evidence Ledger mit expliziter Query-Conflict-Policy.

Gewählt wurde Variante 2. Sie behält den bestehenden V1-Seam und macht die
Pair-Arrays zur alleinigen positiven Retrieval-Berechtigung:

- Conflict-Evidenz publiziert selbst keine Pair-Tokens und kein `geo`;
- Conflict-Keys werden vor Ausgabe pro Relation gesammelt;
- ein akzeptiertes Assignment wird nur bei demselben exakten Scope derselben
  Relation zurückgehalten;
- valide andere Scopes und Relationen bleiben auffindbar;
- Conflict-only hat keine Tokens und Status `conflict`;
- Mixed mit mindestens einem zugelassenen Token hat Status `filterable`;
- `spatial_conflict` und `spatial_conflict_scope_keys` sind unindizierte Auditfelder;
  der Filter-Compiler liest sie nicht.

Die Admission-Änderung bumpte den Deriver auf `spatial-deriver-v2` und damit den
aktiven Fingerprint auf `spatial-projection-v1-47fec701a2a2`. Vor Promotion ist
folglich ein vollständiger neuer Re-Enrichment-Lauf erforderlich.

### 5. Tokenlänge wird erzwungen

Beide service-lokalen Encoder weisen Pair-Tokens über 229 ASCII-Bytes mit einem
Domainfehler ab. Der gemeinsame JSON-Vertrag bindet denselben Grenzwert und beide
Services testen ihn unabhängig.

## Verifikation

```text
services/intelligence
395 passed
ruff check .: green

services/data-ingestion
1366 passed, 1 skipped, 17 deselected
ruff check .: green
```

Der Skip ist der vorhandene umgebungsbedingte GDELT-Integrationstest bei nicht
laufenden Dev-Compose-Services; es wurde kein `pytest.mark.skip` ergänzt. Die 17
Deselections sind die vorhandenen `live`-Tests.

## Operativer Stand

Der unabhängige read-only Review-Snapshot vom 2026-08-10 zählte 1.025.197 Points und
nur die neun Corpus-/Fulltext-Indizes. Es existieren weiterhin weder Spatial-Indizes
noch angereicherte Spatial-Payloads. Im Rahmen der Remediation wurden keine
Live-/Staging-Indizes angelegt, keine Points geschrieben und keine Capability
promoted.

Vor einer Promotion bleiben autorisierte Indexmigration, genehmigter Full-Lane-
Dry-run, Apply über das approval-gebundene Interface sowie ein nachfolgender realer
Coverage-Snapshot erforderlich. Ein wirksamer Stale-/Unprojected-Gap über 1 Prozent
blockiert.
