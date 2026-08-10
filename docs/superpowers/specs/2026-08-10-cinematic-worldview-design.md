# Cinematic WorldView — Cesium Scene and Scoped Data Visualization

- **Spec-Datum:** 2026-08-10
- **Status:** Draft — Required Fixes aus zwei adversarialen Review-Runden
  eingearbeitet; unabhängiger Abschluss-PASS erforderlich, nicht umsetzungsfreigegeben
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

Der freigegebene
[Spatial-Scope-Spec-Satz](2026-07-31-spatial-scope-drilldown-design.md) bleibt
normativ. Die Required Fixes beider adversarialer Reviews wurden in ihren einzigen
normativen Heimaten gelandet:

- `01 §4.2` besitzt die globale Trennung zwischen Clean-room-Stagecraft und
  quantitativer Datenkodierung;
- `06 §12.1/§13` besitzt Presentation-Port, einzigen Cesium-Root, Scene-State-Lease,
  Viewer-langlebige Post-Process-Ownership und Point-Containment-Accounting;
- `07 §14.2` besitzt `SpatialApplicationV1` einschließlich unveränderter CHRONIK-
  Szenenprojektion und aller vier Exclusion-Counter;
- `11 §18.2/§18.5/§19` besitzt Keyboard-Äquivalenz, Motion-Policy und
  Spatial-Metric-Verträge;
- `14 §26/§28` besitzt Shared-Refactor-Stufe, Mode-Matrix, beide Rollback-Domänen
  und die eng gefassten abgelehnten Alternativen;
- der Spatial-Index registriert diese Verträge und diese Erweiterungs-Spec.

Diese Spec besitzt ausschließlich die neuen Cinematic-Scene-, Frame-, Lens- und
Diagnostics-Verträge. Sie dupliziert die vorgenannten Regeln nicht als Override.
Bis zum dokumentierten Abschluss-PASS sind auch ihre neuen Verträge Draft.

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
9. Ukraine bildet die erste belegte Admin-1-Produktabdeckung. Deutschland folgt erst
   nach eigenem Source-Lock-/Catalog-Promotion-Gate; der Renderer enthält keinerlei
   landesspezifischen Sondercode.
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
- flache, nicht pickbare Auswahlkonturen und statische Basisringe mit je Scope-Klasse
  festen Parametern;
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

Photorealistic 3D Tiles sind auf Globe-/Country-Höhe verborgen. Sie werden erst in
lokalen Ansichten als Kontext eingeblendet; V1 versucht dort kein Dimming parallel
zum bereits vorhandenen `customShader`.

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
| Acquire | Kontext dimmen, Zielkontur aufbauen | 250–400 ms |
| Travel | Bogenflug mit Heading/Pitch/Range-Easing | 1.2–2.0 s |
| Reveal | regionale Flächen und Datenmarks einblenden | 300–600 ms |

Die Phasen dauern höchstens `400 + 2.000 + 600 = 3.000 ms`; die Gesamtdauer
überschreitet einschließlich Scheduling-Toleranz 3,2 Sekunden nicht. Pointer-, Wheel- oder
Keyboard-Kameraeingabe beendet den Flug sofort, nicht aber den committed Scope.
Reduced Motion verwendet dasselbe Endziel mit Dauer `0` und einen statischen Reveal.

Deep Links und Browser-History spielen keinen künstlichen World→Country→Admin-1-
Pfad ab. Sie fitten direkt den committed Ziel-Scope und verwenden nur den Reveal.

### 6.4 Country Situation Board

Ein Country mit reviewten Children zeigt alle direkten Admin-1-Kinder vollständig.
Die Kamera endet in einer schrägen 2,5D-Perspektive. Der Hintergrund wird zu einer
ruhigen dunklen kartographischen Bühne; Terrain und Gebäude sind hier sekundär.

Ohne aktive Metrik sind alle Child-Surfaces flache Ground-Primitives mit identischen
Styleparametern. Hover verwendet
eine separate, kurzlebige Overlay-Primitive und verändert weder Pick-Geometrie noch
Scope. Mit aktiver Metrik kodiert zunächst Farbe genau diese eine Metrik; Höhe kommt
nur nach dem separaten Extrusions-Promotion-Gate hinzu.

Ein Country ohne Admin-1-Katalog bleibt ein Country-Leaf. Es gibt keine erfundene
Unterteilung und keinen Legacy-Fallback.

### 6.5 Regional Tactical Scene

Im Admin-1-Scope liegt die Region wie ein räumliches Tabletop unter einer schrägen
Kamera. Terrain, Photorealistic/OSM Buildings und lokale Imagery dürfen kontrolliert
zurückkehren. Daten erscheinen in getrennten Rendergruppen:

- Punkt-/Cluster-Glyphs;
- lokale Dichtezellen, nach Metric-Promotion optional Säulen;
- nach Capability-Promotion echte Track-/Relation-Arcs;
- nach Capability-Promotion lineare Infrastruktur;
- priorisierte Labels und Leader-Callouts;
- Inspector und Legende im DOM-HUD.

Admin-2-Geometrie ist dafür nicht erforderlich. Lokale Raster-/Zellaggregation ist
eine Datenvisualisierung innerhalb des aktiven Admin-1-Containments und erzeugt
keine neue administrative Identität.

---

## 7. Modularchitektur und Seams

```text
existing stores ── WorldviewSceneFrameAssembler ── WorldviewSceneFrame
                                                        │
SpatialScopeModule ──────────────────────────────────────┼─ CinematicWorldviewModule
                                                        │           │
                                                        ▼           ▼
                                             RecordingSceneAdapter  ViewerSpatialCesiumRuntime
                                                                     └─ one root/state lease

GlobeViewer ── WorldviewPostProcessController (viewer lifetime)
                         ▲
                         └─ allowlisted strategy slots
```

### 7.1 Besitz

`SpatialScopeModule` besitzt weiterhin Resolve, Lineage, Navigation, Race-Semantik,
Catalog-Revision und Query-Token.

`CinematicWorldviewModule` besitzt ausschließlich:

