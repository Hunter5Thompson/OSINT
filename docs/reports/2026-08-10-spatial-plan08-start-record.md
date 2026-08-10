# Spatial Scope Plan 08 — Mandatory Start Record

**Datum:** 2026-08-10

**Branch:** `feat/spatial-plan03`

**Start-HEAD:** `2efd953 docs(spatial): hand off Plan 08`

**Status:** Work Order 1 eingeschränkt freigegeben; Work Order 2 gestoppt;
Admin-2 blockiert; 3D-Metrik deferred

## Zweck und Aktivierungsregel

Dieser Record ist das verpflichtende Plan-08-Auswahlgate vor Produktionscode. Er
inventarisiert die tatsächlich gemounteten WorldView-Layer und trennt vier Dinge,
die nicht gegenseitig als Evidenz dienen dürfen:

1. eine vorhandene Darstellung auf dem Globus,
2. eine fachlich autoritative räumliche Relation,
3. einen generation-sicheren Scope-Seam,
4. eine operative Daten-/Coverage-Aktivierung.

Nur `earthquakes` erfüllt für den ersten neuen strikten Punktadapter alle nötigen
lokalen Bedingungen. Die Freigabe gilt ausschließlich für clientseitiges
`occurs-in` über das feste, katalogrevisionsgebundene Containment-Asset. Sie ist
keine Neo4j-/Qdrant-Promotion und keine Aussage über politische Quellgenauigkeit.

## Verifizierte Slice-3–7-Ausgangsevidenz

Die folgenden versionierten Nachweise bilden das Startgate:

- [Plan-03 Flag-on Canary](2026-08-06-spatial-plan03-flag-on-canary.md): 100
  semantische Transitionen und 100 Kamera-LOD-Swaps ohne monotones Wachstum.
- [Plan-05 Admin-1-/Prefetch-Canary](2026-08-07-spatial-plan05-admin1-prefetch-canary.md):
  Katalog `spatial-v1-e76a16bff799`, 204 Scopes, 68 Assets, 5.355.159 Bytes,
  38/38 Containment-Gates, maximal 0 m gemessener Ableitungsfehler, Firefox/WebGL2
  Cold Visual p95 292 ms. Der Lauf war ein Vite-DEV-Build und belegt keinen
  korrigierten transienten Production-Browser-Cache-Peak.
- [Plan-06A Neo4j-Verifikation](2026-08-08-spatial-plan06a-neo4j-verification.md):
  additive Spatial-Indizes online und read-only Plan-Smoke grün; kein Backfill-Apply.
- [Plan-06B Review-Remediation](2026-08-09-spatial-plan06b-review-remediation.md):
  18/18 statische Exact-Templates per `EXPLAIN`; Country-Smokes reconciliert;
  Admin-1, Incidents und Admin-2 nicht promotierbar.
- [Plan-07A Abschluss](2026-08-10-spatial-plan07a-verification.md) und
  [Review-Remediation](2026-08-10-spatial-plan07a-review-remediation.md):
  Qdrant-Vertrag code-seitig grün; realer Snapshot mit 1.025.197 Points, neun
  Corpus-/Fulltext-Indizes, keinen Spatial-Indizes und keinen Spatial-Payloads.
- [Plan-08-Handoff](../superpowers/HANDOFF-spatial-scope-plan08-2026-08-10.md):
  Plan 07B ist service-lokal grün; keine Live-/Staging-Mutation oder Capability-
  Promotion ist durch diesen Record autorisiert.

## Runtime-Inventur

### Analytische und schaltbare Layer

Die geschlossene Menge stammt aus `LayerVisibility`, `DEFAULT_LAYERS`, der
Backend-Config-Merge-Logik, `LayersPanel` und den tatsächlichen Mounts in
`WorldviewPage`. `Default` beschreibt den Frontend-Fallback vor dem partiellen
Backend-Override. `Scope-Entscheid` gilt für nichtglobale Scopes.

