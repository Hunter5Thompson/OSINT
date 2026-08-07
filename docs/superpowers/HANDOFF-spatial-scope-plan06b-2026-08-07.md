# HANDOFF — Spatial Scope Plan 06A → Plan 06B

**Datum:** 2026-08-07

**Nächster Chat:** Plan 06B — exact CHRONIK erst nach den offenen 06A-Betriebsgates

**Branch:** `feat/spatial-plan03` (auf `origin` gepusht, kein PR, kein Merge)

**Arbeitsverzeichnis:** `/home/deadpool-ultra/ODIN/OSINT`

**Plan-06A-Implementierungs-HEAD:** `51f15f9`

**Basis:** `origin/main` bei `7704d8e`

## Kurzstand

Plan 06A ist im Code vollständig und testgetrieben implementiert. Alle vier
vorgesehenen Work-Order-Commits liegen auf `origin/feat/spatial-plan03`. Der Plan steht
ehrlich bei **18/20 Checkboxen**: Die beiden VERIFY-Punkte benötigen reale
Staging-/Betriebsnachweise, für die in diesem Chat keine Freigabe bestand.

Es wurden insbesondere **keine** Neo4j-Migration, kein Deployment, kein Staging-
`EXPLAIN`, kein Staging-Dry-run, kein Backup und kein Backfill gegen einen echten Graph
ausgeführt. Exact CHRONIK wurde nicht aktiviert. Plan 06B darf keine Lane exact
schalten, bevor die unten genannten Exit-Gates belegt und reviewt sind.

## Pflichtstart für den nächsten Chat

1. Vollständig lesen:
   - `AGENTS.md`
   - `CLAUDE.md`
   - dieses Handoff
   - `docs/superpowers/plans/2026-08-01-spatial-scope/06a-neo4j-normalization-and-backfill.md`
   - den Plan 06B samt gerouteten Specs
2. Branch und Fremdänderungen prüfen:
   ```bash
   git status --short --branch
   git log -6 --oneline --decorate
   ```
3. Die beiden fremden Working-Tree-Dateien nicht stageen, ändern oder zurücksetzen.
4. Vor exact CHRONIK zuerst die offenen 06A-Betriebsgates mit ausdrücklicher
   Nutzerfreigabe abarbeiten oder Plan 06B weiterhin blockiert halten.
5. Kein PR und kein Merge nach `main`, bis der Nutzer dies ausdrücklich freigibt.

## Plan-06A-Commits

| Work Order | Commit | Ergebnis |
|---|---|---|
| 1 — Normalizer | `3f62b43` | Pure, strikte und deterministische Normalisierung |
| 2 — Forward Writer | `2dae8a7` | Atomare parametergebundene Location-Writes |
| 3 — Indizes | `cfe20b2` | Additive Migration und read-only Plan-Smoke |
| 4 — Backfill | `51f15f9` | Restartbarer Dry-run/Apply- und Re-Enrichment-Pfad |

## Implementierter Vertrag

### Pure Normalisierung

- `RawLocationIdentity` validiert Code/System- und Latitude/Longitude-Paare strikt.
- `(0,0)` bleibt ein echter Source-Punkt; es gibt weder Truthiness-Verlust noch einen
  erfundenen Null-Island-/Centroid-Fallback.
- Explizite Adapter decken ISO-2, ISO-3, UN M49, Natural-Earth-M49, GDELT GEC,
  ISO-3166-2, geoBoundaries und ODIN-Scope-Keys ab.
- Freie Namen bleiben Rohprovenienz und werden niemals Scope-Identität.
- Source-Code-Präzedenz, coordinate-only Containment, Boundary-Konflikte und
  widersprüchliche Quellen sind deterministisch und fail-closed.
- Katalogrevision, aktuelle Derivationsrevision und reviewte kompatible
  Derivationsrevisionen bleiben getrennt.

### Additive `:Location`-Properties

