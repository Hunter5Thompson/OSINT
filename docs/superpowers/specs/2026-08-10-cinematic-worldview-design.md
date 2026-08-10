# Cinematic WorldView — Cesium Scene and Scoped Data Visualization

- **Spec-Datum:** 2026-08-10
- **Status:** Draft — adversariales Review erforderlich, nicht umsetzungsfreigegeben
- **Betroffene Systeme:** Hlíðskjalf/WorldView, Spatial Scope, CHRONIK, Backend-Spatial-Adapter und Spatial-Catalog-Build
- **Technischer Rahmen:** React 19, TypeScript strict, CesiumJS 1.142, vorhandene CSS-/SVG-/Canvas-Werkzeuge
- **Entwurfsart:** Clean-room. Das externe `three-scope-map-skill` dient nur als Referenz für die allgemeine visuelle Grammatik aus Licht, Tiefe, Bewegung und hierarchischem Drilldown. Quellcode, Assets, Shader, Daten, Texte, Komponentenstruktur und Framework-Entscheidungen werden nicht übernommen.
- **Dokumentart:** eigenständige Design-Spec. Diese Datei ist weder ein neuer nummerierter Spatial-Plan noch eine Freigabe für Plan 05D.

---

## 1. Entscheidung in einem Satz

ODIN erweitert die bestehende Cesium-WorldView um ein tiefes
`CinematicWorldviewModule`, das committed Spatial Scope, Zeit, ausgewählte Datenlinse
und generation-sichere Layer-Snapshots in eine zusammenhängende cineastische Szene
übersetzt; der bestehende `SpatialScopeModule` bleibt unverändert alleinige
semantische Source of Truth, und jede quantitative visuelle Kodierung bleibt an eine
benannte Metrik, Einheit, Zeitbasis, Präzision, Coverage und Legende gebunden.

CesiumJS bleibt der einzige WorldView-Renderer. React bleibt für Controls,
zugängliche Beschriftung, Legenden und Panels verantwortlich. Diese Spec führt weder
einen zweiten Canvas-Renderer noch Vue, GSAP, React Three Fiber oder einen neuen
Three.js-WorldView-Pfad ein.

---

## 2. Normative Präzedenz und Review-Gate

Bis zu einem dokumentierten Review-PASS bleibt der freigegebene
[Spatial-Scope-Spec-Satz](2026-07-31-spatial-scope-drilldown-design.md) normativ. Diese
Draft-Spec ändert noch keinen bestehenden Vertrag.

Bei Freigabe ersetzt diese Spec ausschließlich folgende frühere Produktentscheidungen:

1. `01 §4.2` und `14 §28` verwerfen bisher jede Übernahme der visuellen Grammatik,
   dekorative Extrusion und Fly-Lines. Künftig wird zwischen nicht-quantitativer
   **Stagecraft** und quantitativer **Datenkodierung** unterschieden.
2. `11 §18.5` verbietet bisher jede dauerlaufende dekorative Animation. Künftig sind
   budgetierte, pausierbare Ambient-Bewegungen zulässig, sofern Reduced Motion und
   die statische Qualitätsstufe semantisch vollständig bleiben.
3. `11 §19` bleibt normative Grundlage datengetriebener 3D-Metriken und wird durch
   diese Spec konkretisiert, nicht abgeschwächt.

Unverändert normativ bleiben insbesondere:

- Scope-Key, Lineage, Catalog-Revision und Boundary-Policy;
- committed statt pending Scope als einzige Daten- und Darstellungsidentität;
- generation-sicherer Build/Swap und deterministisches Disposal;
- feste Preferred-LOD-Pick-Geometrie unabhängig von Kamera-LOD;
- Layer-Relation, Präzision, Coverage, stale policy und Fail-closed-Verhalten;
- parametergebundene statische Backend-Queries und keine LLM-generierten Writes;
- Plan-05D-Gates, Legacy-Rollback und das Verbot vorzeitiger Legacy-Löschung.

Ein Review-PASS für diese Spec autorisiert noch keine Implementierung. Danach wird
ein eigener begrenzter TDD-Implementierungsplan aus dieser Spec abgeleitet. Er ist
kein Bestandteil dieses Dokuments.

---

## 3. Problem und verifizierter Ist-Zustand

### 3.1 Was bereits funktioniert

Der aktuelle Branch besitzt bereits die schwierige räumliche Grundlage:

- kanonische Navigation `world → country → ausgewählte admin1`;
- immutable Catalog-Revisions, Render-/Containment-Assets und LODs;
- race-sichere Scope-Commits, URL/History und Breadcrumb;
- generation-sichere Cesium-Primitives, getrennte Render-/Pick-LOD und Disposal;
- CHRONIK-Scope-Accounting und ein fester Point-in-Boundary-Port;
- Terrain, Photorealistic 3D Tiles, Nachtlichter, Atmosphäre, Graticule;
- gebatchte Billboards/Polylines, Event-/Earthquake-/FIRMS-Pulse, Trails,
  Kursvektoren und Satellitenorbits;
- ein FPS-basierter Degradationsmechanismus.

Diese Systeme werden vertieft und orchestriert, nicht ersetzt.

### 3.2 Warum das Ergebnis trotzdem nicht cineastisch wirkt

Der bestehende Spatial-Presenter rendert absichtlich nur dezente Ground-Fills,
Outlines, eine stabile Pick-Fläche und einen top-down Camera-Fit. Gleichzeitig
besitzt fast jeder operative Layer eine eigene lokale Animationsschleife. Es gibt
keinen gemeinsamen Szenenzustand für Licht, Kamera, Reveal, Datenmarks und HUD.

Im nicht-globalen Scope sind aktuell nur wenige Layer räumlich belegbar. Insbesondere
FIRMS, Facilities, Track-Layer und lineare Infrastruktur werden außerhalb `world`
größtenteils ausgeblendet. Ein Admin-1-Scope zeigt dadurch korrekte, aber visuell
spärliche Daten.

