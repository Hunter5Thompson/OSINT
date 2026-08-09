# HANDOFF — Spatial Scope Plan 06A → Plan 06B

**Datum:** 2026-08-07

**Operationaler Nachtrag:** 2026-08-09

**Nächster Chat:** Plan 06B — exact CHRONIK erst nach den offenen 06A-Betriebsgates

**Branch:** `feat/spatial-plan03` (auf `origin` gepusht, kein PR, kein Merge)

**Arbeitsverzeichnis:** `/home/deadpool-ultra/ODIN/OSINT`

**Pre-06B-Runtime-HEAD:** `c947dd9`

**Basis:** `origin/main` bei `7704d8e`

## Kurzstand

Plan 06A ist im Code vollständig und testgetrieben implementiert. Auf die vier
vorgesehenen Work-Order-Commits folgt der Review-Fix `2aee913`. Ein
operatorautorisierter Nachlauf am 2026-08-08 hat die beiden vormals offenen VERIFY-
Punkte geschlossen; der Plan steht damit bei **20/20 Checkboxen**.

Als Ziel diente der persistente lokale ODIN-Compose-Graph mit Neo4j 5.26.23. Die
additive Indexmigration wurde angewandt, alle vorgesehenen Indizes stehen `ONLINE`,
und reale `EXPLAIN`-Pläne wählen je Scope-Kind den Composite-Index. Ein eingefrorener
Graph-Snapshot wurde anschließend für alle vier Lanes mit `--dry-run` und null
angewandten Writes geprüft. Der vollständige Nachweis steht in
[Plan-06A Neo4j verification](../reports/2026-08-08-spatial-plan06a-neo4j-verification.md).

Der Snapshot entstand vor der anschließenden kontinuierlichen Writer-Akkumulation;
seine `Already = 0`-Werte sind keine aktuelle Graph-Baseline. Der neu gebaute
`data-ingestion-spark`-Container deployte die GDELT-, RSS- und Aircraft-Forward-
Writer in genau diese ODIN-Umgebung und lief danach weiter. Am 2026-08-09 hielt der
Null-Island-Guard bei 17.344 Locations weiterhin mit null `(0,0)`-Treffern.

Das ist weiterhin **keine** Backfill- oder Exact-Freigabe. Vor dem Writer-Deployment
wurde kein Backup/Restore-Punkt dokumentiert; ein aktueller Backup-Punkt bleibt vor
jedem Daten-Apply Pflicht. `backend_incident`, instabile Legacy-Aircraft-IDs und die
vollständige Multi-Revisionsfreigabe bleiben offen. Exact CHRONIK wurde nicht
aktiviert. Plan 06B darf keine Lane exact schalten, bevor die unten genannten
Exit-Gates belegt und reviewt sind.

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
| Review-Fix | `2aee913` | Source-Sentinel-Guards, Runner-Ownership und Conflict-Ausschluss |
| Pre-06B-Fix | `c947dd9` | Forward-Conflicts tragen keine Derivationsrevision mehr |

## Implementierter Vertrag

### Pure Normalisierung

- `RawLocationIdentity` validiert Code/System- und Latitude/Longitude-Paare strikt.
- Der generische Normalizer akzeptiert ein echtes `(0,0)` ohne Truthiness-Verlust.
  Source-Adapter verwerfen `(0,0)` dort separat, wo die Quelle es als Sentinel
  definiert; insbesondere GDELT, ADS-B und die Incident-/Backfill-Lanes.
- Explizite Adapter decken ISO-2, ISO-3, UN M49, Natural-Earth-M49, GDELT GEC,
  ISO-3166-2, geoBoundaries und ODIN-Scope-Keys ab.
- Freie Namen bleiben Rohprovenienz und werden niemals Scope-Identität.
- Source-Code-Präzedenz, coordinate-only Containment, Boundary-Konflikte und
  widersprüchliche Quellen sind deterministisch und fail-closed.
