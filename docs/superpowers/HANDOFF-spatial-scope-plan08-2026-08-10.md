# HANDOFF — Spatial Scope Plan 07B abgeschlossen → Plan 08

**Datum:** 2026-08-10

**Nächster Chat:** Plan 08 — Mandatory Start Record, danach nur die unabhängig
freigegebenen Layer-/Admin-2-/3D-Branches strikt testgetrieben

**Branch:** `feat/spatial-plan03`

**Repo:** `/home/deadpool-ultra/ODIN/OSINT`

**Plan-07B-Abschluss-HEAD vor diesem Handoff:** `6854cf0`

**Remote-Basis vor diesem Handoff:** `origin/feat/spatial-plan03` bei `a97708d`

**Divergenz vor diesem Handoff-Commit:** ahead 8, behind 0

**Status:** Die Pläne 00A bis 07B sind implementiert, reviewed und service-lokal
grün. Das Slice-7-Exit-Gate hält. Plan 08 ist noch nicht begonnen und ist weder ein
automatisches Admin-2-Rollout noch ein 3D-Dekorationsauftrag. Seine drei
Aktivierungszweige sind unabhängig; jeder beginnt mit dem verpflichtenden
Auswahl-/Evidenzrecord und bleibt bei fehlender Evidenz fail-closed.

## TL;DR — wo die nächste Session beginnt

Der kanonische nächste Plan ist
[Plan 08 — Additional Layers, Admin-2 and 3D](plans/2026-08-01-spatial-scope/08-layers-admin2-and-3d.md).
Er beginnt mit dem **Mandatory Start Record**, nicht mit Produktionscode.

Der bisherige V1-Stand liefert eine belastbare Performance-, Catalog- und
Truthfulness-Basis. Die branch-spezifischen Voraussetzungen sind jedoch bewusst noch
nicht erfunden:

- Es ist noch kein erster strikter Punktlayer für Work Order 1 freigegeben.
- Es ist noch kein vollständiges Set weiterer Track-/Polygon-/Rasterlayer für Work
  Order 2 ausgewählt.
- Es gibt weder eine reviewed Admin-2-Quelle noch ein ausgewähltes Theater oder einen
  gebauten Admin-2-Pack.
- Neo4j und Qdrant besitzen keine ausreichende operative Admin-2-Coverage.
- Für Work Order 4 ist keine Metrik mit Einheit, Zeitbasis, Skala, Missing-Semantik,
  Legende und Analystennutzen freigegeben. **3D startet deshalb ausdrücklich als
  deferred.**

Die nächste Session darf die lokalen Kandidaten inventarisieren, Evidenz
zusammenführen und einen prüfbaren Auswahlrecord vorschlagen. Sie darf ohne diesen
Record keinen Capability-Claim, keine Admin-2-Quelle, kein Theater und keine
3D-Metrik still auswählen oder aktivieren.

Die im 07B-Review genannten Produkt-Follow-ups — Graph-Allowlist-Erweiterung,
Frontend-Namensbereinigung, sichtbares Rendering der Run-Attribution und ein
authentisierter Briefing-Run-Receipt — sind **nicht** Plan 08 und dürfen nicht
beiläufig in diesen Slice gezogen werden.

## Pflichtstart in der nächsten Session

Vor jeder Änderung vollständig lesen:

1. `AGENTS.md`
2. `CLAUDE.md`
3. dieses Handoff
4. [Implementation-Planindex](plans/2026-08-01-spatial-scope-implementation.md)
5. [Plan 08](plans/2026-08-01-spatial-scope/08-layers-admin2-and-3d.md)
6. [Spec 04 §10.9 — SpatialContainmentPort](specs/2026-07-31-spatial-scope-drilldown/04-spatial-catalog-contracts.md)
7. [Spec 05 — Boundary-Build, Antimeridian und Budgets](specs/2026-07-31-spatial-scope-drilldown/05-boundary-build-and-antimeridian.md)
8. [Spec 06 §13 — Cesium-/Layer-Semantik](specs/2026-07-31-spatial-scope-drilldown/06-cesium-and-layer-semantics.md)
9. [Spec 11 §19 — UX und 3D-Metriken](specs/2026-07-31-spatial-scope-drilldown/11-ux-and-3d-metrics.md)
10. [Spec 12 — Fehler, Security und Observability](specs/2026-07-31-spatial-scope-drilldown/12-errors-security-and-observability.md)
11. [Spec 13 Slice 8](specs/2026-07-31-spatial-scope-drilldown/13-implementation-and-tdd-slices.md)
12. [Spec 14 §§27/29 — Rollout und Acceptance](specs/2026-07-31-spatial-scope-drilldown/14-rollout-and-acceptance.md)
13. [Plan-03-Flag-on-Canary](../reports/2026-08-06-spatial-plan03-flag-on-canary.md)
14. [Plan-05-Admin-1-/Prefetch-Canary](../reports/2026-08-07-spatial-plan05-admin1-prefetch-canary.md)
15. [Plan-06A-Neo4j-Verifikation](../reports/2026-08-08-spatial-plan06a-neo4j-verification.md)
16. [Plan-06B-Review-Remediation](../reports/2026-08-09-spatial-plan06b-review-remediation.md)
17. [Plan-07A-Abschlussverifikation](../reports/2026-08-10-spatial-plan07a-verification.md)
18. [Plan-07A-Review-Remediation](../reports/2026-08-10-spatial-plan07a-review-remediation.md)
19. [Plan-07B-Start-Handoff](HANDOFF-spatial-scope-plan07b-2026-08-10.md)
20. `TASKS.md`, besonders das weiterhin offene `TASK-123`

Dann den Zustand neu prüfen:

```bash
git status --short --branch
git log -12 --oneline --decorate
git rev-list --left-right --count origin/feat/spatial-plan03...HEAD
```

Der Statusblock im Implementation-Planindex ist historisch nicht vollständig
fortgeschrieben. Er darf nicht dazu führen, bereits abgenommene Slices neu zu öffnen.
Für den Ausführungsstand gelten die versionierten Handoffs, Commits und
Verifikationsreports; für Abhängigkeiten, Whole-Program-Checks und Planverträge bleibt
der Index kanonisch.

Aktuell sind drei fremde Worktree-Einträge sichtbar. Nicht ändern, stagen,
zurücksetzen, formatieren oder in einen Commit aufnehmen:

- `docs/CONTAINER-STATUS.md`
- `scripts/spark/odin-spark-vllm.sh`
- `docs/superpowers/plans/2026-08-10-task-104-phase2-qdrant-bm25-hybrid.md`

Kein PR, Push, Merge nach `main`, Deployment, Live-/Staging-Write, Qdrant-Index- oder
Re-Enrichment-Apply, Neo4j-Backfill/Registry-Activation oder Catalog-Publish ohne
ausdrücklichen Auftrag.

## Abgenommene Plan-07B-Commits

```text
29975cd feat(backend): resolve intelligence spatial tokens
7f4fdff feat(intelligence): pin spatial scope in agent state
39720d7 feat(munin): enforce scope in retrieval tools
859b3b2 fix(munin): block unscoped tool capabilities
81f9206 feat(munin): report spatial application truthfully
288b6ca fix(backend): clear stale spatial run application
93eaadb fix(spatial): tighten reviewed runtime contracts
6854cf0 fix(backend): discard browser spatial attribution
```

## Verbindlicher Abschlussstand aus Plan 07B

### Enforcement und kein Fallback

- Backend löst Browser-Referenzen serverseitig zum vollständigen
  `SpatialScopeTokenV1` auf. Der Browser liefert nur `scope_key`,
  `catalog_revision` und `boundary_policy`.
- Scope, Relation und Bild-URL kommen ausschließlich aus gepinntem Agent-State.
  Modellseitige Tool-Schemas besitzen keine entsprechenden Override-Felder.