Der aktive Spatial-Catalog enthält 176 Countries und 27 ukrainische Admin-1-Scopes,
aber keine deutschen Bundesländer und kein Admin-2. Ein generischer Renderer allein
kann fehlende Katalog- und Datenabdeckung nicht kompensieren.

### 3.3 Produktlücke

WorldView besitzt heute mehrere gute visuelle Effekte, aber noch kein Erlebnis mit
dramaturgischem Anfang, räumlichem Übergang und datenreicher regionaler Auflösung.
Der Nutzer sieht einen Kamera-Zoom auf eine Grenze; er erlebt noch keine kohärente
Transformation von Weltlage zu regionalem Lagebild.

---

## 4. Ziele und Nicht-Ziele

### 4.1 Ziele

1. WorldView bietet eine unverwechselbare Hlíðskjalf-Noir-Szene mit räumlicher Tiefe,
   Atmosphäre, kontrollierter Bewegung und klarer Informationshierarchie.
2. Ein expliziter Scope-Wechsel erzeugt eine abbrechbare cineastische Choreografie
   von Welt zu Country und von Country zu Admin-1.
3. Country-Ansichten können direkte Admin-1-Children als 2,5D-Situation-Board zeigen.
4. Ein ausgewählter Oblast oder ein Bundesland visualisiert seine tatsächlich
   zugeordneten Daten im aktuellen Zeitfenster.
5. Stagecraft und quantitative Datenkodierung sind visuell und vertraglich getrennt.
6. Alle Datenmarks tragen dieselbe Scope-Revision, Zeitbasis und Coverage-Wahrheit wie
   ihre textuellen Consumer.
7. Ein zentraler Clock- und Quality-Pfad ersetzt unkoordinierte Daueranimationen.
8. Die Szene bleibt über lange COP-Sitzungen performant, zugänglich und leak-frei.
9. Ukraine und Deutschland bilden die erste reviewte Admin-1-Produktabdeckung; der
   Renderer enthält keinerlei landesspezifischen Sondercode.
10. Der erste sichtbare End-to-End-Slice wird vor einer breiten Layer-Migration
    visuell abgenommen.

### 4.2 Nicht-Ziele

- kein Port oder Nachbau des externen Repositorys;
- kein Three.js-, Vue-, GSAP- oder Microfrontend-Renderer für WorldView;
- keine zweite semantische Scope-State-Machine;
- kein automatischer Scope aus Kamera, Zoom, Hover oder Viewport;
- kein Admin-2, City- oder frei gezeichneter AOI-Vertrag in diesem Vorhaben;
- keine pauschale Freigabe aller Layer in jedem Scope;
- keine erfundenen Bögen zwischen Hauptstädten oder zufälligen Punkten;
- keine variable Höhe, Farbe, Größe oder Pulsfrequenz ohne offengelegte Bedeutung;
- kein Fallback von regionalen Daten auf ungekennzeichnete globale Daten;
- keine Entity-API für hochvolumiges Cesium-Rendering;
- keine Plan-05D-Ausführung, Legacy-Löschung, Deployment- oder Datenbankmigration;
- keine neue Runtime-Abhängigkeit ohne gesonderten Review-Nachweis. Für den ersten
  Slice reichen die vorhandenen Frameworks und Bibliotheken.

---

## 5. Begriffe und visuelle Wahrheitsregeln

### 5.1 Stagecraft

**Stagecraft** ist visuelle Inszenierung ohne quantitative Aussage. Zulässig sind:

- Atmosphäre, Starfield, Grain und Graticule;
- ein kurzer Target-Scan nach expliziter Auswahl;
- Kameraeasing, Reveal und kontrolliertes Dimming des Kontexts;
- ein deterministischer Selection-Lift, der ausschließlich Scope und Kameraextent
  folgt und nie aus Datenwerten berechnet wird;
- statische Basisringe oder ein Scope-Sockel als Auswahlrahmen;
- zeitlich begrenzter Glow und Bloom.

Stagecraft darf nicht wie eine Legende, Skala oder Datenintensität aussehen. Sie ist
für alle in derselben Scope-Klasse vergleichbaren Ziele gleich definiert.

### 5.2 Datenkodierung

**Datenkodierung** ist jede variable visuelle Eigenschaft, die aus Records oder
Metriken berechnet wird, insbesondere Höhe, Farbe, Größe, Opazität, Linienbreite,
Geschwindigkeit, Pulsfrequenz oder Partikeldichte.

Jede Datenkodierung benötigt:

- einen stabilen `metricId` oder eine geschlossene Layer-Semantik;
- Label, Einheit, Aggregation, Skala, Domain und Clamping;
- Instant- oder Window-Zeitbasis;
- Scope-Key, Catalog-Revision und Datenrevision;
- Relation, Präzision, Completeness und ausgeschlossene Records;
- Missing-Value-Semantik und sichtbare Legende;
- Tooltip beziehungsweise Inspector-Nachweis für den konkreten Wert.

### 5.3 Datenlinse

Eine **Datenlinse** wählt eine zusammenhängende visuelle Fragestellung. Sie ändert
weder Scope noch Zeit noch Datenwahrheit. Bestehende Layer-Toggles bleiben die
Source-Kontrolle; eine Linse entscheidet nur, wie aktivierte, kompatible Sources
priorisiert und kodiert werden.

### 5.4 Szene

Eine **Szene** ist eine immutable, generation-gebundene visuelle Projektion aus
committed Scope, Zeit, Linse, Layer-Snapshots, Motion-Policy und Quality-Tier. Kamera
und GPU-Primitives sind Ergebnisse der Szene, niemals Eingaben in die Semantik.

---

## 6. Zielerlebnis und Zustandsfolge

### 6.1 World Establishing State

Der World-Scope zeigt:

- schwarzes Void und zurückhaltendes Starfield;
- steel-getönte Atmosphäre und klar lesbaren Terminator;
- stark gedimmte/desaturierte Erdoberfläche mit Nachtlichtern;
- feine Graticule und Country-Outlines;
- nur global sinnvolle Datenbewegungen, beispielsweise Satellitenorbits oder
  tatsächlich vorhandene Track-Geometrien;