- Szenenkompilierung und generation-sichere visuelle Updates;
- Camera-Choreografie als Best-Effort-Effekt;
- Visual-Lens-, Motion- und Quality-Projektion;
- visuelle Diagnostics und Rendering-Fehler.

`ViewerSpatialCesiumRuntime` besitzt gemäß Spatial `06 §12.1` als einziges Module
Scene-Root, Primitive-Gruppen, Scene-State-Lease und Clock. Operational und
Cinematic sind darin wechselseitige Strategien. `GlobeViewer` besitzt unabhängig
von Spatial-Flag und Mode genau einen langlebigen `WorldviewPostProcessController`;
die aktive Strategie besitzt nur ihren allowlisteten Slot. Ein Mode-Wechsel erzeugt
weder eine zweite Root, einen zweiten Stage-Owner noch eine zweite Scope-State-
Machine.

Das `CinematicWorldviewModule` darf weder `dispatch(enter)` aufrufen noch Scope-Keys
aus Labels, Geometrie, Kamera oder Pick-Koordinaten ableiten.

### 7.2 Kleines externes Interface

Das Modul erfüllt den bestehenden Scope-Presentation-Port und besitzt genau einen
zweiten Update-Kanal für Daten mit anderer Kadenz:

```ts
interface CinematicWorldviewModule {
  present(
    input: ResolvedPresentationInput,
    stateRevision: number,
    signal: AbortSignal,
  ): Promise<PresentationOutcome>;

  update(frame: WorldviewSceneFrame): void;
  diagnostics(): CinematicWorldviewDiagnostics;
  dispose(): void;
}
```

`present` besitzt exakt die Outcome-Semantik aus Spatial `06 §12.1`; die heute im
Produktionscode vorhandene `Promise<void>`-Drift ist eine verpflichtende
RED→GREEN-Vorbedingung des späteren Plans. `update` akzeptiert nur Frames, deren
`query.scopeKey`, `query.catalogRevision` und `stateRevision` exakt zur letzten
committed Presentation passen. Andere Frames werden verworfen und diagnostiziert;
es gibt keinen permissiven Fallback.

### 7.3 Rendererfreier Frame

`WorldviewSceneFrame` enthält keine Cesium-, React- oder DOM-Typen. V1 ist
geschlossen; neue Felder, Layer oder freie String-IDs benötigen einen Spec-Delta:

```ts
type WorldviewLensId =
  | "situation"
  | "environmental"
  | "thermal"
  | "mobility"
  | "infrastructure";

interface ChronikSceneSnapshot {
  readonly kind: "chronik-events";
  readonly dataRevision: string;
  readonly observedAt: string;
  readonly spatialApplication: SpatialApplicationV1;
  readonly records: readonly {
    readonly eventId: string;
    readonly longitude: number;
    readonly latitude: number;
    readonly occurredAt: string;
  }[];
}

interface EarthquakeSceneSnapshot {
  readonly kind: "earthquakes";
  readonly dataRevision: string;
  readonly observedAt: string;
  readonly application: StrictPointLayerApplication<{
    readonly earthquakeId: string;
    readonly longitude: number;
    readonly latitude: number;
    readonly occurredAt: string;
    readonly magnitude: number;
    readonly depthKm: number;
  }>;
}

interface WorldviewSceneFrame {
  readonly query: SpatialQueryRef;
  readonly stateRevision: number;
  readonly frameRevision: number;
  readonly time: {
    readonly start: string;
    readonly end: string;
    readonly cursor: string;
    readonly mode: "live" | "replay";
  };
  readonly lens: WorldviewLensId;
  readonly motion: WorldviewMotionSnapshot;
  readonly qualityTier: 0 | 1 | 2 | 3 | 4;
  readonly layers: {
    readonly chronik: ChronikSceneSnapshot | null;
    readonly earthquakes: EarthquakeSceneSnapshot | null;
    readonly metric: SpatialMetricSnapshot | null;
  };
}
```

`ChronikSceneSnapshot.spatialApplication` ist keine neu benannte Teilmenge: Es ist
die vollständig decodierte `SpatialApplicationV1` derselben Response-Generation aus
Spatial `07 §14.2`, einschließlich `global`, `intersects` und aller vier Exclusion-
Counter. Der Frame behauptet deshalb keinen auf dem Wire nicht vorhandenen
`candidateCount`. `EarthquakeSceneSnapshot.application` importiert dagegen das
`StrictPointLayerApplication<T>` aus Spatial `06 §13`; nur diese
Containment-Quelle besitzt `excludedBoundaryUncertainCount`. Es gibt keine
vereinheitlichende Accounting-Struktur, die Felder zwischen beiden Quellen verliert
oder erfindet.

Alle ISO-Zeitstrings, Koordinaten, Counts, Magnitude und Depth werden vor dem Frame
validiert und gefroren. `null` bedeutet „für diesen Frame nicht aktiviert“, nie
„verwende alte Daten“.

Ein interner reiner `SceneCompiler` übersetzt den Frame in einen immutable
`ScenePlan`. Der Cesium-Adapter übersetzt den Plan in GPU-Ressourcen. Tests verwenden
einen Recording-Adapter; der Produktionsadapter ist Cesium. Damit ist die
Presenter-Seam real und nicht hypothetisch.

### 7.4 Abhängigkeiten

- Scope, Zeit, Lens, Motion und Performance sind vorhandene In-process-Stores. Ein
  `WorldviewSceneFrameAssembler` ist deren einziger Frame-Caller; es gibt keine
  neuen flachen `WorldviewTimePort`-/`WorldviewLensPort`-Pass-throughs. Assembler,
  `ScenePlan` und Recording-Adapter sind private Implementation-Seams des Cinematic-
  Modules, keine zusätzlich gemeinsam verwendeten Registry-Verträge.
- Backend-/CHRONIK-Reads sind remote but owned und werden über bestehende
  transportfreie Ports angebunden. Nur die neue Metrikabfrage verwendet den in
  Spatial `11 §19` besessenen `SpatialMetricPort` mit HTTP- und In-memory-Adapter.
