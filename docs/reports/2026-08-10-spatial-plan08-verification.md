# Spatial Scope Plan 08 — Verification and bounded completion

**Datum:** 2026-08-10

**Start-HEAD:** `2efd953 docs(spatial): hand off Plan 08`

**Mandatory Start Record:** `c1fe14e docs(spatial): record Plan 08 capability gate`

**Implementierung:** `4d4010a feat(worldview): scope registered point layers`

**Review-Remediation:** `66e4cbf refactor(worldview): enforce spatial capability invariants`

**Status:** Work Order 1 abgeschlossen; Work Order 2 gestoppt; Admin-2 blockiert;
3D deferred; keine operative Capability-Promotion

## Ergebnis

Plan 08 aktiviert genau den im
[Mandatory Start Record](2026-08-10-spatial-plan08-start-record.md) ausgewählten
neuen Pfad: `earthquakes` als strikten clientseitigen `occurs-in`-Punktlayer über
das feste katalogrevisionsgebundene Containment-Asset.

Die Umsetzung besteht aus vier zusammenhängenden, aber getrennt testbaren Seams:

1. `SpatialContainmentPort` veröffentlicht `building`, `ready` oder `unavailable`
   für genau eine lokale `stateRevision`.
2. Der interne Containment-Controller teilt den vorhandenen `BoundaryAssetStore`,
   baut einen festen `BoundaryGeometryIndex` und verwirft alte Generationen vor
   dem semantischen Scope-Publish.
3. Der imperative Earthquake-Adapter filtert den vollständigen Feed vor Viewport-
   Auswahl und Render-Cap, zählt jede Exclusion-Klasse und verändert keine
   semantischen Records.
4. Die geschlossene Registry ist die einzige Claim-Quelle für alle 16
   `LayerVisibility`-Keys und wird sowohl vom WorldView-Runtime-Gate als auch von
   sichtbaren Layer-Badges konsumiert.

Die Architektur folgt damit dem `codebase-design`-Gate: Geometrie-, Asset-,
Generation- und Disposal-Komplexität liegt hinter dem kleinen
`SpatialContainmentPort`; Cesium-Layer kennen weder Katalogauflösung noch
Precision-Entscheidungen.

## Aktivierte Semantik

### Fester Containment-Lebenszyklus

- Jeder semantische Commit invalidiert die bisherige Lease und den bisherigen
  Index synchron, bevor der neue Scope-Snapshot publiziert wird.
- Nichtglobale Scopes publizieren zunächst `building`; fehlt der Descriptor oder
  schlägt Laden/Validierung fehl, folgt `unavailable` ohne BBox-Fallback.
- `world` publiziert ebenfalls zuerst `building`, damit ein imperativer Consumer
  alte Resultate vor dem Scope-Label-Wechsel löscht, und danach microtask-basiert
  einen synthetischen `ready`-Index für alle validen WGS84-Punkte.
- Ein verspäteter Asset-Abschluss verliert über Generation plus `AbortSignal` alle
  Publish-Rechte und gibt seine Lease frei.
- Kamera-/Render-LOD kommt im Port nicht vor und kann den festen Index nicht
  ersetzen.
- `reset` und `dispose` brechen Loads ab und geben die gehaltene Lease frei.

### Strikter Earthquake-Punktadapter

- Klassifikationen: `inside`, `outside`, `boundary-uncertain` und ungültige
  Koordinate.
- Nur `inside` gelangt in den Renderpfad. Alle anderen Klassen werden separat
  gezählt; `building` und `unavailable` halten sämtliche Records zurück.
- Die ursprünglichen Earthquake-Objekte bleiben referenzidentisch und werden weder
  erweitert noch eingefroren oder anderweitig mutiert.
- Der Adapter läuft innerhalb des imperativen Collection-Callbacks, nicht im
  React-Render. Die vorhandene `BillboardCollection` und das Render-Cap von 250
  bleiben erhalten.
- Ein Containment-Publish triggert einen imperativen Redraw; dadurch verschwinden
  alte Punkte schon beim Invalidierungsereignis.

### Geschlossene Runtime-Matrix

Die Registry enthält exakt die 16 Runtime-Keys und pro Zeile Relation, Verhalten,
Precision, unterstützte Scope-Kinds, Stale-Policy und sichtbares
Unsupported-Verhalten.

- `earthquakes`: `strict`, `point-in-boundary`, Invalidierung am semantischen
  Commit.
- `events`: bestehender strikter CHRONIK-Pfad, ehrlich als `bbox-approximate` und
  `response-scope-token` ausgewiesen.
