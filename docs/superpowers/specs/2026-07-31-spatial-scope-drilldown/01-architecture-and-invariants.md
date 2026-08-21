# Teil-Spec 01 — Architektur und Invarianten

> **Parent:** [Spatial-Scope-Index](../2026-07-31-spatial-scope-drilldown-design.md)
>
> **Normativer Besitz:** Gesamtentscheidung, verifizierter Ist-Zustand, Ziele,
> globale Trennlinien, Modulvokabular und Auswahl des öffentlichen Interface.
>
> **Voraussetzung:** nur der Parent-Index. Detailverträge gehören den nachfolgenden
> Teil-Specs und werden hier nicht neu definiert.

---

## 1. Entscheidung in einem Satz

ODIN erhält ein tiefes, rendererunabhängiges `SpatialScopeModule`, das einen kanonischen räumlichen Scope (`world → country → admin1 → admin2`) atomar auflöst und als unveränderlichen Query-Kontext veröffentlicht; Cesium-Darstellung, URL, CHRONIK, Neo4j und Qdrant sind abgeleitete Adapter und dürfen Kamera, Selection, Spotlight oder Viewport niemals als semantische Source of Truth verwenden.

Das Feature ist damit keine neue Karte und kein Three.js-Port. ODIN behält CesiumJS, Terrain, Imagery, 3D Tiles und die vorhandenen operativen Layer. Neu ist die belastbare räumliche Semantik unter der Karte.

---

## 2. Warum das mehr als ein Kamera-Drilldown ist

Ein Country-Klick setzt heute ein Polygon in `SpotlightContext`, fliegt die Kamera und öffnet Country-UI. CHRONIK kann zwar eine BBox erhalten, bekommt sie vom WorldView-Pfad derzeit aber nicht. `IntelQuery.region` ist nur ein freier String; im aktuellen ReAct-Pfad wird er nicht als unveränderlicher Tool-Filter in den Agent-State übernommen. Dadurch existieren mehrere ähnlich aussehende, aber unabhängige Zustände:

- Kamera-Ausschnitt;
- Country-Spotlight inklusive kompletter GeoJSON-Geometrie im React-State;
- Entity-/Country-Selection;
- CHRONIK-Zeitfenster;
- Munin-Query;
- Neo4j- und Qdrant-Filter;
- URL-Zustand.

Ein visuell korrektes Polygon garantiert heute nicht, dass die Daten darunter denselben Raum meinen. Für ein taktisches Lagebild ist genau das der kritische Fehlerfall.

Der neue Scope ist deshalb ein semantischer Query-Kontext mit visueller Repräsentation, nicht umgekehrt:

```text
                         ┌── Cesium boundary + camera
                         ├── CHRONIK event/movement filter
Scope commit (revision) ─┼── operational layer policy
                         ├── Neo4j deterministic predicates
                         ├── Qdrant payload filters
                         └── Munin run snapshot
```

Alle Äste sehen dieselbe `scope_key` und `catalog_revision`. Sie dürfen trotzdem unterschiedliche räumliche Fähigkeiten besitzen. Jeder Ast muss deshalb zusätzlich offenlegen, ob er semantisch, punktgeometrisch, nur per BBox oder gar nicht filtern konnte.

---

## 3. Verifizierter Ist-Zustand

Diese Aussagen wurden gegen den aktuellen Working Tree geprüft:

### 3.1 Frontend

- `SpotlightContext.tsx` vereinigt `CircleTarget` und `CountryTarget`; `CountryTarget` trägt das vollständige Polygon durch React-State.
- `SpotlightOverlay.tsx` rendert Country-Polygone über Cesium-Ground-Primitives.
- `EntityClickHandler.tsx` führt Country-Hit-Test, Selection und Country-Spotlight zusammen.
- `useCountryHitTest.ts` lädt Natural-Earth-TopoJSON und Endonyme, baut einen RBush und liefert M49, ISO3 und Geometrie. Drei Natural-Earth-Features sind im aktuellen Mapping explizit ungelöst.
- `public/country-endonyms.json._topoIndex` ist dabei eine dritte, nicht vom geplanten
  Source Lock besessene Identitätsprojektion. Sie mappt Kosovo aktuell auf `XKX`, und
  `capitalCoverage.test.ts` fixiert diese Kopplung. Dieser Legacy-Pfad darf im neuen
  Spatial-Modus keinen `ScopeKey` erzeugen.