- Nicht-globale Graph-Reads verwenden nur die statische Allowlist. Ein nicht
  unterstützter Intent liefert `SPATIAL_SCOPE_UNSUPPORTED` und erzeugt weder
  Free-Cypher noch einen Query-Aufruf.
- Qdrant-Filter bleiben mit der Corpus-Policy verschachtelt. Missing, partial,
  stale, no-hit oder Fehler lösen keinen ungefilterten Retry aus.
- Capability-Binding und Runtime-Guards blockieren nicht erlaubte GDELT-, RSS- und
  Vision-Aufrufe vor externem I/O.
- `spatial_relation` bleibt im internen Intelligence-Vertrag absichtlich required.
  Die Lock-step-Deploy-/Rollback-Reihenfolge steht im
  [Spatial-Intelligence-Runbook](../runbooks/spatial-intelligence-contract-deploy.md).

### Trusted Run-Attribution

`Report.spatial_application` ist der Snapshot des **letzten erfolgreich am Report
persistierten Runs**, keine unveränderliche Report-Identität:

- Ein ungescopter späterer Run löscht einen alten Snapshot explizit bis auf
  Storage-Ebene.
- Schlägt das Schreiben der Application fehl, wird kein `result`-Event ausgesendet;
  der Pfad ist fail-closed, weil eine veraltete Attribution lügen würde.
- Der Munin-Message-Write bleibt best-effort, weil das Result-Event den Text weiterhin
  trägt.
- Browser-Payload aus
  `POST /api/almanac/countries/{id}/briefing/save` kann keine
  `spatial_application` persistieren, auch dann nicht, wenn die Scope-Identität zu
  einem echten Server-Token passt. Status, Completeness und Coverage wären weiterhin
  fabrizierbar.
- Nur ein explizit vertrauenswürdiger Server-Aufrufer darf
  `build_hydration_patch(..., trusted_spatial_application=...)` setzen. Der
  server-to-server `/api/intel/query`-Pfad mit `report_id` ist derzeit der einzige
  echte Producer.
- Country-Dossiers aus dem zustandslosen Generate-then-Browser-Save-Pfad tragen daher
  ehrlich `spatial_application = null`. Eine Attribution dort benötigt später einen
  authentisierten, server-owned Run-Receipt; sie darf am Save-Seam nicht rekonstruiert
  werden.

Der Produktliteral `not-applicable` wurde aus den Spatial-Run-Verträgen entfernt und
ist durch Negativtests gesperrt. Vision verwendet einen echten Runtime-Guard statt
`assert`; der Legacy-`region`-Parameter wird nur noch als boolesches
`deprecated_region_supplied` observiert, nie als Freitext geloggt.

## Verifizierte Baseline vor Plan 08

Die 07B-Werte wurden über drei Reviewrunden unabhängig nachgefahren. Nach dem letzten
Fix war der vollständige Stand:

| Service/Gate | Ergebnis |
|---|---|
| Backend | 574 passed; Ruff sauber; strict MyPy über 88 Module sauber |
| Intelligence | 449 passed; Ruff sauber; Vision-Guard unter `python -O`: 18 passed |
| Frontend | 560 passed in 102 Dateien; ESLint und TypeScript sauber |
| Data Ingestion | 1368 passed, 1 skipped, 17 deselected; Ruff sauber |
| Branch vor Handoff | ahead 8, behind 0; Merge-Base zu `origin/feat/spatial-plan03` sauber |

Der Data-Ingestion-Lauf wurde beim Erstellen dieses Handoffs erneut ausgeführt. Der
Skip ist der vorhandene umgebungsabhängige GDELT-Integrationstest; die 17
Deselections sind die vorhandenen `live`-Tests. Es wurde kein Skip ergänzt.

Über die drei 07B-Reviewrunden sind alle Befunde geschlossen:

| Befund | Abschluss |
|---|---|
| Staler Application-Snapshot nach globalem Run | expliziter Null-Pfad und fail-closed Persistenz |
| Browser-gelieferte Attribution | am Hydration-Seam strikt verworfen |
| Totes `not-applicable` | aus Produktvertrag entfernt, Negativtest |
| Optimierungsabhängiger Vision-`assert` | echter Runtime-Check, unter `-O` geprüft |
| Legacy-`region` ohne Observability | nur boolesches Vorhandensein |
| Required `spatial_relation` im Rollout | bewusster Snapshot-Vertrag plus Runbook |

## Mandatory Start Record — aktueller Evidenzstand

### 1. Slice-3–7-Evidenz: vorhanden und verlinkt

Die oben verlinkten Reports bilden die verpflichtende Ausgangsevidenz:

- Aktiver immutable V1-Katalog:
  `spatial-v1-e76a16bff799`
- 204 Scopes: 1 World, 176 Countries, 27 ausgewählte ukrainische Admin-1-Scopes
- 68 Assets, 5.355.159 Bytes
- Containment-Audit: 38/38 bestanden, maximaler Fehler 0 m
- Firefox/WebGL2-Canary: Cold Visual p95 292 ms, Maximum 641 ms
- Warm Core Commit: 7–20 ms
- 100 Scope-Transitionen ohne monotones Ressourcenwachstum

Diese Zahlen sind korrekt, aber eng zu interpretieren:

- Der Browser-Canary lief im Vite-DEV-Build, nicht in einem instrumentierten
  Production-Bundle.
- Der nach Plan 05 korrigierte transiente Cache-High-Water-Zähler ist per Unit- und
  Regressionstest belegt; der Browser-Canary wurde danach nicht erneut ausgeführt.
  Das Handoff behauptet daher keinen korrigierten transienten Browser-Peak.
- Plan 05D bleibt ein separater, blockierter Deployment-Cleanup. Weder
  `VITE_SPATIAL_SCOPE_ENABLED` noch der Legacy-Country-Pfad dürfen in Plan 08 ohne
  Default-on-/Soak-/Rollback-/Phase-D-Evidenz entfernt werden.

### 2. Neo4j: Compiler-/Plan-Evidenz vorhanden, Admin-2-Coverage fehlt

Plan 06B hat 18/18 statische Exact-Templates read-only per `EXPLAIN` mit
Indexoperator verifiziert. Der damalige Smoke zeigte:

- `country:USA`: candidate/included 13.316/13.316
- `country:IND`: candidate/included 1.696/1.696
- Admin-1: nur 27 scope-keyed Locations über 15 Scopes, nicht promotierbar
- Incidents: 0/11.793 mit scope-keyed Location, Promotion blockiert
- Admin-2: keine ausreichende operative Coverage

Die Exact-Registry ist weiterhin default-leer. Syntax-/Indexnachweis ist keine
Coverage-Attestation. Vor einer Admin-2-Aktivierung verlangt Plan 08 für jedes
ausgewählte Theater die Plan-06-Coverage, Query-Plan-/Accounting-Evidenz und die
explizite Aktivierungsentscheidung. Es gibt keinen erlaubten globalen Fallback.

### 3. Qdrant: V1-Vertrag vorhanden, operative Aktivierung fehlt

Plan 07A hat Payload-, Index-, Filter-, Coverage- und restartbare
Re-Enrichment-Verträge implementiert. Der letzte unabhängige read-only Snapshot
zählte 1.025.197 Points, aber nur neun Corpus-/Fulltext-Indizes:

- keine Spatial-Indizes
- keine Spatial-Payloads
- kein Re-Enrichment-Apply
- keine Exact-Promotion

Vor Admin-2-Retrieval bleiben eine autorisierte Indexmigration, ein vollständiger
Dry-run, Review und approval-gebundenes Apply sowie ein frischer realer
Lane-Coverage-Snapshot erforderlich. Der wirksame Gap
`(stale + unprojected + inconsistent) / total` über 1 Prozent blockiert. Plan 08
darf diese Operatorhandlungen nicht als normalen Implementierungsschritt ausführen.

### 4. Branch-spezifische Auswahl: offen beziehungsweise deferred