| Runtime-ID | Default | Geometrie / Bulk-Seam | Relation und Zeit-/Coverage-Basis | Scope-Entscheid |
|---|---:|---|---|---|
| `flights` | an | Billboards + intern erzeugte Trails | Bewegungsobjekt; 15-s-Poll, Provider-/Cache-Fallback, keine vollständige Track-Intersection oder scoped Response-Abrechnung | **unsupported**, verbergen |
| `satellites` | an | Point-Primitives, Orbit-/Cone-Polylines; einzelne ausgewählte Footprint-Entity | globaler Orbit-Kontext; TLE-Refresh stündlich, Backend-Cache 2 h | **global-context**, sichtbar und so beschriften |
| `earthquakes` | an | `BillboardCollection` + Labels; Render-Cap 250 | `occurs-in`; USGS M4.5+ der letzten sieben Tage, 5-min-Poll/Cache, WGS84-Punkt pro Ereignis | **ausgewählt: strict / point-in-boundary** |
| `vessels` | aus | Billboards + prognostische 5-min-Kursvektoren; Cap 3.000/200 | aktuelle AIS-Position, kein vollständiger Track; 60-s-Poll | **unsupported**, verbergen |
| `cctv` | aus | Billboards | fünf hart codierte Platzhalter ohne produktive Quellen-/Coverage-Semantik | **unsupported**, verbergen |
| `events` | aus | `BillboardCollection` + Labels | `occurs-in`; bestehende CHRONIK-Antwort mit Scope-Token, Generation und ehrlicher bbox-/exact-Anwendung | bestehenden **strict**-Pfad erhalten |
| `cables` | aus | Polyline-/Billboard-/Label-Collections | `intersects`; stündlicher Live-/Fallback-Datensatz, aber keine echte Boundary-Intersection oder scoped Abrechnung | **unsupported**, verbergen |
| `pipelines` | aus | Polyline-/Billboard-/Label-Collections | `intersects`; statisch 52 LineStrings / 268 Stützpunkte, unreviewte vereinfachte Linien für Scope-Intersection | **unsupported**, verbergen |
| `countryBorders` | an | Legacy Ground-Polylines oder Spatial-Scope-Primitives | kartografische Präsentation, kein operativer Datenfilter | **scope-presentation**; kein Exact-Claim |
| `cityBuildings` | an | globales Google-/OSM-3D-Tileset | Basiskartenkontext, kein räumlicher Resultset-Claim | **global-context** |
| `firmsHotspots` | an | `BillboardCollection`; View-Cap 400 | `occurs-in`; 24-h-Fenster, 60-s-Poll, Backend-Cap 5.000; noch kein Layer-Generation-/Accounting-Seam | **unsupported**, verbergen |
| `milAircraft` | an | Track-Polylines + Billboards | `intersects`; live 24 h / 30-s-Poll oder CHRONIK-Replay-Fenster; Toggle mischt ungescopten Live- und gescopten Replay-Pfad | **unsupported**, verbergen |
| `datacenters` | aus | `BillboardCollection` + Labels | `occurs-in`; statisch 353 Punkte, gemischte `coord_quality`, keine Coverage-Attestation | **unsupported**, verbergen |
| `refineries` | aus | `BillboardCollection` + Labels | `occurs-in`; statisch 561 Punkte, gemischte `coord_quality`, keine Coverage-Attestation | **unsupported**, verbergen |
| `eonet` | aus | `BillboardCollection` + Labels | `occurs-in`; 168-h-Fenster, 120-s-Poll, Backend-Cap 2.000; noch kein Generation-/Accounting-Seam | **unsupported**, verbergen |
| `gdacs` | aus | `BillboardCollection` + Labels | `occurs-in`; 168-h-Fenster, 120-s-Poll, Backend-Cap 2.000; noch kein Generation-/Accounting-Seam | **unsupported**, verbergen |

Für jeden Eintrag wird Work Order 1 eine exakte Registry-Zeile mit Relation,
Verhalten, Präzision, Stale-Policy und sichtbarem Unsupported-Verhalten erzwingen.
Die Registry wird produktiv von Layer-Badges und vom fail-closed Runtime-Gate
verwendet; sie bleibt keine zweite, unverdrahtete Wahrheitsquelle.

### Immer gemountete Präsentationskontexte

Diese Pfade sind keine analytischen Resultsets und werden nicht als exakt gescopt
ausgegeben:

| Pfad | Runtime-Seam | Entscheidung |
|---|---|---|
| Terrain, Basemap und NASA-Nachtbild | Cesium Terrain/Imagery | globaler Kartografie-Kontext |
| Graticule | imperative `PolylineCollection` | globaler Referenzkontext |
| Recon-Pins | `BillboardCollection`, Manifest-Cardinality zur Laufzeit | globaler Recon-Katalogkontext; kein `occurs-in`-Claim |
| Spotlight/HUD | UI-/Pick-Präsentation | kein Datenlayer und kein Scope-Filter |
| CHRONIK-Scrubber | servergebundener Scope-/Zeitvertrag | bestehender Slice-4/6/7-Pfad, nicht neu als Punktlayer implementieren |

## Auswahl Work Order 1 — Registry und erster Punktadapter

### Freigabe: `earthquakes`

Die Auswahl beruht auf folgenden nachprüfbaren Eigenschaften:

- Das Backend übernimmt pro USGS-Feature genau `longitude`, `latitude`, Ereignis-ID
  und UTC-Zeit in ein typisiertes Modell. Die fachliche Relation ist
  `occurs-in` am Ereignispunkt.
- Der vorhandene Renderer verwendet bereits eine imperative
  `BillboardCollection`; es entsteht keine Entity-API-Migration.
- Der vollständige Feed wird vor dem bestehenden Viewport-/Magnitude-Cap gefiltert.
  Render-LOD oder Kamera-Culling entscheidet dadurch nie die administrative
  Zugehörigkeit.