- `CountryBorders.tsx` verwendet bereits eine gebatchte `GroundPolylinePrimitive`; dies ist der richtige Cesium-Stil und bleibt erhalten.
- `GlobeViewer.tsx` verwendet CesiumJS 1.142, Terrain und Google Photoreal 3D Tiles mit OSM-Fallback.
- `TimeWindowQuery` und die Timeline-API können bereits eine BBox übertragen. `ScrubberMount.tsx` setzt sie für das Histogramm derzeit nicht.
- `useTimeWindow.ts` und `useTimeHistogram.ts` besitzen AbortController und Sequence Guard, behalten bei Parameterwechsel aber absichtlich alte Daten. Bei einem Scope-Wechsel wäre diese Stale-Policy irreführend.
- `lib/lod.ts` modelliert Kamera-LOD und antimeridianfähige View-Bounds. Kamera-LOD ist nicht dasselbe wie semantische Scope-Tiefe.

### 3.2 Backend und Graph

- Die Timeline-Routen filtern bereits mit statischen, parametergebundenen Cypher-Queries und behandeln `west > east` als Datumsgrenzen-Überquerung.
- `services/data-ingestion/gdelt_raw/migrations/phase2_indexes.cypher` definiert bereits einen Point-Index auf `Location.geo`; aktuelle Writer setzen jedoch überwiegend `lat`/`lon`. Der Index ist daher Zielzustand, nicht Beweis für vorhandene Abdeckung.
- Country-Briefings persistieren bereits Schlüssel im Format `country:<ISO3>` beziehungsweise `country:m49:<M49>`. Diese Identität wird weiterverwendet.
- Geo-Writer speichern quellenspezifische Country-Werte. Insbesondere GDELT-Country-Codes sind nicht automatisch ISO-Codes; beispielsweise ist `UP` ein GDELT/FIPS-artiger Code für Ukraine. Rohcode und Codesystem müssen erhalten bleiben.
- Neo4j-Writes sind deterministisch und parametergebunden. Das bleibt unverhandelbar.

### 3.3 Intelligence und Qdrant

- `QueryRequest.region` erreicht den Intelligence-Service, wird im aktuellen ReAct-Initial-State aber nicht als verpflichtender räumlicher Constraint gespeichert.
- `qdrant_search(query, region="")` lässt das Modell einen Region-String setzen, warnt aber selbst, dass der Index dieses Metadatum nicht zuverlässig enthält.
- Die Qdrant-Payload-Indizes enthalten keine räumlichen Felder.
- Viele Punktquellen besitzen `latitude`/`longitude`; RSS-, Telegram- und Analyse-Dokumente besitzen häufig keine kanonischen Geo-Metadaten.
- Die lokal installierte LangGraph-Version 1.1.3 stellt `ToolRuntime` über `langgraph.prebuilt` bereit. Runtime-State wird damit in Tools injiziert und nicht als modellkontrolliertes Tool-Argument exponiert.

Diese Lücken bestimmen die Reihenfolge der Umsetzung: erst eine semantische Source of Truth, dann ehrliche approximative Filter, danach Datenmigration und exakte Filter.

---

## 4. Ziele, Nicht-Ziele und Erfolgskriterien

### 4.1 Ziele

1. Ein Klick kann deterministisch von Welt zu Land und von dort zu administrativen Untereinheiten wechseln.
2. Breadcrumb, Deep Link, Browser-History und Tastaturbedienung referenzieren denselben
   kanonischen Scope; Browser Back besucht URLs, während Ascend den Katalog-Parent nimmt.