- Cesium/Ion ist eine externe Renderabhängigkeit hinter dem Scene-Adapter.
- Der Presenter führt keine eigenen ungeprüften Remote-Downloads aus.

### 7.5 React-Integration

React komponiert Runtime, Frame-Assembler und HUD/Legende. `WorldviewPage` übergibt
nur die vorhandenen Stores an einen Composition-Root; es baut keine Frames und
erhält keine neue Layer-Kaskade. Kein Animationsframe erzeugt React-State.
Per-frame-Mutationen bleiben innerhalb der Runtime. Die Motion-Einstellung und
`matchMedia`-Änderungen laufen über den live `WorldviewMotionStore` aus Spatial `11`.

---

## 8. Cesium-Renderarchitektur

### 8.1 Scene-Root und Gruppen

Die `ViewerSpatialCesiumRuntime` besitzt genau eine WorldView-Scene-Root. Darunter
liegen maximal folgende logische Gruppen:

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
| metrische Extrusion nach eigenem Promotion-Gate | `Primitive` + `PolygonGeometry`/`WallGeometry` |
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

### 8.4 Flache Selection und metrische Extrusion

Selection bleibt eine flache Ground-Surface plus Outline/Basisring. Weder Geometrie-
höhe noch Styleparameter hängen von Cameraextent oder Zielgröße ab. Damit bleibt sie
visuell von einer quantitativen Säule unterscheidbar und erfordert bei Camera-Moves
keinen Geometrie-Neubau.

Metrische Extrusion lebt nach eigenem Promotion-Gate in einer separaten Gruppe. Sie
verwendet ausschließlich Samples des `SpatialMetricPort` und die Regeln aus Spatial
`11 §19`. `extrudedHeight` wird einmal pro Metric-Revision auf Endhöhe gebaut und
niemals pro Frame oder Camera-Move animiert. Reveal darf nur ein unterstütztes
Color-Alpha-Attribut nach `ready` über `getGeometryInstanceAttributes` ändern. Dieser
Zugriff wird nicht an `releaseGeometryInstances: false` gekoppelt; CPU-Geometrie
bleibt nur für einen separat belegten Consumer erhalten. Ist die Attributmutation in
Cesium 1.142 nicht im Browser-Harness belegt, setzt die Primitive
`releaseGeometryInstances: true` und erscheint statisch. Vor Höhenfreigabe muss ein Base-Height-Record für Terrain und
`verticalExaggeration` sowie das Chunk-/Build-Budget bestanden sein. Ohne diesen
Record bleibt dieselbe Metrik als flache Color-/Hatch-Fläche sichtbar. Fehlende,
stale oder inkompatible Samples erzeugen keine variable Darstellung.

### 8.5 Visual Style

Die Hlíðskjalf-Palette bleibt eigenständig:

- `steel` für Atmosphäre und globalen Kontext;
- `stone`/`bone` für Kartographie und neutrale Labels;
- `amber` für explizite Analystenaktion und Selection;
- `sentinel`/`rust` für Threat/Severity;
- `sage` für Umwelt- und Observation-Signale.

Farben werden aus CSS-Tokens aufgelöst. Hex-Fallbacks sind ausschließlich für SSR/
jsdom zulässig und müssen in Tests bytegleich zum jeweiligen kanonischen Token
gepinnt sein; sie sind keine zweite Farbwahrheit. Der externe Cyan/Green-Look wird
nicht kopiert.

Auf World-/Country-Höhe wird Photoreal Content über `show` verborgen, damit
Kartographie und Datenmarks die visuelle Hierarchie besitzen. V1 kombiniert keine
`Cesium3DTileStyle` mit dem bestehenden `customShader` und ersetzt diesen nicht. Im
Admin-1-Scope darf Photoreal/Terrain nach dem Reveal wieder sichtbar werden. Neue
Starfield-/Basemap-Assets benötigen Source Lock, Lizenznachweis und Same-origin-
Auslieferung.

### 8.6 Post-Processing

Bloom wird mild und global eingesetzt; selektiver Glow entsteht primär durch
geschichtete Geometrie und emissive Materialien. So hängt die Lesbarkeit nicht von
einem fragilen Screen-Space-Maskenpfad ab.

Der von `GlobeViewer` über die gesamte Viewer-Lebensdauer besessene
`WorldviewPostProcessController` aus Spatial `06 §12.1` existiert auch in der
Flag-off-Legacy-Zeile und besitzt ein einziges `PostProcessStageComposite` an
stabiler Collection-Position. Cinematic, CRT, Night Vision und FLIR registrieren
allowlistete Slots; der Controller baut deren interne Reihenfolge deterministisch
neu. `shaderUtils.ts` darf keine WorldView-Stage oder Bloom-Property mehr direkt
mutieren. Im Cinematic-Mode wird Bloom über den aktiven Scene-State-Lease
restaurierbar vermittelt. Kein Shadertext stammt aus Daten, Konfiguration oder LLM-
Ausgabe.

### 8.7 Gemeinsamer Animation Clock

Genau ein `scene.preRender`-Listener steuert alle cineastischen Uniforms und
registrierten animierten Marks. Cinematic darf erst aktiviert werden, nachdem die
Schleifen aus `EventLayer`, `FIRMSLayer` und `EarthquakeLayer` entweder an diesem
Clock registriert oder im jeweiligen Motion-Modus vollständig deaktiviert sind.
Danach besitzen diese Layer keinen eigenen `requestAnimationFrame`-Loop mehr. Das
ist ein verpflichtendes Verhaltens-/Disposal-Gate, keine spätere Optimierung.

Der eine `preRender`-Listener bleibt als Runtime-Frame-Monitor attached. Sein
Animation-Clock mutiert nur, wenn mindestens ein Animationsclient aktiv ist.
`reduced` deaktiviert Stagecraft-Interpolation; `static` registriert keine
Animationsclients. Im statischen Fall misst derselbe Listener nur, mutiert keine
visuellen Eigenschaften und fordert keinen zusätzlichen Render an.
Stagecraft ist standardmäßig zeitlich begrenzt. Dauerbewegung ist nur für reale
Live-Daten oder in `full` explizit erlaubte Ambient-Motion zulässig und pausierbar.