| Plan-08-Zweig | Status beim Handoff | Harte nächste Voraussetzung |
|---|---|---|
| WO1 Registry + Punktadapter | Auswahl offen | vollständige Enabled-Layer-Inventur, autoritative Relation und generation-safe Seam; genau einen ersten strict Point Layer reviewen |
| WO2 Track/Polygon/Raster | Auswahl offen | pro Layer echte Relation, Precision, Stale-/Unsupported-Verhalten und vorhandenen Bulk-Seam belegen |
| WO3 Admin-2 | blockiert | reviewed Theater + Source-Lock-Änderung + Raw-Feature/Ring/Cardinality-/Budget-Feasibility; danach getrennte Plan-06/07-Coverage |
| WO4 3D | **deferred** | nur mit freigegebener Metrik samt Einheit, Zeitpunkt, Skala, Missing-Semantik, Legende, Provenance und Analystennutzen öffnen |

Ein blockierter Zweig blockiert die unabhängig akzeptierten Zweige nicht.

## Bestehende Frontend-Seams — Inventurstart, keine Auswahl

`services/frontend/src/spatial/layerScopePolicy.ts` enthält derzeit acht grobe
Capability-Zeilen:

```text
chronik-events
geo-events-hotspots-earthquakes
aircraft-vessel-tracks
satellites
cables-pipelines
facilities
terrain-imagery-3d
country-admin-borders
```

Diese Aggregation ist noch **nicht** der geschlossene Plan-08-Nachweis für jeden
enabled Layer. Produktionsseitig nutzt nur `ChronikTimeline.tsx` den separaten
`chronikSpatialStatus`-Helper. Für
`LAYER_SPATIAL_CAPABILITIES`/`layerSpatialCapability` existiert am aktuellen HEAD
außerhalb der Tests kein Consumer.

`services/frontend/src/spatial/geometry.ts` stellt
`BoundaryGeometryIndex`, `createBoundaryGeometryIndex` und
`createSpatialChildGeometryIndex` bereit. Das Modul ist weiterhin nur aus Tests
importiert. Der in Spec 04 definierte `SpatialContainmentPort` existiert noch nicht
als Produktionssymbol. Work Order 1 muss den fixed, katalogrevisiongebundenen
Containment-Index testgetrieben als produktiven imperativen Seam verdrahten:

- alter Index wird beim semantischen Commit vor dem ersten neuen Render invalidiert;
- `building`/`unavailable` verbirgt alte strict-Ergebnisse;
- `inside`, `outside` und `boundary-uncertain` werden getrennt gezählt;
- `world` schließt jeden validen WGS84-Punkt ein;
- Kamera-LOD ändert den Containment-Index nie;
- Ergebnisse werden nicht in semantische Layerdaten zurückgeschrieben.

Vorhandene Bulk-Cesium-Komponenten sind lediglich Kandidaten für die Inventur, keine
vorweggenommene Freigabe. Dazu zählen unter anderem FIRMS, Earthquake, EONET, Event,
GDACS, Flight, MilAircraft, Ship, Refinery, Datacenter, CCTV, Recon, Pipeline und
Cable. Die nächste Session muss von den tatsächlich enabled Runtime-Toggles und
Registrierungen ausgehen, nicht nur von Dateinamen oder der groben Matrix.

### TASK-123 bleibt offen

Plan 08 ist der vorgesehene Ort für zwei noch offene Kriterien:

1. `spatial/geometry.ts` mit
   `BoundaryGeometryIndex`/`createSpatialChildGeometryIndex` produktiv im
   Plan-08-Containment-Adapter verdrahten **oder** vor 05D als tote Vorleistung
   entfernen.
2. `LAYER_SPATIAL_CAPABILITIES` erhält einen Produktions-Consumer für
   Layer-Badges/Scope-Verhalten **oder** wird vor 05D entfernt.

Plan 08 darf `TASK-123` nicht pauschal schließen. Die übrigen Paritäts-, A11y-,
Palette-, LOD- und Legacy-Cleanup-Kriterien bleiben bis zu ihrem jeweils belegten
Abschluss offen.