- ruhiges HUD ohne automatisch geöffneten Inspector.

Photorealistic 3D Tiles sind auf Globe-/Country-Höhe verborgen oder stark gedimmt.
Sie werden erst in lokalen Ansichten als Kontext eingeblendet.

### 6.2 Target Acquisition

Hover darf ausschließlich Outline, Label und Prefetch beeinflussen. Erst ein
expliziter Click/Search/Breadcrumb-Command startet den Scope-Wechsel.

Nach dem committed Scope:

1. der globale Kontext dimmt;
2. eine feste, nicht pickbare Selection-Surface wird sichtbar;
3. ein kurzer Scan und eine doppelte emissive Kontur akzentuieren das Ziel;
4. der Scene-Presenter startet den Camera-Flight;
5. scope-abhängige Daten erscheinen erst mit passender `stateRevision`.

Pending Scope darf nie als bereits ausgewählt inszeniert werden. Während Resolve
bleibt die alte committed Szene wahr; nach Commit verschwinden alte Boundary und alte
scope-abhängige Daten unverzüglich.

### 6.3 Cinematic Dive

Der Standardflug besitzt drei visuelle Phasen:

| Phase | Ziel | Richtwert |
|---|---|---:|
| Acquire | Kontext dimmen, Zielkontur aufbauen | 250–450 ms |
| Travel | Bogenflug mit Heading/Pitch/Range-Easing | 1.2–2.2 s |
| Reveal | regionale Flächen und Datenmarks einblenden | 300–700 ms |

Die Gesamtdauer überschreitet im Normalfall 3,2 Sekunden nicht. Pointer-, Wheel- oder
Keyboard-Kameraeingabe beendet den Flug sofort, nicht aber den committed Scope.
Reduced Motion verwendet dasselbe Endziel mit Dauer `0` und einen statischen Reveal.

Deep Links und Browser-History spielen keinen künstlichen World→Country→Admin-1-
Pfad ab. Sie fitten direkt den committed Ziel-Scope und verwenden nur den Reveal.

### 6.4 Country Situation Board

Ein Country mit reviewten Children zeigt alle direkten Admin-1-Kinder vollständig.
Die Kamera endet in einer schrägen 2,5D-Perspektive. Der Hintergrund wird zu einer
ruhigen dunklen kartographischen Bühne; Terrain und Gebäude sind hier sekundär.

Ohne aktive Metrik besitzen alle Child-Surfaces dieselbe Basishöhe. Hover verwendet
eine separate, kurzlebige Overlay-Primitive und verändert weder Pick-Geometrie noch
Scope. Mit aktiver Metrik kodieren variable Höhe und Farbe genau diese eine Metrik.

Ein Country ohne Admin-1-Katalog bleibt ein Country-Leaf. Es gibt keine erfundene
Unterteilung und keinen Legacy-Fallback.

### 6.5 Regional Tactical Scene

Im Admin-1-Scope liegt die Region wie ein räumliches Tabletop unter einer schrägen
Kamera. Terrain, Photorealistic/OSM Buildings und lokale Imagery dürfen kontrolliert
zurückkehren. Daten erscheinen in getrennten Rendergruppen:

- Punkt-/Cluster-Glyphs;
- lokale Dichtezellen oder Säulen;
- echte Track-/Relation-Arcs;
- lineare Infrastruktur;
- priorisierte Labels und Leader-Callouts;
- Inspector und Legende im DOM-HUD.

Admin-2-Geometrie ist dafür nicht erforderlich. Lokale Raster-/Zellaggregation ist
eine Datenvisualisierung innerhalb des aktiven Admin-1-Containments und erzeugt
keine neue administrative Identität.

---

## 7. Modularchitektur und Seams

```text
SpatialScopeModule ───────────────┐
WorldviewTimePort ────────────────┤
WorldviewSceneDataPort ───────────┼── CinematicWorldviewModule
WorldviewLensPort ────────────────┤             │
Performance / Motion Policy ──────┘             ▼
                                      CesiumWorldviewSceneAdapter
                                      ├─ visual style
                                      ├─ scope surfaces
                                      ├─ metric surfaces
                                      ├─ glyphs/arcs/labels
                                      ├─ camera/clock
                                      └─ post-process/HUD state
```

### 7.1 Besitz

`SpatialScopeModule` besitzt weiterhin Resolve, Lineage, Navigation, Race-Semantik,
Catalog-Revision und Query-Token.

`CinematicWorldviewModule` besitzt ausschließlich:

- Szenenkompilierung und generation-sichere visuelle Updates;
- Camera-Choreografie als Best-Effort-Effekt;
- Scene-Root, Primitive-Gruppen, Clock und Post-Process-Lifecycle;
- Visual-Lens-, Motion- und Quality-Projektion;
- visuelle Diagnostics und Rendering-Fehler.

Es darf weder `dispatch(enter)` aufrufen noch Scope-Keys aus Labels, Geometrie,
Kamera oder Pick-Koordinaten ableiten.

### 7.2 Kleines externes Interface

Das Modul erfüllt den bestehenden Scope-Presentation-Port und besitzt genau einen
zweiten Update-Kanal für Daten mit anderer Kadenz:

```ts
interface CinematicWorldviewModule {
  present(
    input: ResolvedPresentationInput,
    stateRevision: number,
    signal: AbortSignal,
  ): Promise<void>;

  update(frame: WorldviewSceneFrame): void;
  diagnostics(): CinematicWorldviewDiagnostics;
  dispose(): void;
}
```

`present` wird nur von der bestehenden Scope-Seam aufgerufen. `update` akzeptiert
nur Frames, deren `scopeKey`, `catalogRevision` und `stateRevision` exakt zur letzten
committed Presentation passen. Andere Frames werden verworfen und diagnostiziert;
es gibt keinen permissiven Fallback.

### 7.3 Rendererfreier Frame

`WorldviewSceneFrame` enthält keine Cesium-, React- oder DOM-Typen. Es enthält
mindestens:

- `SpatialQueryRef` und `stateRevision`;
- aktives Zeitfenster und Cursor;
- aktive Datenlinse;
- geschlossene, typisierte Layer-Snapshots;
- Relation, Präzision, Completeness und Ausschlusszählungen je Snapshot;
- Motion-Policy und Quality-Tier;
- monotone Datenrevision beziehungsweise Observed-at-Zeit.

Ein interner reiner `SceneCompiler` übersetzt den Frame in einen immutable
`ScenePlan`. Der Cesium-Adapter übersetzt den Plan in GPU-Ressourcen. Tests verwenden
einen Recording-Adapter; der Produktionsadapter ist Cesium. Damit ist die
Presenter-Seam real und nicht hypothetisch.

### 7.4 Abhängigkeiten

- Scope, Zeit, Lens und Performance sind in-process Snapshots.
- Backend-/CHRONIK-Reads sind remote but owned und werden über bestehende
  transportfreie Ports sowie HTTP-Adapter angebunden.
- Cesium/Ion ist eine externe Renderabhängigkeit hinter dem Scene-Adapter.
- Der Presenter führt keine eigenen ungeprüften Remote-Downloads aus.

### 7.5 React-Integration

React komponiert Modul und Adapter, speist Daten-Snapshots und rendert HUD/Legende.
Kein Animationsframe erzeugt React-State. Per-frame-Mutationen bleiben innerhalb des
Cesium-Adapters. `WorldviewPage` erhält keine neue Layer-spezifische Orchestrierungs-
Kaskade.

---

## 8. Cesium-Renderarchitektur

### 8.1 Scene-Root und Gruppen

Der Cesium-Adapter besitzt genau eine WorldView-Scene-Root. Darunter liegen maximal
folgende logische Gruppen:

1. Base Style und Atmosphere Controls;
2. aktive Scope-Surface und Child-Outlines;
3. stabile, unsichtbare Child-Pick-Surface;
4. optionale Metric-Surfaces;
5. Network-/Track-Geometrie;
6. statische und animierte Glyphs;
7. Labels/Callouts;
8. kurzlebige Transition-/Hover-Overlays.

Es existiert höchstens eine aktive und eine staging Scene-Generation. Der Adapter
tauscht keine einzelne Gruppe unter neuer Semantik sichtbar aus, bevor alle für den
Frame verpflichtenden Gruppen ready und generation-current sind.

### 8.2 Primitive-Wahl

| Visuelles Element | Cesium-Strategie |
|---|---|
| Ground Mask / Scope Fill | gebatchte `GroundPrimitive` |
| feste oder metrische Extrusion | `Primitive` + `PolygonGeometry`/`WallGeometry` |
| Scope- und Glow-Outlines | geschichtete `GroundPolylinePrimitive` bzw. `PolylineGeometry` |
| Track-/Relation-Arcs | `PolylineCollection` oder gebatchte `PolylineGeometry` |
| hochvolumige Punkte | wenige große `BillboardCollection`s nach Update-Frequenz |
| Labels | budgetierte `LabelCollection` |
| lokale Effekte | Material-Uniforms, Ellipsen oder begrenzte `ParticleSystem`s |
| globale Bildwirkung | benannte `PostProcessStage`s |

Keine hochvolumige Darstellung verwendet die Entity-API.

### 8.3 Scope-Surface und Picking

Die bestehende, an `childrenLods[preferredLod]` gepinnte Pick-Surface bleibt
unsichtbar und über die gesamte `stateRevision` identisch. Camera-LOD, Hover,
Extrusion, Metrik oder Post-Processing dürfen sie weder ersetzen noch neu bauen.

Die sichtbare Child-Surface ist getrennt. Operative Datenpicks behalten Priorität vor
`spatial-child`; Hover- und Stagecraft-Overlays sind nicht pickbar. Ein visueller
Fehler darf keine Legacy-Identität aktivieren.

### 8.4 Selection-Lift und metrische Extrusion

Der Selection-Lift ist eine deterministische Funktion aus Scope-Kind und
Cameraextent, mit festen Min-/Max-Clamps. Er ist unabhängig von Datenwerten und wird
als Auswahlrahmen beschrieben.

Metrische Extrusion lebt in einer separaten Gruppe. Sie verwendet ausschließlich
Samples des `SpatialMetricPort` und die Regeln aus Spatial-Spec `11 §19`. Bei
fehlenden, stale oder inkompatiblen Samples wird keine variable Höhe gerendert.

### 8.5 Visual Style

Die Hlíðskjalf-Palette bleibt eigenständig:

- `steel` für Atmosphäre und globalen Kontext;
- `stone`/`bone` für Kartographie und neutrale Labels;
- `amber` für explizite Analystenaktion und Selection;
- `sentinel`/`ember` für Threat/Severity;
- `sage` für Umwelt- und Observation-Signale.

Farben werden aus CSS-Tokens aufgelöst. Der Presenter besitzt keine zweite
hardcodierte Farbwahrheit. Der externe Cyan/Green-Look wird nicht kopiert.

Auf World-/Country-Höhe wird Photoreal Content verborgen oder gedimmt, damit
Kartographie und Datenmarks die visuelle Hierarchie besitzen. Im Admin-1-Scope darf
Photoreal/Terrain nach dem Reveal wieder sichtbar werden. Neue Basemap-Assets
benötigen Source Lock, Lizenznachweis und Same-origin-Auslieferung.

### 8.6 Post-Processing

Bloom wird mild und global eingesetzt; selektiver Glow entsteht primär durch
geschichtete Geometrie und emissive Materialien. So hängt die Lesbarkeit nicht von
einem fragilen Screen-Space-Maskenpfad ab.

Alle Stages besitzen eindeutige Ownership-Namen. Cinematic Stages, CRT, Night Vision
und FLIR dürfen sich nicht gegenseitig über unspezifisches `removeAll` löschen. Die
Stage-Reihenfolge ist deterministisch getestet. Kein Shadertext stammt aus Daten,
Konfiguration oder LLM-Ausgabe.

### 8.7 Gemeinsamer Animation Clock