---

## 9. Datenlinsen und regionale Visualisierung

### 9.1 Geschlossene Lens-Registry und Aktivierung

| Linse | Primäre Frage | Initialer Status | Zulässige initiale Marks |
|---|---|---|---|
| `situation` | Was geschieht im ausgewählten Raum und Zeitfenster? | aktivierbar | scope-accounted CHRONIK-Events |
| `environmental` | Welche Naturereignisse liegen im Scope? | aktivierbar | scope-accounted Earthquakes |
| `thermal` | Wo liegen thermische Aktivitäten? | blockiert | keine, bis FIRMS-Promotion |
| `mobility` | Welche Bewegungen schneiden den Scope? | blockiert | keine, bis Track-Intersection-Promotion |
| `infrastructure` | Welche Infrastruktur liegt im oder schneidet den Scope? | blockiert | keine, bis Facility-/Line-Promotion |

`situation` ist die Default-Linse. „Aktivierbar“ bedeutet weiterhin: nur bei einer
passenden produktiven Capability-Zeile und einem Snapshot mit identischer Scope-
Revision. FIRMS bleibt außerhalb `world` verborgen, bis Generation, Accounting,
24-h-Containment und der produktive Cap von 5.000 in einem eigenen Promotion-Record
belegt sind. Freie String-Linsen und ein UI-Toggle für blockierte Linsen sind
unzulässig.

### 9.2 Erste Kandidatenmetrik und Stop-Gate

`chronik.events.count` ist die erste Kandidatenmetrik, aber noch nicht verbindlich
aktivierbar. Der aktuelle Stand besitzt weder einen Per-Child-Aggregationsendpoint
noch einen `SpatialMetricPort`-Produktionsadapter; die Plan-06B-Evidenz weist für
histogrammtragende Incidents `0/11.793` scope-keyed Locations aus. Der erste
erreichbare Cinematic-Slice hängt deshalb nicht von dieser Metrik ab.

Die spätere Definition besitzt genau folgende fachliche Semantik; allein die beiden
gekennzeichneten Kalibrierwerte werden im Promotion-Record ergänzt:

```text
metricId:      chronik.events.count
label:         Ereignisse
unit:          events
aggregation:   count
scale:         log
domain:        aus Metric-Promotion-Record
heightMeters:  null bis separates Extrusions-Gate
timeBasis:     window
missingValue:  hatched
```

Flächenintensität und eine später separat freigegebene Höhe kodieren denselben Count.
Severity bleibt eine getrennte Punkt-/Glyph-Dimension. Tooltip und Legende zeigen
Count, Zeitfenster, Scale, located/unlocated, Completeness und Präzision. Die
Transformation lautet nach Kalibrierung
`log1p(count) / log1p(definition.domain[1])`, geclampt auf `[0, 1]`. Ein echter Count
`0` ist gültig; `null` ist Missing Data und wird ausschließlich per Hatch dargestellt.
Domain und optionaler Höhenbereich werden aus einer eingefrorenen repräsentativen
Verteilung plus Occlusion-/Interpretierbarkeitsmessung versioniert; sie werden weder
hier erfunden noch pro sichtbarem Sample neu berechnet.

Ein approximativer oder partieller Sample darf sichtbar sein, wenn Methode und
Coverage unübersehbar beschriftet sind. Er darf nicht als „exact“ erscheinen.

### 9.3 Country-Level-Aggregation

Country-Samples sind nach dem vollständigen Satz direkter Child-`scopeKey`s
adressiert. Vor einem Metrik-Slice muss ein `Metric Transport Promotion Record` genau
eine Transportform wählen und mit Produktionsconsumer-Evidenz attestieren. Zulässig
sind:

1. serverseitige Aggregation über materialisierte kanonische Admin-1-Keys; oder
2. ein zentraler Point-in-Child-Containment-Adapter über reviewte fixe Geometrie mit
   expliziter Präzision und Ausschlusszählung.

Eine BBox-Abfrage pro Child ist ausdrücklich verboten, weil überlappende BBoxes
doppelt zählen. Der semantische Pfad benötigt die bestehenden Plan-06B-Gates je
Lane/Kind/Derivationsrevision, inklusive Incident-Coverage, reconciliertem Accounting
und indexgestütztem Plan. Der Containment-Pfad benötigt georeferenzierte Records,
das fixe reviewte Child-Pack und zählt `boundary-uncertain`, unlocated und conflicts
separat. Beide Pfade erfüllen den `SpatialMetricSnapshot`-Vertrag aus Spatial `11`.
Ohne bestandenen Record bleibt `chronik.events.count` im UI und in Hero-Gates aus.

### 9.4 Admin-1-Lokalaggregation ohne Admin-2

Im Admin-1-Scope dürfen georeferenzierte Records innerhalb des aktiven festen
Containments in lokale Zellen aggregiert werden. Die Zellen sind reine
Visualisierung, keine neuen Scopes.

- Zellgröße, Ursprung und das in V1 geschlossene Equal-Area-CRS `EPSG:6933` stammen
  aus der versionierten `SpatialMetricDefinition.binning`; Ursprung und Zellmaß sind
  projizierte Meterwerte und bleiben über Zoom/Camera-LOD konstant.
- Camera-LOD darf nur Marks/Labels cullen, niemals Zellgrenzen oder Zellwerte ändern;
  Legende und Tooltip zeigen das feste Zellmaß.
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
- Deutschland bleibt bis zum nachfolgenden Promotion-Gate ein Country-Leaf.
- Andere Countries ohne reviewten Admin-1-Katalog bleiben Blätter.
- Admin-2 bleibt deaktiviert.

### 10.2 Deutschland

