# Teil-Spec 14 — Rollout und Abnahme

> **Parent:** [Spatial-Scope-Index](../2026-07-31-spatial-scope-drilldown-design.md)
>
> **Normativer Besitz:** Feature-Gates, Kompatibilität, Rollback, Stop-Regeln,
> abgelehnte Alternativen, Gesamt-Definition-of-Done und technische Primärquellen.
>
> **Voraussetzungen:** [01 — globale Invarianten](01-architecture-and-invariants.md),
> [12 — Fehler/Security](12-errors-security-and-observability.md) und bei
> Umsetzungsfreigabe [13 — TDD-Slices](13-implementation-and-tdd-slices.md).

---

## 26. Rollout, Kompatibilität und Rollback

### 26.1 Rollout

- **Phase A, Slices 1–2:** `VITE_SPATIAL_SCOPE_ENABLED` ist default-off; kein neuer
  Renderer ist produktiv erreichbar.
- **Phase B, Slices 3–5:** Legacy- und Spatial-Implementation bleiben im Source-Tree,
  werden aber am Composition Root strikt wechselseitig gemountet. Flag off rendert
  `CountryTarget`; Flag on rendert ausschließlich den Cesium-Scope-Adapter. Kein
  Viewer besitzt beide Country-Renderer gleichzeitig. Produktion bleibt zunächst
  default-off; ein getrennt gebautes Flag-on-Artefakt läuft als Canary. Das `VITE_*`-
  Flag ist Build-Time-Konfiguration, kein behaupteter Runtime-Schalter.
- **Phase C, nach allen Slice-5-Gates:** Flag wird default-on; der Legacy-Pfad bleibt
  genau eine Release-/Soak-Periode als Flag-Rollback erhalten.
- **Phase D, Cleanup-Release:** Nach erfolgreichem Soak werden `CountryTarget`, der
  alte Country-Hit-Test als Identitätsquelle und das Flag entfernt. Ab hier ist ein
  Frontend-Artefakt-Rollback nötig; Flag-off wird nicht mehr versprochen.
- Backend-Katalog-Endpunkte dürfen vorher deployt werden.
- Catalog-Bootstrap meldet tatsächlich verfügbare Consumer-Capabilities.
- Exact Neo4j/Qdrant-Filter besitzen separate serverseitige Activation Gates nach Coverage-Report.
- UI zeigt nur Drill-Affordances, die der aktive Katalog wirklich besitzt.

### 26.2 Kompatibilität

- Timeline-`bbox` bleibt bestehen.
- `region` bleibt befristet für nicht migrierte Intelligence-Caller, ist aber nie Scope-Enforcement.
- bestehende `lat/lon` und Country-Rohfelder bleiben erhalten.
- bestehender Country-Almanac-Key `country:<ISO3>` wird kanonisch wiederverwendet.
- globaler `CountryBorders`-Layer kann als Context-Layer bestehen bleiben; aktive/Child-Scope-Geometrie besitzt der neue Adapter.

### 26.3 Rollback

- Phasen B/C: Ein Flag-off-Build beziehungsweise dessen vorheriges Artefakt mountet
  den Legacy-WorldView; neue Backend-Endpunkte und additive Daten bleiben inert und
  kompatibel.
- Phase D: Rollback deployt das unmittelbar vorherige Frontend-Artefakt. Die
  Backend-/Datenänderungen bleiben additiv, sodass dieses Artefakt weiter funktioniert.
- additive Neo4j-/Qdrant-Felder und Indizes werden beim Code-Rollback nicht destruktiv entfernt.
- exact Activation Gate aus: Endpoint meldet wieder explizit `bbox_approximate`, sofern dieser Pfad im jeweiligen Release weiterhin unterstützt wird; niemals still.
- Katalog: vorherige Revision bleibt als served Revision verfügbar und kann wieder active gesetzt werden.
- kein Rollback löscht Backfill-Rohdaten oder überschreibt Source-Codes.

Der Parallelzeitraum ist auf Phase B plus eine Soak-Periode begrenzt und besitzt einen
expliziten Lösch-Gate. „Parallel“ meint Codeverfügbarkeit, niemals gleichzeitiges
Rendering.

---

## 27. Stop-Regeln

Umsetzung stoppt und benötigt Review, wenn eine der Bedingungen eintritt:

1. Source-Lizenz, Attribution oder Boundary-Representation ist ungeklärt.
2. Ein Source-Hash weicht vom Lock ab.
3. Admin-0-Crosswalk enthält unklassifizierte oder heuristisch geratene IDs/
   Features; ein reviewter `non_scope_feature`-Record ist dagegen eine explizite
   Entscheidung.
4. Topology-/Antimeridian-Validierung schlägt fehl.
5. Asset-/Feature-/Vertex-Budgets werden überschritten.
6. Ein UI-Zustand kann alte Scope-Daten unter neuem Breadcrumb zeigen.
7. Ein nicht-globaler Query-Pfad fällt ungefiltert zurück.
8. Das Modell kann Scope-Key, Relation oder Filterfeld als Tool-Argument überschreiben.
9. Scoped Neo4j benötigt freien LLM-Cypher, weil kein statisches Template existiert.
10. Backfill-Conflict-/Coverage-Report fehlt oder unterschreitet das Gate.
11. Cesium-Soak zeigt monotones Wachstum von Primitives, Listenern oder decoded Cache.
12. Eine politische Sondergeometrie wird ohne explizite Policy-Revision verpflichtend gerendert.
13. Ein Spatial-Pick erzeugt Identität aus `_topoIndex`, Displayname oder lokalem
    ISO3 statt aus dem Catalog-Child-Pack.