## TDD- und Commitreihenfolge für Plan 08

### Schritt 0 — Mandatory Start Record

1. Alle enabled Layer aus Runtime-Registrierung, Toggles und Komponenten
   inventarisieren.
2. Für jeden Kandidaten Relation, Modus, Precision, Coverage-/Zeitbasis,
   Stale-Invalidation, Unsupported-Verhalten, Bulk-Cesium-Seam und erwartbare
   Cardinality dokumentieren.
3. Nur Kandidaten mit autoritativer Semantik und generation-safe Invalidation
   auswählen; alle anderen sichtbar unsupported/global-context lassen.
4. Admin-2 nur über eine reviewed Catalog-Plan-/Source-Lock-Auswahl öffnen und vor
   Code Feature-, Ring-, Vertex-, Wire-, Heap-, Error- und `<=256`-Pack-Budgets
   beweisen.
5. 3D bleibt deferred, solange kein vollständiger Metric Record accepted ist.
6. Den Record als versionierten Report ablegen. Fehlgeschlagene Branches dort
   ausdrücklich als gestoppt dokumentieren.

Der Auswahlrecord ist ein Design-/Activation-Gate. Eine Entscheidung mit neuen
Quellen, Theatern oder Produktsemantik darf nicht aus Dateinamen erraten werden.

### Work Order 1 — Registry und erster Punktadapter

RED zuerst: geschlossene Matrix für jeden enabled Layer sowie Lifecycle-,
Generation-, Containment-, World- und LOD-Unabhängigkeitsfälle. Danach minimal GREEN
mit imperativem Adapter über `SpatialContainmentPort`, `BillboardCollection`,
Filterung außerhalb des React-Renders und ohne semantische Datenmutation.

Commitgrenze:

```text
feat(worldview): scope registered point layers
```

### Work Order 2 — nur ausgewählte Tracks/Polygone/Raster

Pro Layer separat RED. Track-Intersection erhält sämtliche Originalpunkte und clippt
nicht irreführend. Polygone deklarieren `intersects`, `contained` oder
`unsupported`; Raster/globaler Kontext bleibt explizit unfiltered oder unavailable.
Serverfilter verwenden ausschließlich statische allowlistete Compiler. Jeder Adapter
besitzt Generation-Guard und ehrliches Response-Accounting.

Commitgrenze:

```text
feat(worldview): add truthful scoped layer adapters
```

### Work Order 3 — nur reviewed Admin-2-Theater

Erst RED für Lineage, vollständiges Child-Set, Preferred-Pick-LOD, Containment,
Budgets, Deep Link, Pick-Invarianz, Cache-/Primitive-High-Water und disabled
Affordance außerhalb der Auswahl. Ein Pack über 256 Features muss failen; niemals
implizit paginieren.

Danach Source-Lock/Katalog bauen und auditieren. Der generische Core-/Backend-/
Cesium-Pfad bleibt ohne Admin-2-Sonderfall. Falls Tiling nötig wird: sofort stoppen
und zuerst einen eigenen versionierten Vertrag entwerfen. Materialisierung und Query
erst nach theaterbezogener Plan-06/07-Coverage.

Commitgrenze:

```text
feat(spatial-scope): enable reviewed admin2 theaters
```

### Work Order 4 — optional, aktuell deferred

Nur nach accepted Metric Record öffnen. Der Presenter bleibt getrennt vom
`SpatialScopeModule`; Height/Colour codieren ausschließlich dokumentierte Werte.
Tests müssen Skala, Einheit/Zeitbasis, Clamping, Zero/negative/invalid/missing,
Legende, Snapshot-Revision, Generation, Reduced Motion, Accessibility und fehlende
Höhe ohne Daten beweisen. Keine dekorativen Arcs oder Extrusions.

Commitgrenze erst bei echter Auswahl:

```text
feat(worldview): visualize scoped <metric-name> in 3d
```