- Der Adapter konsumiert ausschließlich `SpatialContainmentPort`. Beim semantischen
  Commit wird der alte Index synchron ungültig; `building` und `unavailable`
  liefern keine alten Ergebnisse.
- `inside`, `outside`, `boundary-uncertain` und ungültige WGS84-Koordinaten werden
  getrennt gezählt. Strict schließt die letzten drei Klassen aus.
- `world` nimmt jeden validen WGS84-Punkt auf. Kamera-LOD verändert den festen
  katalogrevisiongebundenen Containment-Index nicht.
- Die semantischen Earthquake-Objekte werden weder mit Scope-Key noch mit
  Containment-Ergebnissen angereichert oder mutiert.

Die Auswahl autorisiert keine Aussage, dass der gelockte Grenzdatensatz oder der
USGS-Ereignispunkt metergenau ist. `boundary-uncertain` bleibt das Fehlerband der
Boundary-Ableitung und wird sichtbar aus der Included-Menge herausgerechnet.

## Work Order 2 — gestoppt

Kein Track-, Polygon- oder Rasterlayer wird in diesem Plan-08-Lauf neu aktiviert:

- `flights` besitzt nur aktuelle Samples plus lokal erzeugte Trails;
- `vessels` besitzt aktuelle Positionen plus prognostische Kursvektoren;
- `milAircraft` mischt einen globalen Live- und einen bereits gescopten Replay-Pfad;
- Cables und Pipelines benötigen echte Segment-/Boundary-Intersection statt
  Vertex-, Mittelpunkt- oder Startpunkt-Heuristik;
- Satelliten, Terrain, Imagery und 3D Tiles sind ausdrücklich globaler Kontext.

Eine Vertex- oder Mittelpunktprobe würde `intersects` falsch approximieren. Ein
ausgewählter Track müsste das vollständige Originalobjekt unverändert erhalten und
eigenes Generation-/Response-Accounting liefern. Da dieser vollständige Seam heute
nicht vorliegt, stoppt der Zweig ohne Produktionsadapter.

## Work Order 3 — Admin-2 blockiert

Der reviewte `catalog-plan.json` enthält 175 Country-only-Einträge, genau ein
Admin-1-Theater (`country:UKR`) und **null Admin-2-Einträge**. Der aktive Source Lock
enthält Natural Earth Admin-0, geoBoundaries UKR Admin-1, Mapshaper und den
ODIN-Crosswalk, aber keine Admin-2-Quelle.

Damit fehlen weiterhin:

- ein reviewtes Theater und eine politische Representation-Entscheidung;
- gelockter Release, URL, Lizenz, Attribution und SHA-256;
- Raw-Feature-, Ring-, Vertex-, größter-Ring-, Wire-, Heap- und Error-Messung;
- der Nachweis `<= 256` Child-Features ohne implizites Paging;
- vollständige Lineage-/Direct-Link-/Pick-/Soak-Evidenz;
- theaterbezogene Neo4j- und Qdrant-Plan-06/07-Coverage samt Accounting.

Es wird weder Source Lock noch Catalog Plan geändert, kein Pack gebaut und keine
Admin-2-Capability aktiviert. Tiling wäre ein eigener versionierter Vertrag.

## Work Order 4 — 3D deferred

Es existiert kein akzeptierter Metric Record mit Name, Einheit, Zeitbasis,
Aggregation, linearer/logarithmischer Skala, Domain, Clamping, Missing-Semantik,
Legende, Snapshot-/Provenance-Revision und Analystennutzen. Google-/OSM-3D-Tiles,
Terrain und vertikale Überhöhung sind Basiskartenkontext und keine Plan-08-Metrik.

Darum entstehen keine Extrusion, Höhe, Farbmetrik oder Arc. Work Order 4 bleibt
ausdrücklich `deferred`.

## TDD- und Aktivierungsgrenzen

Die freigegebene Implementierung folgt dieser Reihenfolge:

1. RED: geschlossene Matrix über alle 16 `LayerVisibility`-Keys sowie Lifecycle-,
   Generation-, World-, Containment-, Accounting- und LOD-Unabhängigkeitstests.
2. GREEN: kleiner `SpatialContainmentPort`, kataloggebundener Containment-Adapter
   über den gemeinsamen `BoundaryAssetStore`, strikter Earthquake-Punktadapter und
   produktiver Registry-Consumer.
3. REFACTOR: Claims bleiben in der Registry; Earthquake-Rendering kennt keine
   eigene Precision-Entscheidung und mutiert keine Quelldaten.
4. VERIFY: fokussierte Tests, High-Cardinality-/Heap-Messung, vollständige
   Frontend-Gates und anschließend die service-lokalen Whole-Program-Gates.

Nicht autorisiert sind Push, PR, Merge, Deployment, Catalog-Publish, Neo4j-/Qdrant-
Mutation, Re-Enrichment oder Capability-Promotion. Die drei beim Start vorhandenen
fremden Worktree-Änderungen bleiben außerhalb jedes Plan-08-Commits.