Der aktuelle Source Lock enthält keine DEU-Admin-1-Quelle. Vor Planung oder
Aktivierung müssen ein konkreter immutable Source-Release, Download-URL, Lizenz,
SHA-256, Attribution und Representation-Entscheidung reviewt und in den Source Lock
aufgenommen werden. Der kanonische Crosswalk muss alle 16 ISO-3166-2-Keys eindeutig
abdecken und MultiPolygon-/Enklavenfälle wie Bremen sowie Berlin/Brandenburg explizit
validieren. Danach gelten Double-build, LOD-, Wire-, Heap-, Ring-, Vertex- und
Containment-Feasibility-Gates unverändert.

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
- Das Country Situation Board rendert jedes direkte Child zusätzlich als
  fokussierbaren DOM-Button. Tab/Enter/Space erreichen denselben kanonischen
  `enter(childKey)`-Command wie der Globus-Pick; dies gilt auch ohne aktive Metrik.
- Hover verändert nur temporäre Präsentation und Prefetch, niemals Scope oder Daten.
- Jede Linse besitzt eine textuelle Überschrift, Legende und zugängliche Beschreibung.
- Farbe ist niemals der einzige Informationsträger; Form, Label oder Muster ergänzen
  kategoriale und Missing-Value-Zustände.
- Eine dauerhaft gemountete Live-Region meldet committed Scope, aktive Linse,
  Presentation-Problem und Ladeabschluss, aber keine per-frame Änderungen und
  höchstens zwei Meldungen pro Sekunde.
- Die sichtbare Motion-Einstellung verwendet exakt den `WorldviewMotionStore` aus
  Spatial `11`: `full` erlaubt budgetierte Choreografie, `reduced` setzt Camera- und
  Reveal-Dauer auf `0` und entfernt Ambient-Interpolation, `static` besitzt keinen
  Animationsclient. `prefers-reduced-motion` initialisiert `reduced`; nur eine
  explizite Nutzeraktion darf auf `full` hochstufen.
- Keine Vollbildblitze. Pulse überschreiten 2 Hz nicht und bleiben flächenmäßig
  begrenzt.
- Kameraanimation ist jederzeit durch Pointer-, Wheel- und Keyboard-Kameraeingabe
  über `camera.cancelFlight()` abbrechbar. Da dieser Input-Pfad heute fehlt, ist sein
  RED→GREEN-Nachweis eine Vorbedingung des ersten Cinematic-Slice. Fokus wird nach
  Child-Click oder Reveal nicht unkontrolliert versetzt.
- Die DOM-Child-Liste ist die Alternative für Navigation; bei metrischen Flächen
  ergänzt sie Wert, Einheit, Zeit, Präzision und Coverage.

---

## 12. Performance, Quality und Lifecycle

### 12.1 Quality-Tiers

Der `PerformanceGuard` wird vor Cinematic-Aktivierung auf den einen Runtime-Frame-
Monitor migriert, um echte Frame-Time-Verteilung und Hysterese erweitert und liefert
dann die Qualitätsstufe; sein heutiger eigener rAF-Loop entfällt:

| Tier | Verhalten |
|---:|---|
| 0 | volle Choreografie und bestehende volle Animationen |
| 1 | verkürzte Trails, produktiv 10 statt 30 Positionen |
| 2 | keine Pulse; statische Ringe |
| 3 | keine Orbit-Arcs, Trails oder Ambient-Motion |
| 4 | statische Punkte und semantisch gleichwertige Szene |

Degradation verändert nie Scope, Query, Count, Coverage oder Pickbarkeit. Recovery
erhöht Qualität stufenweise und baut keine stabile Pick-Surface neu.

### 12.2 Budgets

- Default-on-Gate auf der reviewten Desktop-Workstation: Median mindestens 55 FPS
  **und** p95 Frame-Time höchstens 25 ms über eine deterministische 60-Sekunden-
  Tier-0-Szene. Median 48 FPS bei p95 20 ms ist ein Gate-Fehler. Ein begrenzter
  Frame-Delta-Ring misst beide Werte; der heutige reine Callback-Zähler reicht nicht
  als Evidenz.
- Degradation startet vor dem Hard Gate: rolling p95 über 25 ms für zwei Sekunden,
  rolling Median unter 55 FPS für fünf Sekunden oder weniger als 45 FPS für eine
  Sekunde senkt genau einen Tier. Erst wenn nach fünf Sekunden Settle auf Tier 4
  weiterhin mehr als zwei Sekunden unter 30 FPS auftreten, schlägt das Hard Gate
  fehl. Die Laufzeit-Degradation macht einen fehlgeschlagenen Tier-0-Release-
  Benchmark nicht nachträglich grün.
- Der reproduzierbare Browser-Benchmark muss diese initialen Schwellen vor
  Default-on bestätigen; ein verfehlter Wert führt zu einem reviewten Spec-Delta
  oder kleinerem visuellen Budget, nicht zu Testtoleranz-Erhöhung.
- Kein eigener Main-Thread-Task über 50 ms; Boundary-/Mark-Konvertierung bleibt
  gechunkt mit Ziel unter 8 ms pro Chunk.
- Cinematic erhöht keinen produktiven Layer-Cap. Es respektiert insbesondere FIRMS
  400, Earthquakes 250 sowie die getrennten Vessel-Load-/Render-Caps 3.000/200 und
  verwendet für jeden weiteren Layer dessen registrierten bestehenden Cap. Ein
  höherer Cap benötigt einen eigenen Benchmark- und Memory-Record.
- Wenige große Billboard-/Polyline-Collections werden nach Update-Frequenz getrennt.
- Maximal eine aktive und eine staging Scene-Generation.
- Ein Scope-/Lens-Wechsel abortet alle veralteten Builds und Data-Frames und ruft für
  einen aktiven Cesium-Flug `camera.cancelFlight()` auf.

### 12.3 Lifecycle-Gates

- 100 Zyklen `world ↔ country ↔ admin1` ohne monotones Wachstum von Primitives,
  Collections, Post-Process-Stages, Clock-Callbacks, Event-Listenern oder Asset-Leases;