- `satellites` und `cityBuildings`: sichtbarer `global context`.
- `countryBorders`: sichtbare `scope presentation`, kein Exact-Datenclaim.
- Alle elf nicht ausgewählten Toggle-Layer: nur im World-Scope verfügbar; in
  Country/Admin-Scope werden Fetch und Render fail-closed deaktiviert und als
  `unavailable in scope` beschriftet.
- Während initialer Deep-Link-Hydration bleiben nur deklarierte globale
  Kontextlayer sichtbar; es gibt keinen World-only-Datenflash.

Der separate, immer gemountete Recon-/Terrain-/Graticule-/HUD-Kontext bleibt wie im
Start Record dokumentiert global und wird nicht als analytisches `occurs-in`
ausgegeben.

## TDD-Evidenz

### RED

Der fokussierte Lauf vor Produktionscode war absichtlich rot:

```text
Test Files  6 failed (6)
Tests       24 failed | 33 passed (57)
```

Die Fehler lagen ausschließlich an den neu geforderten Seams:

- `containment.ts` und `pointLayerSpatialAdapter.ts` fehlten;
- die alte Registry hatte acht grobe Klassen statt 16 Runtime-Keys;
- Controller, Earthquake-Renderer und Layer-Badges konsumierten die neuen
  Verträge noch nicht.

Ein zusätzlicher RED/GREEN-Zyklus erzwang für `world` erst synchrones `building`
und dann `ready`, damit kein imperativer World-Redraw unter einem alten
Non-World-Label stattfinden kann.

### GREEN und Integration

- erster fokussierter GREEN-Lauf: 6 Dateien, 68/68 Tests;
- finaler kompletter Frontend-Lauf: 106 Dateien, 594/594 Tests;
- eigener Flag-on-WorldView-Test beweist bei Country-Scope:
  `flights=false`, `satellites=true`, `earthquakes=true` mit Adapter sowie die drei
  zugehörigen Registry-Badges;
- Deep-Link-Hydrationstest beweist den fehlenden World-only-Flash;
- TypeScript strict, ESLint und Produktionsbuild sind grün.

## High-Cardinality-/Heap-Messung

Fokussierter hermetischer Vitest-Lauf am finalen Feature-Commit:

```text
input_count                         30,000
included_count                      10,000
excluded_outside_count              10,000
excluded_boundary_uncertain_count   10,000
downstream_render_count                250
filter duration                     18.771 ms
16 retained result sets          5,258,008 bytes
retained heap per pass              328,626 bytes
```

Der Lauf verwendet den echten RBush-basierten Containment-Controller und den echten
Punktadapter. Die 16 Resultsets werden absichtlich gehalten, damit die
`heapUsed`-Differenz nicht durch sofortige Garbage Collection verschwindet. Die
Budgets im Test sind 750 ms, 64 MiB insgesamt und 4 MiB pro gehaltenem Pass.

Dies ist eine Node/Vitest-Filter-/Heap-Messung, keine neue GPU- oder
Production-Browser-Frame-Messung. Für den unveränderten Cesium-Collection-Pfad gilt
weiter die vorhandene
[Plan-05-Browser-/Soak-Evidenz](2026-08-07-spatial-plan05-admin1-prefetch-canary.md);
der Plan-08-Test belegt zusätzlich, dass höchstens 250 Earthquake-Records in diesen
Pfad gelangen. Es wird kein neuer Production-Browser-Cache-Peak behauptet.

## Katalog- und Coverage-Gate

Der unveränderte veröffentlichte Katalog wurde offline erneut geprüft:

```text
spatial-v1-fe9828dcda05: pass (41 assets, 4509895 bytes)
audit status: pass
scopes: 204 = 1 world + 176 country + 27 admin1 + 0 admin2
containment descriptors: 38
largest asset: 820,372 wire bytes / 2,654,336 estimated heap bytes
```

Die Audit-Limits bleiben 4 MiB Wire, 16 MiB Heap, 256 Features, 2.048 Ringe und
16.384 Vertices pro Ring. Es wurde kein Katalog gebaut, publiziert oder verändert.

`spatial-v1-e76a16bff799` bleibt im Mandatory Start Record korrekt als historischer
Plan-05-Canary-Nachweis genannt. Der aktuelle veröffentlichte Katalog
`spatial-v1-fe9828dcda05` enthält dieselben 38 Containment-Deskriptoren für die
38/38 Gates; die Änderung von 68 auf 41 Assets betrifft Render-LODs und nicht die
Containment-Fläche. Der historische Canary maß maximal 0 m Ableitungsfehler; für den
aktuellen Katalog liefen hier `verify` und `audit`, keine neue Fehlermessung. Der
Runtime-Adapter liest das jeweilige `maxErrorMeters` aus dem Deskriptor und schließt
das resultierende Fehlerband konservativ als `boundary-uncertain` aus.