Genau ein `scene.preRender`-Listener steuert alle cineastischen Uniforms und
registrierten animierten Marks. Bestehende Layer-Schleifen werden nur dann ersetzt,
wenn ihre Verhaltensabdeckung am neuen Clock-Interface vorhanden ist; es entsteht
keine zweite parallele Dauerschleife.

Der Clock läuft nur, wenn mindestens eine aktive Animation existiert. Stagecraft ist
standardmäßig zeitlich begrenzt. Dauerbewegung ist nur für reale Live-Daten oder
explizit erlaubte Ambient-Motion zulässig und muss pausierbar sein.

---

## 9. Datenlinsen und regionale Visualisierung

### 9.1 Geschlossene V1-Linsen

| Linse | Primäre Frage | Zulässige Marks |
|---|---|---|
| `situation` | Was geschieht im ausgewählten Raum und Zeitfenster? | Event-Dichte, Severity-Glyphs, zeitliche Änderung |
| `thermal` | Wo liegen thermische Aktivität und Anomalien? | FIRMS-Punkte, Cluster, FRP-Intensität |
| `mobility` | Welche Bewegungen schneiden den Scope? | reale Tracks, Trails, Kursvektoren |
| `infrastructure` | Welche relevante Infrastruktur liegt im oder schneidet den Scope? | Facilities, Kabel, Pipelines |
| `environmental` | Welche Natur- und Umweltereignisse liegen im Scope? | Erdbeben, GDACS, EONET, Observation-Glyphs |

`situation` ist die Default-Linse. Eine spätere Linse benötigt einen Spec-Delta und
eine geschlossene Capability-Matrix; freie String-Linsen sind unzulässig.

### 9.2 Erste verbindliche Metrik

Der erste Country-Level-Hero-Slice verwendet:

```text
metricId:      chronik.events.count
label:         Ereignisse
unit:          events
aggregation:   count
scale:         log
domain:        [0, 1000]
heightMeters:  [0, 80000]
timeBasis:     window
missingValue:  hatched
```

Höhe und Flächenintensität kodieren denselben Count. Severity bleibt eine getrennte
Punkt-/Glyph-Dimension und verändert die Flächenhöhe nicht. Tooltip und Legende
zeigen Count, Zeitfenster, Scale, located/unlocated, Completeness und Präzision.

Die Transformation lautet `log1p(count) / log1p(1000)` und wird auf `[0, 1]`
geclampt. Ein echter Count `0` ist ein valider Nullwert auf Basishöhe; `null` ist
Missing Data und wird ausschließlich über das Hatch-Muster dargestellt. Werte über
1.000 bleiben im Tooltip exakt, werden visuell aber am dokumentierten Maximum
geclampt. Domain und Höhenbereich sind Bestandteil der versionierten
Metric-Definition und dürfen nicht pro Frame aus dem gerade sichtbaren Sample neu
berechnet werden.

Ein approximativer oder partieller Sample darf sichtbar sein, wenn Methode und
Coverage unübersehbar beschriftet sind. Er darf nicht als „exact“ erscheinen.

### 9.3 Country-Level-Aggregation

Country-Samples sind nach direkten Child-`scopeKey`s adressiert. Der Presenter
berechnet keine administrative Zuordnung aus sichtbarer Render-LOD. Zulässig sind:

1. serverseitige Aggregation über materialisierte kanonische Admin-1-Keys; oder
2. ein zentraler Point-in-Child-Containment-Adapter über reviewte fixe Geometrie mit
   expliziter Präzision und Ausschlusszählung.

Welche Transportform verwendet wird, gehört in den späteren Implementierungsplan.
Beide Adapter müssen dasselbe `SpatialMetricSnapshot`-Interface erfüllen.

### 9.4 Admin-1-Lokalaggregation ohne Admin-2

Im Admin-1-Scope dürfen georeferenzierte Records innerhalb des aktiven festen
Containments in lokale Zellen aggregiert werden. Die Zellen sind reine
Visualisierung, keine neuen Scopes.

- Zellgröße folgt Camera-LOD und besitzt feste Min-/Max-Budgets.
- Nur `inside` zählt als strict; `boundary-uncertain` wird ausgeschlossen und gezählt.
- Unlocated Records werden nie am Centroid erfunden.
- Höhe/Farbe folgen derselben sichtbaren Metrikdefinition wie die Legende.
- Kritische Einzelereignisse können zusätzlich als priorisierte Glyphs erscheinen.

### 9.5 Layer-Semantik

Die bestehende Capability-Registry bleibt Eigentümerin der Aussage:

- Punktlayer `occurs-in`: strict Point-in-Boundary oder serverseitiger Scope-Key;
- Tracks `intersects`: bei positivem Schnitt bleibt der vollständige Track sichtbar;
- lineare Infrastruktur `intersects`: echte Geometrie-Intersection oder sichtbar
  deklarierter Context, niemals Startpunktfilter;
- Satelliten `global-context`: global und als solcher beschriftet;
- Terrain, Imagery und 3D Tiles `context`: nie als regional gefilterte Daten ausgeben.

Jeder neue visuelle Layer muss zuerst eine vollständige Registry-Zeile und stale
policy besitzen. Präsentationsreife ersetzt keine Datenreife.

---

## 10. Catalog-Abdeckung

### 10.1 Erster Produktumfang

- World und vorhandene Countries bleiben global verfügbar.
- Ukraine behält ihre 27 reviewten Admin-1-Scopes.
- Deutschland erhält alle 16 Bundesländer als vollständiges Child-Set.
- Andere Countries ohne reviewten Admin-1-Katalog bleiben Blätter.
- Admin-2 bleibt deaktiviert.

### 10.2 Deutschland

Die Bundesländer verwenden die bestehende Admin-1-Quellenpolitik und kanonische
ISO-3166-2-Keys, sofern der reviewte Crosswalk eindeutig ist. Source Lock,
Attribution, politische Representation, Double-build, LOD-, Wire-, Heap-, Ring-,
Vertex- und Containment-Feasibility-Gates gelten unverändert.

Ein unvollständiges Child-Set stoppt die Deutschland-Aktivierung. Der Renderer darf
nicht „die verfügbaren“ Bundesländer als vollständige administrative Wahrheit
darstellen.