- 100 Wechsel zwischen den jeweils aktivierten Linsen innerhalb desselben Scope ohne
  Pick-Surface-Rebuild; blockierte Lens-IDs bleiben unavailable und bauen keine Szene;
- keine zerstörte Primitive, Stage oder Collection bleibt referenziert;
- kein stale Frame erscheint unter neuer Scope-/Lens-Beschriftung;
- Long-session-Soak mit Live-Daten, Timeline-Seek, Kamerainteraktion und
  Degradation/Recovery;
- Runtime-Rollback auf den operationalen Presenter ohne Daten- oder Catalog-Rollback;
- Scene-State, einzige Root und Stage-Reihenfolge entsprechen nach Dispose exakt der
  vor Attach erfassten Baseline aus Spatial `06 §12.1`.

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

Der Vertrag ist geschlossen und enthält keine Rohrecords:

```ts
interface CinematicWorldviewDiagnostics {
  readonly identity: {
    readonly scopeKey: ScopeKey | null;
    readonly catalogRevision: string | null;
    readonly stateRevision: number | null;
    readonly lens: WorldviewLensId | null;
  };
  readonly generations: {
    readonly active: number | null;
    readonly staging: number | null;
  };
  readonly resources: {
    readonly primitives: number;
    readonly collections: number;
    readonly labels: number;
    readonly stages: number;
    readonly clockCallbacks: number;
    readonly assetLeases: number;
    readonly primitiveHighWater: number;
    readonly collectionHighWater: number;
    readonly leaseHighWater: number;
  };
  readonly performance: {
    readonly fpsMedian: number | null;
    readonly frameTimeP95Ms: number | null;
    readonly qualityTier: 0 | 1 | 2 | 3 | 4;
    readonly degradationCount: number;
    readonly culledMarkCount: number;
  };
  readonly transitions: {
    readonly started: number;
    readonly completed: number;
    readonly aborted: number;
    readonly discarded: number;
  };
  readonly frames: {
    readonly accepted: number;
    readonly identityRejected: number;
  };
  readonly marks: {
    readonly chronik: number;
    readonly earthquakes: number;
    readonly metricSurfaces: number;
  };
  readonly metric: {
    readonly status: "inactive" | "ready" | "partial" | "unavailable";
    readonly metricId: SpatialMetricId | null;
  };
  readonly sceneStateLease: {
    readonly active: boolean;
    readonly restoreCount: number;
    readonly lastRestoreEqual: boolean | null;
  };
  readonly errors: {
    readonly emitted: number;
    readonly suppressed: number;
  };
}
```

Produktionslogs sind aggregiert und bounded. Wiederholte identische Fehler werden wie
bei den Legacy-Diagnostics unterdrückt gezählt statt unbegrenzt ausgegeben.

---

## 15. Rollout, Kompatibilität und Plan 05D

### 15.1 Vorgelagerte Shared-Refactor-Stufe

Die in Spatial `14 §26.1` besessene Stufe S landet und canaryt vor der ersten
Cinematic-Zeile die gemeinsam genutzten Änderungen: `PresentationOutcome`-Parität,
Viewer-langlebigen Post-Process-Controller, gemeinsamen Layer-/Performance-Clock und
Camera-Flight-Cancel. Dieses separat rückrollbare Artefakt enthält weder
`CinematicWorldviewModule` noch eine neue Scene-Strategie oder visuelle Claims. Es
muss Flag-off-Legacy und Flag-on-Operational mit eigenem TDD-, Canary-, Soak- und
Artefakt-Rollback-Record belegen. Ein kombinierter späterer Cinematic-Testlauf
ersetzt diesen Record nicht.

### 15.2 Presentation-Mode

Der cineastische Presenter verwendet den in Spatial `14 §26.1` besessenen Modus:

```text
worldview_presentation_mode = operational | cinematic
```

Er ist nur in einem Spatial-enabled Artefakt gültig, stammt aus validierter
Client-Konfiguration und nie aus einem Query-Parameter. Initial bleibt `operational`
Default; Canary und Review nutzen `cinematic`. Die geschlossene Flag-/Mode-Matrix
und die sichtbare Diagnose für eine ungültige Kombination werden hier nicht neu
definiert.

Ein Mode-Wechsel verändert weder URL-Scope noch Katalog- oder Datenrevision. Beide
Presenter verwenden denselben `SpatialScopeModule`, Catalog und Layer-Snapshots.

### 15.3 Zwei Rollback-Domänen

Shared-Refactor-Rollback deployt das unmittelbar vor Stufe S gebaute Frontend-
Artefakt. Der Presentation-Mode behauptet nicht, Port-, Clock-, Controller- oder
Camera-Input-Migrationen zurückzunehmen.

Cinematic-Rollback arbeitet ausschließlich auf der bestandenen Post-S-Baseline:

- Cinematic-Strategie, Controller-Slot, Clock-Clients und Listener deterministisch
  disposen;
- alle vom `SceneStateLease` besessenen Properties auf die aktuelle Baseline
  restaurieren und Wertgleichheit diagnostizieren;
- anschließend die operationale Strategie derselben einzigen Runtime attachen;
- committed Scope, Zeit, Selection und Daten unverändert bewahren.

Für keine der beiden Domänen ist ein Schema-, Datenbank-, Catalog- oder Ingestion-
Rollback erforderlich. Die jeweiligen Frontend-Artefakte und Records bleiben jedoch
getrennt; der Runtime-Mode ist kein Ersatz für Artefakt-Rollback.

### 15.4 Plan 05D

Diese Spec entsperrt Plan 05D nicht. Legacy-Renderer, `CountryTarget`,
`useCountryHitTest`, `_topoIndex` und `VITE_SPATIAL_SCOPE_ENABLED` bleiben bis zu den
bereits definierten Phase-D-Gates erhalten. Der cineastische Presenter muss zunächst
gegen operationalen Presenter und Artefakt-Rollback beweisen, dass die neue
Präsentationsschicht langzeittauglich ist.

---

## 16. Abnahme- und Review-Evidenz

### 16.1 Erreichbare und promotion-gebundene Hero-Frames