Die vorhandene
[Neo4j-Evidenz](2026-08-09-spatial-plan06b-review-remediation.md) bleibt bei 18/18
statischen `EXPLAIN`-Templates, aber ohne Admin-1-/Incident-/Admin-2-Promotion. Die
[Qdrant-Evidenz](2026-08-10-spatial-plan07a-review-remediation.md) weist den realen
Snapshot weiterhin ohne Spatial-Indizes und Spatial-Payloads aus. Diese Evidenz
blockiert Admin-2 weiterhin; sie wurde nicht durch eine hermetische Frontend-Suite
umgedeutet.

## Whole-Program-Qualitätsgate

| Service | Ergebnis |
|---|---|
| Frontend | 594/594 Tests; ESLint sauber; TypeScript strict sauber; Vite-Produktionsbuild erfolgreich |
| Backend | 574/574 Tests; Ruff sauber; MyPy sauber (88 Source Files) |
| Intelligence | 449/449 Tests |
| Data Ingestion | 1368 bestanden, 1 übersprungen, 17 deselected; Ruff sauber |
| Katalog | `verify` und `audit` für `spatial-v1-fe9828dcda05` bestanden |
| Repository | `git diff --check` sauber |

Der Vite-Build meldet lediglich den bereits bekannten Chunk-Size-Hinweis; es gibt
keinen Buildfehler.

## Acceptance-Matrix für tatsächlich aktivierte Arbeit

| Gate | Ergebnis | Evidenz |
|---|---|---|
| Mandatory Start Record vor Produktionscode | pass | Commit `c1fe14e` |
| geschlossene Registry für 16/16 Toggle-Layer | pass | Matrix- und Flag-on-Integrationstests |
| alter Index vor neuem semantischem Render ungültig | pass | Controller-/Containment-Reihenfolgetests |
| Generation/Abort/Lease-Release | pass | stale Completion, Reset und Disposal Tests |
| World-Semantik ohne Mixed-Scope-Frame | pass | `building → ready` World-Test |
| Missing Asset ohne BBox-/Global-Fallback | pass | `unavailable`- und Pack-Rejection-Tests |
| strict Boundary-Uncertain-Exclusion plus Accounting | pass | Punktadapter- und 30k-Benchmarktest |
| Kamera-LOD unabhängig vom Containment | pass | Adapter-/Presentation-Lifetime-Test |
| Bulk-Cesium ohne Entity-API-Migration | pass | bestehende `BillboardCollection`, Cap-Test |
| keine semantische Datenmutation | pass | Referenz-/Freeze-Test |
| Unsupported/global-context sichtbar | pass | Badge- und WorldView-Integrationstest |
| Track/Polygon/Raster-Neuaktivierung | gestoppt | kein ausgewählter Kandidat im Start Record |
| Admin-2 | blockiert | 0 Admin-2-Scopes; keine Source-/Coverage-Evidenz |
| 3D-Metrik | deferred | kein akzeptierter Metric Record |

## Bewusste Nicht-Abschlüsse

Plan 08 schließt Spec 14 §29 nicht pauschal:

- Plan 05D und die Legacy-Country-Löschung wurden nicht ausgeführt.
- `TASK-123` bleibt offen; Plan 08 erfüllt davon ausschließlich Kriterien 6 und 9.
- Es gab keine Neo4j-/Qdrant-Mutation, Re-Enrichment-, Catalog-Publish- oder
  Capability-Promotion.
- Es gab keinen neuen echten Production-Browser-/GPU-Soak. Die neue Arbeit besitzt
  hermetische High-Cardinality-Evidenz und nutzt den bereits vermessenen, unveränderten
  Bulk-Cesium-Pfad.

Damit ist der ausgewählte Plan-08-Work-Order vollständig implementiert und
verifiziert; die gestoppten, blockierten und deferred Zweige bleiben ausdrücklich
geschlossen.

## Worktree- und Delivery-Audit

Die beim Start vorhandenen fremden Änderungen blieben außerhalb aller Commits:

```text
 M docs/CONTAINER-STATUS.md
 M scripts/spark/odin-spark-vllm.sh
?? docs/superpowers/plans/2026-08-10-task-104-phase2-qdrant-bm25-hybrid.md
```

Es erfolgte kein Push, Pull Request, Merge, Deployment oder externer Write.