Jeder Work Order folgt AGENTS.md: RED dokumentieren, minimal GREEN, Refactor,
fokussiert verifizieren, dann eigener Conventional Commit. Nicht ausgewählte oder
blockierte Work Orders erhalten keinen leeren Platzhalter-Commit.

## Stop-Regeln und operative Grenzen

- Kein Layer darf seine eigene Approximation als exact labeln; die Registry besitzt
  den Claim.
- Kein non-globaler Pfad fällt auf globale Daten zurück.
- Ein fehlender Containment-Asset ist `unsupported`, niemals BBox-Ersatz.
- `boundary-uncertain` ist kein inside und darf nicht zu Neo4j-/Qdrant-Scope-Keys
  materialisiert werden.
- Track-Intersection ist Whole-object-Semantik; keine visuell irreführende
  Punktlöschung.
- Keine Cesium Entity API für Bulk-Daten; vorhandene primitive Collections und
  generation-safe Disposal-Seams verwenden.
- Keine Admin-2-Quelle außerhalb des reviewed Source Locks.
- Kein Pack über 256 still paginieren. Tiling erfordert vorab einen neuen,
  versionierten Vertrag.
- Kein Admin-2-Materialize/Query ohne eigenständige Plan-06-/07-Coverage je Theater.
- Keine 3D-Höhe, Farbe oder Arc ohne reale, belegte Metrik und Missing-Semantik.
- Keine Live-/Staging-Mutation, kein Catalog-Publish und keine Capability-Aktivierung
  aufgrund hermetischer Tests allein.
- Kein Plan-05D-Legacy-Cleanup im Rahmen von Plan 08.

## Whole-Program-Abschluss für Plan 08

Nach den tatsächlich aktivierten Branches:

1. Fokussierte Truthfulness-, Generation-, Containment- und Budgettests.
2. High-cardinality Frame-/Memory-Benchmark für neue Layeradapter.
3. Falls Admin-2 aktiviert wurde: Double-build/Audit, Direct Link, Cesium-Soak,
   Neo4j-/Qdrant-Pläne und vollständiges Accounting je Theater.
4. Falls 3D aktiviert wurde: Golden Data-to-Visual, Analystenreview,
   GPU-/Frame-Benchmark, Reduced Motion/A11y und Long-session Disposal-Soak.
5. Alle Service-Suites und statischen Checks aus dem Implementation-Planindex.
6. `git diff --check`, Fremdänderungsaudit und ein versionierter Abschlussreport.
7. Spec 14 §29 nur mit angehängter Evidenz schließen.

Plan 08 ist erst abgeschlossen, wenn jede **aktivierte** Capability eine ehrliche
Registry-Zeile und einen Stale Guard besitzt, Admin-2 die Catalog- und Datenbudgets
erfüllt, optionales 3D reale Metriksemantik zeigt und kein unsupported/partial Pfad
unsichtbar oder global wird.

## Bewusste Produkt-Follow-ups außerhalb Plan 08

- Graph-Allowlist für weitere scoped Intents erweitern.
- `SpatialApplicationV1` (Timeline) und `SpatialRunApplicationV1` (Intel-Run)
  sprachlich/typseitig entflechten sowie gemischte Request-Namenskonventionen
  bereinigen.
- `SpatialRunApplicationV1` analystensichtbar rendern.
- Authentisierten server-owned Run-Receipt für Country-Briefings entwerfen, damit
  der Generate-Pfad echte Attribution persistieren kann.

Sie sind nach 07B bewusst offen und benötigen eigene Produkt-/Planentscheidungen.
Plan 08 darf sie nur anfassen, wenn der Nutzer den Scope ausdrücklich erweitert.

## Session-Abschluss

Plan 07B ist merge-fähig und vollständig abgenommen. Dieses Handoff schließt die
Session dokumentarisch; es führt weder Push/PR/Merge noch Deployment oder
Datenmutation aus. Die nächste Session startet bei Plan 08 Schritt 0 und behandelt
jeden nicht belegten Capability-Claim fail-closed.