### 10.3 Generizität

Renderer, SceneCompiler, Lens und Metric-Adapter unterscheiden nicht nach `UKR` oder
`DEU`. Alle Unterschiede stammen aus Catalog, Capability und Daten-Snapshots. Ein
Ländername in Renderlogik oder Tests ist nur als Fixture zulässig, nicht als Branch.

---

## 11. Interaktion und Accessibility

- Breadcrumb, Ascend, Browser-History, Search und Escape behalten ihre bestehende
  Semantik.
- Scope-Click und operative Entity-Auswahl bleiben unterscheidbar; Entity-Pick hat
  Vorrang.
- Hover verändert nur temporäre Präsentation und Prefetch, niemals Scope oder Daten.
- Jede Linse besitzt eine textuelle Überschrift, Legende und zugängliche Beschreibung.
- Farbe ist niemals der einzige Informationsträger; Form, Label oder Muster ergänzen
  kategoriale und Missing-Value-Zustände.
- Eine dauerhaft gemountete Live-Region meldet committed Scope, aktive Linse,
  Presentation-Problem und Ladeabschluss, aber keine per-frame Änderungen.
- Es gibt eine sichtbare Motion-Einstellung `full | reduced | static`.
  `prefers-reduced-motion` startet mindestens in `reduced` und darf nicht automatisch
  auf `full` hochgestuft werden.
- `static` bewahrt alle Datenmarks, Legenden und Picks ohne nicht-essenzielle Bewegung.
- Keine Vollbildblitze. Pulse überschreiten 2 Hz nicht und bleiben flächenmäßig
  begrenzt.
- Kameraanimation ist jederzeit abbrechbar. Fokus wird nach Child-Click oder Reveal
  nicht unkontrolliert versetzt.
- Für metrische Flächen existiert eine tabellarische/Inspector-Alternative mit
  Scope-Label, Wert, Einheit, Zeit und Coverage.

---

## 12. Performance, Quality und Lifecycle

### 12.1 Quality-Tiers

Der bestehende `PerformanceGuard` liefert die Qualitätsstufe:

| Tier | Verhalten |
|---:|---|
| 0 | volle Choreografie, budgetierte Partikel, Pulse und Trails |
| 1 | weniger Partikel, kürzere Trails und weniger Labels |
| 2 | Pulse nur für priorisierte/selektierte Ereignisse |
| 3 | statische Arcs und keine Ambient-Motion |
| 4 | vollständig statische, semantisch gleichwertige Szene |

Degradation verändert nie Scope, Query, Count, Coverage oder Pickbarkeit. Recovery
erhöht Qualität stufenweise und baut keine stabile Pick-Surface neu.

### 12.2 Budgets

- Ziel auf der reviewten Desktop-Workstation: Median mindestens 55 FPS und p95
  Frame-Time höchstens 25 ms über eine deterministische 60-Sekunden-Szene.
- Hard Gate: keine mehr als zwei Sekunden anhaltende Framerate unter 30 FPS.
- Kein eigener Main-Thread-Task über 50 ms; Boundary-/Mark-Konvertierung bleibt
  gechunkt mit Ziel unter 8 ms pro Chunk.
- Maximal 10.000 gleichzeitig animierte Marks; weitere Marks werden deterministisch
  nach Relevanz, Frustum, Lens und LOD budgetiert.
- Wenige große Billboard-/Polyline-Collections werden nach Update-Frequenz getrennt.
- Maximal eine aktive und eine staging Scene-Generation.
- Ein Scope-/Lens-Wechsel abortet alle veralteten Builds, Flights und Data-Frames.

### 12.3 Lifecycle-Gates

- 100 Zyklen `world ↔ country ↔ admin1` ohne monotones Wachstum von Primitives,
  Collections, Post-Process-Stages, Clock-Callbacks, Event-Listenern oder Asset-Leases;
- 100 Lens-Wechsel innerhalb desselben Scope ohne Pick-Surface-Rebuild;
- keine zerstörte Primitive, Stage oder Collection bleibt referenziert;
- kein stale Frame erscheint unter neuer Scope-/Lens-Beschriftung;
- Long-session-Soak mit Live-Daten, Timeline-Seek, Kamerainteraktion und
  Degradation/Recovery;
- Runtime-Rollback auf den operationalen Presenter ohne Daten- oder Catalog-Rollback.

---

## 13. Fehler, Security und Provenance

### 13.1 Fail-closed

- Scope-Präsentationsfehler erzeugen `PRESENTATION_FAILED`; Scope und Queries bleiben
  committed und textuell nutzbar.
- Lens-/Metric-Fehler verbergen nur die betroffene Kodierung und zeigen eine sichtbare
  Diagnose. Sie aktivieren keine globale oder Legacy-Datenquelle.
- Frame-Identitätsmismatch wird verworfen und gezählt.
- Fehlende Geometrie erzeugt keine approximative Ersatzfläche.
- Post-Process- oder Particle-Fehler degradieren auf geschichtete statische
  Primitives.

### 13.2 Security

- Shader, Materialtypen, Lens-IDs, Metric-IDs und Renderstrategien sind statisch
  allowlisted.
- Daten dürfen Uniformwerte innerhalb validierter Domains liefern, aber keinen GLSL-
  Text, Materialtyp, Asset-URL oder Renderbefehl.
- Kein LLM erzeugt ScenePlan, Query, Shader oder Scope-Key.
- HTTP-Adapter bleiben same-origin, abortbar und schema-validiert.
- Keine Secrets, Rohdatenpayloads oder personenbezogenen Labels in Diagnostics.
- Cesium-/Browser-Picks werden gegen geschlossene typisierte IDs validiert.

### 13.3 Provenance

Cartography- und Metric-Inspector zeigen:

- Catalog- und Datenrevision;
- Boundary-Policy und Quellenattribution;
- Metric-Definition, Datenquelle und observed-at;
- Relation, Präzision, Completeness und Ausschlusszählungen;
- Darstellungshinweis für strittige oder politisch sensible Grenzen.