Plan 06B darf ausschließlich diesen Vertrag konsumieren:

```text
source_country_code
source_country_code_system
country_iso3
admin1_code
admin2_code
country_scope_key
admin1_scope_key
admin2_scope_key
geo
spatial_basis
spatial_precision
spatial_catalog_revision
spatial_derivation_revision
spatial_conflict
spatial_conflict_scope_keys
```

Country-only-Datensätze besitzen keinen erfundenen Punkt und keinen erfundenen
Admin-1-Key. Exakte Queries müssen `spatial_conflict=true` ausschließen und die
freigegebene Derivationsrevision binden.

### Forward-Writer-Inventar

Der Graph-Integrity-Report enthält ein versioniertes, JSON-fähiges Inventar:

- `gdelt_raw` — aktiv, gemeinsamer Normalizer, explizite Bolt-Transaktion mit Rollback;
- `rss_pipeline` — aktiv, strukturierter ISO-2-Country-Scope ohne Centroid;
- `military_aircraft` — aktiv, beobachtungsbezogener Location-Key und Point;
- `backend_incident` — aktiv, aber ausdrücklich `unsupported` wegen noch nicht
  integrierter Cross-Service-Normalisierung;
- `intelligence_link_event_location` — inaktiv, keine Produktionsaufrufer;
- drei alte Graph-Integrity-Writer — als Migration-only ausgewiesen.

Der aktive Backend-Incident-Writer ist damit ein echtes offenes Lane-Gate. Er darf in
Plan 06B nicht still als exact-fähig behandelt werden.

### Indizes und Plan-Smoke

`migrations/location_spatial_scope_indexes.cypher` deklariert ausschließlich:

```text
location_country_scope_derivation (country_scope_key, spatial_derivation_revision)
location_admin1_scope_derivation  (admin1_scope_key, spatial_derivation_revision)
location_admin2_scope_derivation  (admin2_scope_key, spatial_derivation_revision)
location_geo                      (geo) — POINT
```

Alle vier Deklarationen verwenden `IF NOT EXISTS`. Der frühere `location_geo`-Satz
wurde aus `gdelt_raw/migrations/phase2_indexes.cypher` entfernt, sodass genau eine
Deklaration existiert.

Der read-only Smoke ist vorbereitet:

```bash
cd services/data-ingestion
uv run python -m graph_integrity.cli spatial-index-smoke
```

Er gibt maschinenlesbare `EXPLAIN`-Evidence aus und failt, wenn ein vorgesehener
Composite-Index nicht gewählt wird. Er wurde nicht gegen Staging ausgeführt.

### Backfill und Re-Enrichment

- Dry-run und Apply sind explizit und gegenseitig exklusiv.
- Apply verlangt ein content-adressiertes, frisch erneut geprüftes Dry-run-Reportfile.
- Cursor sind stabil nach `loc_key`; Checkpoints sind nach Jobart, Lane und
  Ziel-Derivationsrevision getrennt.
- Ein Checkpoint wird erst nach einem vollständig angewandten atomaren Batch
  fortgeschrieben; Wiederholung nach Crash ist idempotent.
- Konflikte erhalten nur Audit-/Conflict-Felder; bestehende Roh-/Scope-Felder bleiben
  unangetastet. Unresolved/invalid werden nicht geschrieben.
- Legacy-RSS-Centroids werden country-only normalisiert, ohne ihren synthetischen
  Mittelpunkt als neuen Point zu materialisieren.
- Location-Datensätze ohne stabile ID werden gezählt, machen das Report
  `complete=false` und blockieren die Apply-Freigabe.
- Reports enthalten total, already-normalized, resolvable, unresolved, conflict,
  invalid-coordinate, target-revision-mismatch, geplante/angewandte Writes,
  by-source/by-code-system, projected Country-Coverage sowie den Anteil reviewt
  kompatibler stale Revisionen.
- Eine neue Derivationsrevision plant pro betroffenem Lane/Scope-Kind einen
  restartbaren Job; Carry-forward derselben Revision plant keinen Rewrite.