Vor Migration weiterer Layer werden genau drei heute erreichbare Zielzustände
festgelegt und visuell abgenommen:

1. `world` — idle establishing scene mit ausschließlich global erlaubten Layern;
2. `country:UKR` — target acquisition und flaches Country Situation Board mit allen
   27 Children, ohne Metrikbehauptung;
3. `admin1:iso3166-2:UA-14` — regional tactical scene mit scope-accounted CHRONIK
   und Earthquakes; jede Approximation/Coverage ist sichtbar.

Die folgenden Frames sind keine Abnahme des ersten Slice, sondern getrennte
Promotion-Gates:

4. `country:UKR` mit `chronik.events.count` erst nach Metric Transport Promotion;
5. `admin1:iso3166-2:UA-14` mit FIRMS erst nach FIRMS-Capability-Promotion;
6. `country:DEU` mit allen 16 Bundesländern erst nach DEU-Source-/Catalog-Promotion.

Jeder Frame verwendet fixe Viewportgröße, Camera, Uhrzeit, Datenfixture, Lens,
Quality und Motion-Policy. Die Evidenz umfasst Screenshot, kurze Transition-Aufnahme,
DOM-/Accessibility-Snapshot und Diagnostics.

### 16.2 Testinfrastruktur-Gate

Der aktuelle Frontend-Stack besitzt Vitest/jsdom, aber keinen echten Browser-/WebGL-
oder Image-Snapshot-Harness. Vor dem ersten Cesium-/Visual-RED wird deshalb
Playwright als reine Dev-/Testabhängigkeit separat reviewt und ein reproduzierbarer
Chromium-Harness mit fixer Version, Viewport, Device Scale, Uhr, lokaler Datenfixture
und kontrolliertem WebGL-Modus eingerichtet. Hero-Baselines verwenden keine
variablen Remote-Tiles. Bis dieser Harness selbst als service-lokales Gate grün und
flake-frei ist, gelten manuelle Screenshots nicht als automatisierte Release-Evidenz.

Die Freigabereihenfolge ist nicht komprimierbar: erst grüner Browser-Harness, dann
Shared-Refactor-Stufe S mit beiden operationalen Canaries und Artefakt-Rollback,
danach Cinematic-TDD und Cinematic-Canary. Eine gemeinsame Endsuite ohne die beiden
getrennten Records beweist die Rollback-Isolation nicht.

Danach gelten:

- reine SceneCompiler-Tests für alle aktivierten Linsen sowie Missing-/Stale-/
  Coverage-Zustände;
- Recording-Adapter-Tests über das externe Modul-Interface;
- echte Browser-Cesium-Tests für Primitive-Typen, Pick-ID, Staging, feste
  Post-Process-Reihenfolge, `camera.cancelFlight`, Scene-State-Restore und Disposal;
- Visual-Regression-Screenshots für die erreichbaren Hero-Frames in full, reduced
  und static; Promotion-Frames kommen erst mit ihrer Capability hinzu;
- Accessibility-Tests für Motion, Live-Region, Legende, Keyboard und Tabellenersatz;
- Point-, Track- und Metric-Truthfulness-Tests pro aktivierter Capability;
- Katalog-Double-build und Feasibility als Gate der Deutschland-Promotion;
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

Abgelehnt. Variable Höhe und Linien suggerieren Daten. Selection bleibt flach;
alles Variable benötigt eine überprüfbare Kodierung oder echte gerichtete Relation.

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
- [Spatial 07 — CHRONIK-Query-Vertrag](2026-07-31-spatial-scope-drilldown/07-chronik-query-contract.md)
- [Spatial 11 — UX und 3D-Metriken](2026-07-31-spatial-scope-drilldown/11-ux-and-3d-metrics.md)
- [Spatial 12 — Fehler, Security und Observability](2026-07-31-spatial-scope-drilldown/12-errors-security-and-observability.md)
- [Spatial 14 — Rollout und Abnahme](2026-07-31-spatial-scope-drilldown/14-rollout-and-acceptance.md)
- [Plan 06B — CHRONIK Exact Scope](../plans/2026-08-01-spatial-scope/06b-chronik-exact-scope.md)
- [Worldview Layer-Design — Hlíðskjalf Noir](2026-04-30-worldview-layer-design.md)
- [Globe Layers Evolution](2026-04-05-globe-layers-evolution-design.md)
- `services/frontend/src/pages/WorldviewPage.tsx`
- `services/frontend/src/components/globe/GlobeViewer.tsx`
- `services/frontend/src/components/globe/PerformanceGuard.tsx`
- `services/frontend/src/spatial/cesium/CesiumSpatialScopeAdapter.ts`
- `services/frontend/src/spatial/cesium/buildScopePrimitives.ts`
- `services/frontend/src/spatial/layerScopePolicy.ts`
- `services/frontend/src/spatial/pointLayerSpatialAdapter.ts`
- `services/frontend/src/types/index.ts`

### Extern, nur technische Primärdokumentation