3. Ein Scope-Commit tauscht `current`, Lineage und Query-Token atomar aus.
4. CHRONIK und Munin erhalten den committed Scope, niemals den pending Scope.
5. Cesium rendert gebatcht, generation-sicher und ohne GPU-Leak über lange Sessions.
6. Boundary-Daten sind offline gebaut, versioniert, lizenzklar, provenance-stark und zur Laufzeit same-origin.
7. Jeder Daten-Consumer kennzeichnet Filterrelation, Präzision, Vollständigkeit und ausgeschlossene ungeoreferenzierte Datensätze.
8. Antimeridian, MultiPolygon, Löcher, fehlende Geometrie, Race Conditions und Revisionswechsel sind spezifizierte Normalfälle.
9. Die öffentliche Moduloberfläche bleibt klein genug, dass normale Caller weder GeoJSON noch Cesium noch BBox-Compiler verstehen müssen.
10. Spätere 3D-Metrikdarstellung kann auf demselben Scope aufbauen, ohne Scope-Semantik und Visual Encoding zu vermischen.

### 4.2 Nicht-Ziele

- Kein Three.js-Renderer und kein Austausch von CesiumJS.
- Keine Übernahme der Ästhetik, Fly-Lines, Chase-Lights, Basisringe oder anderer dekorativer Effekte des Fundstücks.
- Keine automatisch aus Kamerahöhe abgeleitete semantische Region.
- Kein universelles City- oder AOI-Modell in V1. Städte sind nicht überall administrative Kinder; AOIs sind nutzerdefinierte Geometrien mit anderer Identität und Lifecycle.
- Keine Behauptung, alle WorldView-Layer seien nach einem Scope-Wechsel exakt gefiltert.
- Kein Runtime-Download von Aliyun, geoBoundaries, Natural Earth oder anderen Drittquellen.
- Kein LLM-generiertes Cypher zur Durchsetzung räumlicher Constraints und weiterhin kein LLM-generierter Write.
- Keine dekorative Extrusion. Höhe ist nur zulässig, wenn sie eine benannte Metrik mit Einheit, Zeitbasis, Skala und Legende kodiert.

### 4.3 Produktseitige Definition von Erfolg

Ein Analyst kann einen Deep Link wie `?scope=admin1:iso3166-2:UA-14` öffnen, sieht nach der Auflösung einen kanonischen Breadcrumb, kann die Parent-Ebene erreichen und erhält CHRONIK-/Munin-Antworten, die denselben Scope und ihre Filterpräzision ausweisen. Ein schneller Wechsel A → B kann weder eine verspätete A-Geometrie noch A-Daten unter dem B-Breadcrumb anzeigen.

---

## 5. Begriffe und harte Trennlinien

### 5.1 Modulvokabular

- **Module:** `SpatialScopeModule` verbirgt Auflösung, Lineage, Races, URL, Prefetch, Query-Token und Consumer-Synchronisation.
- **Interface:** drei Operationen — Snapshot lesen, abonnieren, Command dispatchen.
- **Implementation:** State Machine, Katalogzugriff, Cache, URL- und Cesium-Adapter.
- **Depth:** ein `enter(scopeKey)` kauft eine große Menge korrekten Verhaltens hinter einer kleinen Oberfläche.
- **Seam:** die semantische Scope-Grenze ist die wichtigste Seam; HTTP, Browser-History und Cesium sind interne austauschbare Adapter-Seams.
- **Adapter:** übersetzt den semantischen Scope in ein externes System, ohne dessen Typen in den Core zurückzuleaken.
- **Leverage:** eine Korrektur an Revision- oder Race-Semantik schützt alle Caller gleichzeitig.
- **Locality:** Antimeridian-, Cache-, URL- und Fehlerregeln leben an genau einer Stelle.

### 5.2 Zustände, die niemals gleichgesetzt werden