Neue Texturen, Basemaps oder Icon-Atlanten benötigen Lizenz- und Source-Lock-Nachweis.
Das externe Inspirationsrepository wird nicht als Runtime- oder Build-Abhängigkeit
eingetragen.

---

## 14. Diagnostics und Observability

`CinematicWorldviewDiagnostics` liefert mindestens:

- committed `scopeKey`, `catalogRevision`, `stateRevision` und Lens;
- aktive/staging Scene-Generationen;
- Primitive-, Collection-, Label-, Stage- und Clock-Callback-Zahlen;
- High-water-Werte und aktive Asset-Leases;
- Frame-Time/FPS und Quality-Tier;
- gestartete, abgeschlossene, abgebrochene und verworfene Transitions;
- akzeptierte und wegen Identity-Mismatch verworfene Frames;
- Marks pro Lens/Layer sowie Degradation-/Culling-Zahlen;
- Metric- und Coverage-Status ohne Rohrecords.

Produktionslogs sind aggregiert und bounded. Wiederholte identische Fehler werden wie
bei den Legacy-Diagnostics unterdrückt gezählt statt unbegrenzt ausgegeben.

---

## 15. Rollout, Kompatibilität und Plan 05D

### 15.1 Unabhängiger Presentation-Schalter

Der cineastische Presenter erhält einen vom Spatial-Scope-Flag unabhängigen
Runtime-Modus:

```text
worldview_presentation_mode = operational | cinematic
```

Der Modus stammt im Produktionsbetrieb aus validierter Client-Konfiguration, nicht
aus einem frei manipulierbaren Query-Parameter. Initial bleibt `operational` Default;
Canary und Review nutzen `cinematic`. Nach visueller Abnahme, Performance-Gates,
Soak und Rollback-Probe kann `cinematic` separat Default werden.

Ein Mode-Wechsel verändert weder URL-Scope noch Katalog- oder Datenrevision. Beide
Presenter verwenden denselben `SpatialScopeModule`, Catalog und Layer-Snapshots.

### 15.2 Rollback

Rollback bedeutet ausschließlich:

- neue Scene-Root, Stages und Clock deterministisch disposen;
- operationalen Cesium-Presenter wieder attachen;
- committed Scope, Zeit, Selection und Daten unverändert bewahren.

Kein Schema-, Datenbank-, Catalog- oder Ingestion-Rollback ist dafür erforderlich.

### 15.3 Plan 05D

Diese Spec entsperrt Plan 05D nicht. Legacy-Renderer, `CountryTarget`,
`useCountryHitTest`, `_topoIndex` und `VITE_SPATIAL_SCOPE_ENABLED` bleiben bis zu den
bereits definierten Phase-D-Gates erhalten. Der cineastische Presenter muss zunächst
gegen operationalen Presenter und Artefakt-Rollback beweisen, dass die neue
Präsentationsschicht langzeittauglich ist.

---

## 16. Abnahme- und Review-Evidenz

### 16.1 Verbindliche Hero-Frames vor breiter Umsetzung

Vor Migration weiterer Layer werden vier deterministische Zielzustände festgelegt
und visuell abgenommen:

1. `world` — idle establishing scene;
2. `country:UKR` — target acquisition und Country Situation Board;
3. `country:UKR` — 27 Oblaste mit `chronik.events.count`;
4. `admin1:iso3166-2:UA-71` oder ein reviewter Konflikt-Scope — regional tactical
   scene mit CHRONIK und FIRMS.

Nach Deutschland-Catalog-Aktivierung folgt zusätzlich:

5. `country:DEU` — vollständige 16 Bundesländer im identischen generischen Pfad.

Jeder Frame verwendet fixe Viewportgröße, Camera, Uhrzeit, Datenfixture, Lens,
Quality und Motion-Policy. Die Evidenz umfasst Screenshot, kurze Transition-Aufnahme,
DOM-/Accessibility-Snapshot und Diagnostics.

### 16.2 Automatisierte Gates

- reine SceneCompiler-Tests für alle Linsen, Missing-/Stale-/Coverage-Zustände;
- Recording-Adapter-Tests über das externe Modul-Interface;
- Cesium-Integrationstests für Primitive-Typen, Pick-ID, Staging, Stage-Reihenfolge,
  Camera-Cancel und Disposal;
- Visual-Regression-Screenshots für alle Hero-Frames in full und static;
- Accessibility-Tests für Motion, Live-Region, Legende, Keyboard und Tabellenersatz;
- Point-, Track- und Metric-Truthfulness-Tests pro aktivierter Capability;
- Katalog-Double-build und Feasibility für Deutschland;
- 100-Scope-/100-Lens-Zyklen und Long-session-Soak;
- vollständige Frontend-, Backend-, Intelligence- und Data-Ingestion-Gates vor
  Default-on, soweit der spätere Implementierungsplan diese Systeme verändert.

### 16.3 Manuelle Abnahme

Automatisierte Korrektheit ersetzt keine Art-Direction-Abnahme. Vor breiter
Layer-Migration bestätigt der Product Owner ausdrücklich:

- WorldView wirkt als zusammenhängende Szene statt als Satellitenkarte mit Overlay;
- World→Country→Admin-1 besitzt wahrnehmbare, aber nicht langsame Dramaturgie;
- regionale Daten sind innerhalb von fünf Sekunden interpretierbar;
- die visuelle Hierarchie bleibt Hlíðskjalf statt Referenzkopie;
- Full, Reduced und Static sind jeweils produktgeeignet.

Ohne diese Abnahme stoppt die visuelle Expansion; semantische Tests werden nicht
abgeschwächt, um ein unbefriedigendes Design freizugeben.

---

## 17. Abgelehnte Alternativen

### Externes Three.js-Template oder zweiter Renderer

Abgelehnt. Es dupliziert Globe, Kamera, Terrain, Picking, Layer und GPU-Lifecycle und
erzeugt Framework-, Asset- und Lizenzrisiken. Cesium besitzt die benötigten
Geometrie-, Material-, Post-Process-, Particle- und Camera-Fähigkeiten bereits.