- Conflict-Ergebnisse behalten Audit-Scope und Kandidaten, tragen aber keine
  `spatial_derivation_revision`; dadurch stimmen Forward- und Batch-Pfad überein.
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
Admin-1-Key. Exakte Queries müssen immer `spatial_conflict = false` fordern und die
freigegebene Derivationsrevision binden. Die Nullung der Revision ist Defense-in-
Depth, kein Ersatz für diesen Read-Filter: fünf vor `c947dd9` forward-geschriebene
Conflicts tragen im bestehenden Graph weiterhin eine nicht-null Revision.

### Forward-Writer-Inventar

Der Graph-Integrity-Report enthält ein versioniertes, JSON-fähiges Inventar:

- `gdelt_raw` — aktiv, gemeinsamer Normalizer, explizite Bolt-Transaktion mit Rollback;
  GDELT-ActionGeo `(0,0)` erzeugt keine Location;
- `rss_pipeline` — aktiv, strukturierter ISO-2-Country-Scope ohne Centroid;
- `military_aircraft` — aktiv, beobachtungsbezogener Location-Key und Point nur bei
  vollständiger, nicht als `(0,0)` codierter Position;
- `backend_incident` — aktiv, aber ausdrücklich `unsupported` wegen noch nicht
  integrierter Cross-Service-Normalisierung;
- `intelligence_link_event_location` — inaktiv, keine Produktionsaufrufer;
- drei alte Graph-Integrity-Writer — als Migration-only ausgewiesen.

GDELT, RSS und Military-Aircraft laufen im neu gebauten `data-ingestion-spark`-
Container der ausgewählten ODIN-Umgebung. 36 Stunden Live-GDELT erzeugten bei mehr
als 17.000 Locations keinen Null-Island-Treffer. Der aktuelle Container wurde nach
`c947dd9` erneut gebaut und projiziert neue Conflicts mit null Derivationsrevision.
Die fünf bestehenden Pre-Fix-Conflicts wurden nicht ohne Apply-/Backup-Gate repariert.

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
Deklaration existiert. Der bestehende `apply_phase2()`-Runner liest beide Dateien und
wendet damit auf einer frischen Instanz GDELT- und Spatial-Indizes gemeinsam an. Die
zentrale Spatial-Datei ist dafür explizit in Wheel und Container enthalten; ein
statischer Runner-Test friert diese Ownership ein.

Der read-only Smoke ist vorbereitet:

```bash
cd services/data-ingestion
uv run python -m graph_integrity.cli spatial-index-smoke
```

Er gibt maschinenlesbare `EXPLAIN`-Evidence aus und failt, wenn ein vorgesehener
Composite-Index nicht gewählt wird. Jede Probe bindet Scope und Derivationsrevision
und fordert zusätzlich `spatial_conflict = false`. Der reale Lauf gegen Neo4j 5.26.23
meldete `all_expected_indexes_used=true` und für Country, Admin-1 und Admin-2 jeweils
einen `NodeIndexSeek`; der Conflict-Ausdruck blieb der verbindliche Post-Seek-Filter.

### Backfill und Re-Enrichment

- Dry-run und Apply sind explizit und gegenseitig exklusiv.
- Apply verlangt ein content-adressiertes, frisch erneut geprüftes Dry-run-Reportfile.
- Cursor sind stabil nach `loc_key`; Checkpoints sind nach Jobart, Lane und
  Ziel-Derivationsrevision getrennt.
- Ein Checkpoint wird erst nach einem vollständig angewandten atomaren Batch
  fortgeschrieben; Wiederholung nach Crash ist idempotent.
- Konflikte erhalten nur Audit-/Conflict-Felder; bestehende Roh-/Scope-Felder bleiben
  unangetastet. Eine eventuell alte `spatial_derivation_revision` wird entfernt,
  sodass der Batch-Pfad sie nicht in den Composite-Indizes belässt. Seit `c947dd9`
  gilt dieselbe Nullung für neue Forward-Writes; bestehende Pre-Fix-Zeilen bleiben bis
  zu einem genehmigten Repair sichtbar. Unresolved/invalid werden nicht geschrieben.