| Zustand | Bedeutung | Darf Scope ändern? |
|---|---|---:|
| `SpatialScope` | kanonischer semantischer Raum | ja, nur über Commands |
| Camera | aktueller Blick auf den Globus | nein |
| Viewport/BBox | momentaner Bildausschnitt oder explizite AOI | nein |
| Selection | angeklicktes operatives Objekt oder Country-Detail | nein |
| Spotlight | temporärer Zoom-/Pin-/Suchfokus | nein |
| Camera LOD | Renderdetail anhand Höhe | nein |
| Time window | CHRONIK-Zeitdimension | nein |
| Layer visibility | sichtbare Informationsklassen | nein |

Ein Country-Klick darf zwei getrennte Actions auslösen — Country-Selection öffnen und `scope.enter(...)` — aber Selection ist nie das Transportmittel für Scope.

### 5.3 Scope-Hierarchie und Besuchshistorie

- `path` ist die vom Katalog verifizierte Parent-Lineage `world → … → current`.
- Browser-History ist die zeitliche Folge besuchter URLs.
- `ascend()` bedeutet „zum kanonischen Parent“.
- Browser Back bedeutet „zur vorherigen besuchten URL“.
- Diese Operationen werden weder benannt noch implementiert, als wären sie dasselbe.

---

## 6. Drei Interface-Entwürfe und Entscheidung

Vor der Festlegung wurden drei eigenständige Designs verglichen.

### 6.1 Entwurf A — minimaler Command-Store

Eine frameworkfreie Oberfläche mit `getSnapshot`, `subscribe`, `dispatch`; alle Übergänge sind Commands, React ist nur Adapter.

**Stärken:** höchste Depth, kleine Testfläche, keine React- oder Cesium-Typen, klare atomare Commit-Semantik.

**Schwäche:** Caller benötigen ergonomische Wrapper, sonst werden Command-Objekte repetitiv.

### 6.2 Entwurf B — flexibler Projection-Runtime

Ein erweiterbarer Kind-/Projection-Registry mit Leases für Neo4j, Qdrant, Cesium, AOI, Locality und weitere Scope-Arten.

**Stärken:** sehr präzise Policy- und Projektionsmodelle, langfristig maximal erweiterbar.

**Schwäche:** zu viele öffentliche Konzepte vor dem ersten vertikalen Slice; Plugin-Kinds und Leases würden V1-Komplexität zu jedem Caller tragen.

### 6.3 Entwurf C — caller-optimierter React-Hook

`useSpatialScope()` liefert `current`, `trail`, `query`, `enter`, `back`, `reset` und versteckt alle Geometrie.

**Stärken:** beste Ergonomie in WorldView-Komponenten.

**Schwäche:** als primäre Architektur würde Business-Logik leicht in Provider/Effects und damit in React wandern; außerdem ist „back“ zwischen Parent-Aufstieg und Browser-History mehrdeutig.

### 6.4 Bewertungsmatrix

| Kriterium | A: Command-Store | B: Projection-Runtime | C: Hook-first |
|---|---:|---:|---:|
| Depth | sehr hoch | hoch | mittel |
| Locality | sehr hoch | hoch | mittel |
| klare Semantik-Seam | sehr hoch | hoch | mittel |
| Caller-Ergonomie | mittel | niedrig | sehr hoch |
| V1-Implementierungsrisiko | niedrig | hoch | mittel |
| spätere Erweiterbarkeit | hoch | sehr hoch | mittel |

### 6.5 Gewählter Hybrid

Entwurf A ist der Core. Entwurf C wird als dünner `useSyncExternalStore`-Adapter darübergelegt. Aus Entwurf B werden nur transportneutrale, interne Query-Projektionen und explizite Präzisionsmetadaten übernommen. V1 exponiert keine Plugin-Registry, keine Geometrie-Leases und keine City-/AOI-Kinds.

Deletion Test: Würde das Module entfernt, müssten Country-Click, Breadcrumb, URL, CHRONIK, Munin, Cesium, Prefetch und Race Guards dieselben Regeln jeweils neu implementieren. Das rechtfertigt das Module.

---