### Post-Processing als alleinige Lösung

Abgelehnt. Bloom und Color-Grading erzeugen Stimmung, aber keine räumliche Tiefe,
korrekte Datenmarks oder regionale Semantik. Die Szene braucht echte Primitives und
ein Datenmodell.

### Alle bestehenden Layer nur heller machen

Abgelehnt. Mehr Glow auf unkoordinierten Layern erzeugt visuelles Rauschen. Linsen,
Priorität, gemeinsame Choreografie und Scope-fähige Daten sind erforderlich.

### React-State pro Frame

Abgelehnt. Es koppelt Animation an Re-render, erschwert Disposal und verteilt
Szenenwissen über Caller. Per-frame-Mutation gehört in den Cesium-Adapter.

### Render-LOD als Containment oder Aggregationsquelle

Abgelehnt. Sichtbare Geometrie kann kameraabhängig und vereinfacht sein. Datenwerte
verwenden feste Containment- oder kanonische serverseitige Zuordnung.

### Variable Showroom-Extrusion und Fake-Arcs

Abgelehnt. Variable Höhe und Linien suggerieren Daten. Selection-Lift bleibt
deterministische Stagecraft; alles Variable benötigt eine überprüfbare Kodierung.

### Vollständiger globaler Admin-1-Rollout im ersten Slice

Abgelehnt. Ukraine beweist den visuellen Pfad, Deutschland beweist Generizität.
Weitere Theater folgen nur nach Catalog-, Daten- und Performance-Evidenz.

### Kopplung an Plan 05D

Abgelehnt. Neue visuelle Abnahme und spätere Legacy-Löschung besitzen getrennte
Risiken, Rollbacks und Freigaben.

---

## 18. Pflicht-Review

Das Review beantwortet mindestens:

1. Ist die Präzedenz gegenüber Spatial `01`, `06`, `11` und `14` eindeutig und eng
   genug?
2. Bleibt der Scope-Core vollständig unabhängig von Szene, Kamera, Lens und Metric?
3. Ist das `CinematicWorldviewModule` tief genug, oder leakt Scene-Orchestrierung in
   `WorldviewPage` beziehungsweise einzelne Layer?
4. Sind Stagecraft und Datenkodierung für Analysten eindeutig unterscheidbar?
5. Sind `chronik.events.count`, lokale Zellen und Coverage-Regeln semantisch
   verteidigbar?
6. Kann Deutschland vollständig und source-locked als Admin-1 aktiviert werden?
7. Sind Cesium-Primitive-, Post-Process-, Camera-, Pick- und Disposal-Annahmen mit
   Version 1.142 korrekt?
8. Sind Motion-, Flash-, Keyboard-, Live-Region- und Tabellenanforderungen ausreichend?
9. Sind FPS-, Main-Thread-, Mark-, Collection- und Soak-Budgets realistisch und hart
   genug?
10. Ist operational↔cinematic Rollback ohne Cross-Scope-Stale-Zustand beweisbar?
11. Enthält die Spec irgendeine stille Freigabe von Admin-2, Deployment, Legacy-
    Löschung oder ungescopten Daten? Falls ja, ist das ein Stop-Finding.

Review-Ausgang ist `PASS`, `PASS WITH REQUIRED FIXES` oder `FAIL`. Alle Findings
erhalten ID, Schweregrad, harte Evidenz, normative Heimat und Disposition. Erst nach
eingearbeiteten Required Fixes und Abschluss-PASS darf ein Implementierungsplan
geschrieben werden.

---

## 19. Primärquellen und bestehende normative Nachbarn

### Repo-intern

- [Spatial Scope — modularer Spec-Index](2026-07-31-spatial-scope-drilldown-design.md)
- [Spatial 01 — Architektur und Invarianten](2026-07-31-spatial-scope-drilldown/01-architecture-and-invariants.md)
- [Spatial 06 — Cesium und Layer-Semantik](2026-07-31-spatial-scope-drilldown/06-cesium-and-layer-semantics.md)
- [Spatial 11 — UX und 3D-Metriken](2026-07-31-spatial-scope-drilldown/11-ux-and-3d-metrics.md)
- [Spatial 12 — Fehler, Security und Observability](2026-07-31-spatial-scope-drilldown/12-errors-security-and-observability.md)
- [Spatial 14 — Rollout und Abnahme](2026-07-31-spatial-scope-drilldown/14-rollout-and-acceptance.md)
- [Worldview Layer-Design — Hlíðskjalf Noir](2026-04-30-worldview-layer-design.md)
- [Globe Layers Evolution](2026-04-05-globe-layers-evolution-design.md)
- `services/frontend/src/pages/WorldviewPage.tsx`
- `services/frontend/src/components/globe/GlobeViewer.tsx`
- `services/frontend/src/components/globe/PerformanceGuard.tsx`
- `services/frontend/src/spatial/cesium/CesiumSpatialScopeAdapter.ts`
- `services/frontend/src/spatial/cesium/buildScopePrimitives.ts`
- `services/frontend/src/spatial/layerScopePolicy.ts`

### Extern, nur technische Primärdokumentation

- [CesiumJS PolygonGeometry](https://cesium.com/learn/cesiumjs/ref-doc/PolygonGeometry.html)
- [CesiumJS Primitive](https://cesium.com/learn/cesiumjs/ref-doc/Primitive.html)
- [CesiumJS MaterialAppearance](https://cesium.com/learn/cesiumjs/ref-doc/MaterialAppearance.html)
- [CesiumJS PostProcessStage](https://cesium.com/learn/cesiumjs/ref-doc/PostProcessStage.html)
- [CesiumJS Camera](https://cesium.com/learn/cesiumjs/ref-doc/Camera.html)
- [CesiumJS BillboardCollection](https://cesium.com/learn/cesiumjs/ref-doc/BillboardCollection.html)
- [CesiumJS ParticleSystem](https://cesium.com/learn/cesiumjs/ref-doc/ParticleSystem.html)
- [Visual inspiration only: three-scope-map-skill](https://github.com/songsummer920-dazzle/three-scope-map-skill)