- Source-Null-Island-Sentinels werden als `invalid_coordinate` gezählt und niemals als
  resolvable oder als Write ausgewiesen.
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
- Review: Raw-Fallback-Import fehlte, vier Aircraft-Guard-Tests, drei
  Runner-/Packaging-Tests und sechs Conflict-/Backfill-/Smoke-Tests waren rot.

Grüne Nachweise:

- WO2 betroffene Writer-/Runtime-Suites: **120 bestanden**.
- WO3 Migration/Plan-Smoke fokussiert: **14 bestanden**.
- Graph-/Spatial-Fokus nach WO4: **109 bestanden**.
- Review-Fokus: **57 bestanden** in vier getrennten Läufen.
- Operationaler VERIFY-Fokus am 2026-08-08: **27 bestanden**
  (Migration, Plan-Smoke, Batch und CLI).
- Pre-06B-Conflict-Fix am 2026-08-09: RED mit **2 fehlgeschlagen**, danach
  **76 bestanden** im betroffenen Normalizer-/Writer-/Batch-Fokus.
- Vollständiger Data-Ingestion-Lauf nach dem Pre-06B-Fix:
  **1.365 bestanden, 1 bedingter Integration-Skip, 17 `live` deselected**;
  Ruff grün.
- Vollständiger Data-Ingestion-Lauf nach Review-Fix:
  **1.345 bestanden, 1 bedingter Integration-Skip, 17 `live` deselected**.
- `uv run ruff check .`: **grün**.

Der Skip ist der vorbestehende, bedingte GDELT-Integrationstest bei nicht laufenden
Dev-Compose-Services. Die 17 deselected Tests tragen den expliziten `live`-Marker.

## Offene 06A-Betriebsgates — blockieren exact

Indexmigration und reale `EXPLAIN`-Evidence sind seit dem Nachlauf belegt. Der
repräsentative Dry-run belegt außerdem 99,61 % GDELT- und 100 % RSS-Country-Coverage
der addressierbaren Records sowie 0 % stale-compatible für alle vier Jobs. Er hat
jedoch folgende verbleibende Gates sichtbar gemacht:

1. aktueller Backup/Restore-Punkt für den bereits durch Forward-Writer mutierten
   Zielgraph vor jedem Backfill-Apply;
2. vollständige, reviewte Dry-runs für jede tatsächlich anzuwendende Lane/
   Ziel-Derivationsrevision; bisher wurde repräsentativ
   `spatial-derive-v1-4d1de888e0c7` geprüft;
3. Outcome-Review für 140 unresolved GDELT- und 10 unresolved RSS-Locations, bevor
   die 100-%-Recognized-Code- und No-Unknown-Default-Gates als bestanden gelten;
4. Entscheidung/Integration für `backend_incident`; der Zwei-Record-Snapshot ist
   keine Exact-Promotion-Evidence;
5. stabile IDs beziehungsweise explizite Disposition für neun Legacy-Aircraft-
   Locations. Der Aircraft-Report ist dadurch `complete=false`; sieben keyed
   Beobachtungen sind im aktuellen Containment-Katalog unresolved;
6. content-adressierte Apply-Freigabereports, Daten-Apply und anschließendes
   Response-Accounting je zu aktivierender Lane;
7. explizite Disposition der fünf bestehenden Pre-Fix-Conflicts; unabhängig davon
   bleibt `spatial_conflict = false` im Read-Contract verpflichtend;
8. explizite Exact-Aktivierungsentscheidung für Plan 06B.

Die Nutzerfreigabe vom 2026-08-08 deckte Stackstart, Image-Rebuild/-Recreate, die
additive Indexmigration und Zero-Write-Dry-runs in der ausgewählten ODIN-Umgebung ab.
Sie deckt keinen Backup-Eingriff, kein Backfill-Apply, kein Deployment in eine weitere
Umgebung und keine Exact-Aktivierung ab.

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
- Pre-06B-Runtime-HEAD: `c947dd9`; der Fix ist im laufenden
  `data-ingestion-spark`-Container der ausgewählten ODIN-Umgebung verifiziert.
- Es wurde kein PR erstellt und nichts nach `main` gemerged.