- [CesiumJS PolygonGeometry](https://cesium.com/learn/cesiumjs/ref-doc/PolygonGeometry.html)
- [CesiumJS Primitive](https://cesium.com/learn/cesiumjs/ref-doc/Primitive.html)
- [CesiumJS MaterialAppearance](https://cesium.com/learn/cesiumjs/ref-doc/MaterialAppearance.html)
- [CesiumJS PostProcessStage](https://cesium.com/learn/cesiumjs/ref-doc/PostProcessStage.html)
- [CesiumJS Camera](https://cesium.com/learn/cesiumjs/ref-doc/Camera.html)
- [CesiumJS BillboardCollection](https://cesium.com/learn/cesiumjs/ref-doc/BillboardCollection.html)
- [CesiumJS ParticleSystem](https://cesium.com/learn/cesiumjs/ref-doc/ParticleSystem.html)
- [Visual inspiration only: three-scope-map-skill](https://github.com/songsummer920-dazzle/three-scope-map-skill)

---

## 20. Disposition des adversarialen Erst-Reviews

Das Erst-Review endete `PASS WITH REQUIRED FIXES`. Dieser Record beschreibt nur,
wo die Findings geschlossen wurden; er erzeugt keine zweite normative Heimat. Der
Status bleibt bis zu einem unabhängigen Abschluss-Re-Review blockiert.

| Finding | Disposition |
|---|---|
| `CRIT-001` | `01 §4.2`, `06 §12.1`, `11 §18/§19`, `14 §26/§28` und Index-Registry sind die normativen Eigentümer; §2 ist nur Navigationskarte. |
| `CRIT-002` | FIRMS aus dem ersten Hero-Satz entfernt und als eigenes Capability-Promotion-Gate geführt. |
| `CRIT-003` | `chronik.events.count` als aktuell blockierte Kandidatenmetrik mit Transport-/Coverage-/Accounting-Record und BBox-per-Child-Verbot geführt. |
| `CRIT-004` | Ein `ViewerSpatialCesiumRuntime`, exklusiver `SceneStateLease`, vollständige Property-Liste und Before/After-Restore-Gate definiert. |
| `WARN-001` | Bestehende drei rAF-Layer und der PerformanceGuard müssen vor Aktivierung auf einen Runtime-Clock/Motion-Store migrieren; `static` besitzt keine Animationsclients. |
| `WARN-002` | Ein Post-Process-Owner und ein Composite mit fester Slot-Reihenfolge ersetzen direkte Stage-Mutation/`removeAll`. |
| `WARN-003` | Selection ist flach; Metric-Höhe wird nicht animiert und bleibt bis Base-Height-/Build-Promotion flache Color-/Hatch-Fläche. |
| `WARN-004` | 10k-Cap entfernt, produktive Layer-Caps gepinnt, Frame-p95-Instrumentierung/Hysterese ergänzt und Flight-Maximum auf 3.000 ms korrigiert. |
| `WARN-005` | Zellraster ist versioniert und cameraunabhängig; Camera-LOD darf nur cullen. |
| `WARN-006` | `present` liefert wieder `Promise<PresentationOutcome>`; die Code-Drift ist explizite RED→GREEN-Vorbedingung. |
| `WARN-007` | Index-Registry erweitert; Frame, Diagnostics, Motion und Metric-Verträge sind geschlossen und besitzen je eine Heimat. |
| `WARN-008` | Deutschland aus dem initialen Umfang entfernt und an konkretes Source-Lock-/16-Child-/Feasibility-Promotion-Gate gebunden. |
| `WARN-009` | DOM-Child-Buttons definieren die vollständige Tastaturäquivalenz auch ohne Metrik. |
| `WARN-010` | Playwright-/WebGL-Harness ist explizites Testinfrastruktur-Gate; `camera.cancelFlight` wird nicht als vorhanden behauptet. |
| `INFO-001/002` | `rust` ersetzt das nicht existente `ember`; SSR/jsdom-Fallbacks müssen token-identisch testgepinnt sein. |
| `INFO-003/004` | Hero-Scope ist `UA-14`; Domain/Höhe werden erst aus Verteilung und Occlusion-Evidenz kalibriert. |
| `INFO-005/006/007` | Tier 3 folgt dem Codevertrag; Flag-/Mode-Matrix und exakte Full/Reduced/Static-Semantik liegen in ihren normativen Heimaten. |

---

## 21. Disposition des Abschluss-Re-Reviews, Runde 2

Auch Runde 2 endete `PASS WITH REQUIRED FIXES`; ihr Autor war zugleich Reviewer der
ersten Runde. Dieser Record verlinkt nur die Korrekturen in ihren normativen Heimaten
und ist kein unabhängiges Votum. Die Spec bleibt bis zum PASS eines unbelasteten
Reviewers blockiert.

| Finding | Disposition |
|---|---|
| `CRIT-005` | `ChronikSceneSnapshot` importiert die vollständige `SpatialApplicationV1` aus `07 §14.2`; alle vier Wire-Exclusion-Counter, `global` und `intersects` bleiben erhalten, `candidateCount` entfällt. Point-Containment importiert separat `StrictPointLayerApplication<T>` aus `06 §13`. |
| `WARN-011` | `06 §12.1` schließt SkyBox, Sky-/Ground-Atmosphere, Dynamic Lighting und Light-/Night-Fade ein; Photoreal wird in V1 nur über `show` verborgen, der bestehende `customShader` bleibt unberührt, Restore wertgleich. |
| `WARN-012` | Der einzige Post-Process-Controller gehört dem `GlobeViewer` über dessen gesamte Lebensdauer und existiert damit auch in der Flag-off-Legacy-Zeile. Runtime-Strategien besitzen nur Slots. |
| `WARN-013` | `14 §26` besitzt die separat releasbare Shared-Refactor-Stufe S mit Operational-/Legacy-Canaries und eigenem Artefakt-Rollback; Cinematic-Runtime-Rollback beginnt erst auf dieser bestandenen Baseline. |
| `INFO-008` | Fixed-Grid-Binning besitzt das geschlossene Equal-Area-CRS `EPSG:6933` sowie Ursprung und Zellmaß in projizierten Metern. |
| `INFO-009` | Per-Instance-Attributzugriff hängt an `ready`, nicht an `releaseGeometryInstances: false`; CPU-Geometrie bleibt nur für einen belegten Consumer erhalten. |
| `INFO-010` | Diagnostics und Metric-Port importieren `SpatialMetricId` aus der geschlossenen Registry in `11 §19`. |
| `INFO-011` | Median ≥ 55 FPS ist explizites Tier-0-Default-on-Gate und Laufzeit-Degradationsschwelle; Median 48/p95 20 ist ausdrücklich kein Pass. |
| `INFO-012` | Die Index-Tabelle wurde vollständig gegen `wc -w` regeneriert. Die älteren Driftfälle `03`/`04` wurden ohne Änderung ihrer Codeblöcke, Überschriften oder Verträge redaktionell unter 2.000 Wörter verdichtet; Schritt 6 verlangt künftig Tabellenupdate im selben Commit. |