14. Der Containment-Feasibility-Report fehlt oder ein verpflichtender Scope verletzt
    das reviewte Wire-/Heap-/Ring-/50-m-Gate.
15. Eine neue Derivationsrevision soll exact aktiviert werden, bevor Neo4j- und
    Qdrant-Re-Enrichment ihre Stale-/Coverage-Gates bestanden haben.

---

## 28. Abgelehnte Alternativen

### Three.js-Template übernehmen

Abgelehnt: ODIN besitzt bereits den richtigen Globe-Renderer. Übernahme würde Lizenz-, Asset-, Architektur- und politische Datenrisiken importieren und Terrain/3D-Tiles/Layer-Integration duplizieren.

### Scope aus Kamera/Zoom ableiten

Abgelehnt: Ein Viewport kann mehrere Länder enthalten, über Ozean liegen oder durch User-Pan entstehen. Kamera ist Ansicht, nicht Analysten-Query.

### GeoJSON im React-Context

Abgelehnt: große mutable Daten, hohe Re-render-Kopplung und keine Query-Identität. React sieht Summaries und Token; Geometrie bleibt im Catalog/Cesium-Adapter.

### BBox als dauerhafter Scope-Vertrag

Abgelehnt: BBox ist für Fiji/Dateline fehleranfällig und semantisch ungenau. Sie bleibt explizite Viewport-/AOI- oder transparente Übergangsprojektion.

### Scope nur als Prompttext an Munin

Abgelehnt: Prompttext ist keine Filtergrenze und kann vom Modell ignoriert oder durch Injection verändert werden.

### Beliebiges LLM-Cypher nachträglich „scopen“

Abgelehnt: eine sichere generische Query-Rewrite-Schicht ist deutlich komplexer und fehleranfällig. Scoped Runs verwenden allowlisted Templates oder failen geschlossen.

### Alle Layer sofort filtern

Abgelehnt: Punkt, Track, Polygon, Raster, globales Referenzobjekt und semantisches Dokument benötigen verschiedene Relationen. Eine Capability-Matrix verhindert visuelle Lügen.

### Dekorative Extrusion/Fly-Lines

Abgelehnt: Höhe und Bögen müssen echte Werte beziehungsweise Beziehungen kodieren. Scope-Navigation braucht keine Showroom-Animation.

---

## 29. Definition of Done für das Gesamtprogramm

- `SpatialScopeModule` erfüllt Interface und Invarianten ohne React-/Cesium-Typen.
- Deep Links, Breadcrumb, Ascend und Browser-History sind race-sicher getestet.
- World→Country→ausgewählte Admin-1-Drilldowns laufen über den lokalen versionierten Katalog.
- Nach Phase D sind Country-Geometrie, Legacy-Hit-Test-Identität und `CountryTarget`
  aus Spotlight-State und Produktionsbundle entfernt.
- Cesium verwendet gebatchte Primitives, generation-sicheren Swap und deterministisches Disposal.
- CHRONIK bindet Scope und Zeit, versteckt stale Cross-Scope-Daten und weist Präzision/Coverage aus.
- Neo4j-Writer und Backfill materialisieren kanonische Scope-Keys und `geo`; exact Filter sind statisch und indexiert.
- Qdrant besitzt relation-spezifische Scope-Payloads und Indizes; Corpus-Policy bleibt wirksam.
- Munin erhält Scope über gepinnten Agent-State/`ToolRuntime`; das Modell kann ihn nicht verändern.
- Kein nicht-globaler Consumer fällt ungefiltert zurück.
- Boundary-Quelle, Lizenz, Representation und Revision sind sichtbar und auditierbar.
- Catalog- und Derivationsrevision sind getrennt; Carry-forward und wiederkehrendes
  Re-Enrichment sind durch Reports belegt.
- Pflicht-Theater erfüllen die gemessenen Containment-Gates; grenznahe Punkte werden
  als `boundary-uncertain` statt als exakt klassifiziert.
- Antimeridian-/Race-/Missing-Geometry-/Revision-/Soak-Tests sind grün.
- Alle service-lokalen Lint-, Type-, MyPy- und Testkommandos sind grün.
- Erst danach wird ein separater Implementation-Plan mit Task-Zuordnung und Commit-Reihenfolge erstellt.

---

## 30. Primärquellen für technische Entscheidungen

- Natural Earth Terms of Use: <https://www.naturalearthdata.com/about/terms-of-use/>
- geoBoundaries API und `gbOpen`-Lizenz: <https://www.geoboundaries.org/api.html>
- CesiumJS `PrimitiveCollection` Lifecycle: <https://cesium.com/learn/cesiumjs/ref-doc/PrimitiveCollection.html>
- Neo4j Spatial Values und Point Indexes: <https://neo4j.com/docs/cypher-manual/current/values-and-types/spatial/>
- Neo4j `point.withinBBox`, inklusive Datumsgrenze: <https://neo4j.com/docs/cypher-manual/current/functions/spatial/>
- Neo4j Point-Index-Erzeugung: <https://neo4j.com/docs/cypher-manual/current/indexes/search-performance-indexes/create-indexes/>
- Qdrant Geo-Payloads: <https://qdrant.tech/documentation/concepts/payload/>
- Qdrant Geo-Filter: <https://qdrant.tech/documentation/search/filtering/>
- Qdrant Payload-Indizes: <https://qdrant.tech/documentation/manage-data/indexing/>
- LangGraph/LangChain Tool Runtime und State-Injection: <https://docs.langchain.com/oss/python/langchain/tools>
- Mapshaper Simplification: <https://mapshaper.org/docs/guides/simplification.html>
- Mapshaper Source/Lizenz: <https://github.com/mbloch/mapshaper>