Beispiel für einen reinen Dry-run; echte Pfade und Zielrevision müssen operatorseitig
reviewt werden:

```bash
cd services/data-ingestion
uv run python -m graph_integrity.cli backfill-spatial-scope \
  --lane gdelt_raw \
  --target-derivation-revision spatial-derive-v1-4d1de888e0c7 \
  --batch-size 500 \
  --checkpoint /operator/path/spatial-checkpoints.json \
  --report-out /operator/path/gdelt-dry-run.json \
  --dry-run
```

Apply bleibt zusätzlich vom Backup-/Deployment-Gate abhängig; das Vorhandensein der
CLI ist keine Freigabe zur Graph-Mutation.

## TDD- und Qualitätsnachweis

Dokumentierte RED-Schritte:

- WO1: Testmodul konnte `graph_integrity.spatial_normalizer` nicht importieren.
- WO2: acht GDELT-, drei RSS- und die neuen Aircraft-Writer-Tests waren zunächst rot.
- WO3: Migration und `spatial_index_smoke` fehlten; die statischen Tests waren rot.
- WO4: `spatial_batch` und `reenrich_spatial_scope` fehlten; die neuen Tests waren rot.

Grüne Nachweise:

- WO2 betroffene Writer-/Runtime-Suites: **120 bestanden**.
- WO3 Migration/Plan-Smoke fokussiert: **14 bestanden**.
- Graph-/Spatial-Fokus nach WO4: **109 bestanden**.
- Vollständiger Data-Ingestion-Lauf:
  **1.336 bestanden, 1 bedingter Integration-Skip, 17 `live` deselected**.
- `uv run ruff check .`: **grün**.

Der Skip ist der vorbestehende, bedingte GDELT-Integrationstest bei nicht laufenden
Dev-Compose-Services. Die 17 deselected Tests tragen den expliziten `live`-Marker.

## Offene 06A-Betriebsgates — blockieren exact

Folgende Nachweise existieren noch nicht:

1. Forward-Writer-Deployment vor Apply;
2. Backup/Restore-Punkt für den Zielgraph;
3. Anwendung der Indexmigration in Staging;
4. reale `EXPLAIN`-Evidence je Country/Admin-1/Admin-2;
5. vollständiger Staging-Dry-run und reviewtes Accounting je Lane/Revision;
6. 100 % erkannte Codes entweder normalisiert oder Conflict;
7. keine unbekannten Defaults;
8. Country-Coverage mindestens 95 % je Lane;
9. stale-compatible Rate höchstens 1 % je Lane;
10. Entscheidung/Integration für `backend_incident` und stabile IDs für etwaige
    Legacy-Aircraft-Locations;
11. reviewtes Coverage-Report als Freigabe-Artefakt für Plan 06B.

Ohne ausdrückliche Freigabe keine dieser Operationen gegen Staging/Live ausführen.

## TASK-123

`TASK-123` bleibt **OFFEN**. Plan 06A betrifft den Neo4j-Datenpfad und erfüllt keine
der neun ausstehenden Frontend-/Legacy-Cleanup-Anforderungen. Das wurde in `TASKS.md`
ausdrücklich abgegrenzt.

## Working-Tree-Hygiene

Die zwei vorbestehenden fremden lokalen Änderungen bestehen unverändert fort:

- `docs/CONTAINER-STATUS.md`
- `scripts/spark/odin-spark-vllm.sh`

Sie wurden in keinem Plan-06A-Commit gestaged, verändert oder zurückgesetzt.

## Git- und Merge-Status

- Remote: `git@github.com:Hunter5Thompson/OSINT.git`
- Feature-Branch: `feat/spatial-plan03`
- Implementierungs-HEAD und Remote waren vor diesem Handoff identisch bei `51f15f9`.
- Es wurde kein PR erstellt und nichts nach `main` gemerged.
