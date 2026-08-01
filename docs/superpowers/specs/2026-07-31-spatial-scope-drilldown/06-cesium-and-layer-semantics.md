# Teil-Spec 06 — Cesium und Layer-Semantik

> **Parent:** [Spatial-Scope-Index](../2026-07-31-spatial-scope-drilldown-design.md)
>
> **Normativer Besitz:** Cesium-Primitives, Build/Swap/Disposal, Picking, Kamera,
> Prefetch, GPU-/Heap-Budgets und die räumliche Capability-Registry der Layer.
>
> **Voraussetzungen:** [03 — Frontend-Core](03-frontend-core-and-navigation.md) und
> [04 — Catalog-Verträge](04-spatial-catalog-contracts.md). UX-Policy liegt in
> [11](11-ux-and-3d-metrics.md).

---

## 12. Cesium-Adapter

### 12.1 Port und Besitz

```ts
type PresentationOutcome =
  | { readonly outcome: "ready" }
  | { readonly outcome: "unavailable"; readonly problem: ScopeProblem };

interface SpatialPresentationPort {
  present(
    input: ResolvedPresentationInput,
    stateRevision: number,
    signal: AbortSignal,
  ): Promise<PresentationOutcome>;
  dispose(): void;
}
```

Der konkrete `CesiumSpatialScopeAdapter` erhält den gemeinsamen
`BoundaryAssetStore`, besitzt exakt eine Root-`PrimitiveCollection` im Viewer und
alle darunter erzeugten Scope-Primitives. `GlobeViewer` bleibt
Renderer-Composition-Root und enthält keine Scope-State-Machine.

`ResolvedPresentationInput`, `AssetDescriptor` und `GeoExtent` sind interne,
rendererfreie Katalogtypen. Sie verlassen das Module nicht in Richtung normaler
React-Caller. `prefetch` wird vom Controller über denselben Catalog-/Asset-Cache wie
`resolve` ausgeführt; es baut beim Hover noch keine GPU-Primitives.

### 12.2 Primitive-Struktur pro Revision

Maximal drei Scope-Draw-Gruppen plus optional eine LabelCollection:

1. `GroundPrimitive` für die aktive Scope-Fläche (`allowPicking: false`).
2. Eine gebatchte `GroundPrimitive` mit einem `GeometryInstance` je drillbarem Child; Farbe sehr dezent, `allowPicking: true`, typisierte Instance-ID.
3. Eine gebatchte `GroundPolylinePrimitive` für aktive und Child-Outlines (`allowPicking: false`).
4. Optional eine `LabelCollection` mit budgetierten, kollisionsarmen Labels.

Keine Entity-API. `classificationType: BOTH` wird dort verwendet, wo Scope-Flächen Terrain und 3D Tiles klassifizieren sollen. `releaseGeometryInstances: true` wird nach erfolgreichem GPU-Upload gesetzt, sofern spätere Per-Instance-Mutation nicht benötigt wird.

Typed Pick-ID:

```ts
interface SpatialChildPickId {
  readonly odinKind: "spatial-child";
  readonly scopeKey: ScopeKey;
  readonly stateRevision: number;
}

function isSpatialChildPickId(value: unknown): value is SpatialChildPickId {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Record<string, unknown>;
  return candidate.odinKind === "spatial-child"
    && typeof candidate.scopeKey === "string"
    && typeof candidate.stateRevision === "number";
}
```

Der Cast geht ausschließlich auf `Record<string, unknown>`, niemals auf `any`.

LOD bleibt ein Presentation-Detail. Der Bundle-Validator verlangt mindestens den
`preferredLod` in `outlineLods` und bei drillbaren Scopes auch in `childrenLods`;
`childrenLods` darf bei einem Blatt leer sein. Für nicht pickbare Rendergeometrie
mappt der Adapter die vorhandenen Kamera-LOD-Stufen aus `lib/lod.ts` auf
`overview/regional/local` und wählt bei fehlender Variante die nächst gröbere
vorhandene. Ein `camera.moveEnd` kann innerhalb desselben Scope einen lokalen LOD-
Build für nicht pickbare Flächen und Outlines starten. Dabei bleibt die alte,
semantisch identische Geometrie sichtbar, bis die neue ready ist; ein eigener
`lodGeneration`-Guard verhindert stale Swaps.
`stateRevision`, URL und Queries ändern sich dabei nicht. Damit wird semantische Tiefe
auch implementatorisch nicht mit Kamerahöhe gleichgesetzt.

### 12.3 Build, Swap und Wahrheit im Übergang

Während `phase="resolving"` bleibt der alte Scope semantisch aktiv; seine Primitives bleiben korrekt sichtbar.

Nach dem semantischen Commit:

1. Der alte Scope-Container wird sofort `show=false`, damit kein altes Polygon unter dem neuen Breadcrumb sichtbar ist.
2. Asset wird geladen, validiert und in CPU-Chunks konvertiert.
3. Ein neuer `PrimitiveCollection({ destroyPrimitives: true })` wird als Staging-Container eingesetzt; seine Kinder starten mit `show=false`.
4. CesiumJS 1.142 besitzt für diese Primitives `ready`, aber kein verlässliches `readyPromise`. Der Adapter prüft `ready` in einem registrierten `scene.postRender`-Listener.
5. Wenn alle Pflicht-Primitives ready und die Generation noch aktuell sind, wird der neue Container sichtbar und der alte über die Parent-Collection entfernt.
6. `PrimitiveCollection` zerstört enthaltene Primitives standardmäßig beim Entfernen. Der Adapter ruft nicht zusätzlich blind `destroy()` auf und schützt jeden Cleanup mit `isDestroyed()`.
7. Ist die Generation veraltet, wird der Staging-Container entfernt und zerstört, ohne je sichtbar oder pickbar zu werden.
8. Fehlt Geometrie, wird der alte Container endgültig entfernt; Scope bleibt semantisch aktiv und die UI zeigt `semantic-only`.

Die lokale Cesium-1.142-Implementation startet die asynchrone Primitive-Erzeugung vor der Draw-Unterdrückung durch `show=false`. Ein Integrationstest muss dieses Staging-Verhalten beim Dependency-Upgrade absichern.

### 12.4 Chunking

JSON-Validierung und Koordinatenkonvertierung dürfen den Main Thread nicht in einem langen Block belegen. Der Builder verarbeitet maximal 8.000 Vertices oder 8 ms pro Chunk, je nachdem, was zuerst erreicht wird, und yielded über `requestAnimationFrame`. Nach jedem Yield wird Abort/Generation geprüft.

Die Cesium-Worker übernehmen Geometry-Kombination mit `asynchronous: true`; das ersetzt nicht das Chunking der vorherigen JavaScript-Dekodierung.

### 12.5 Picking-Priorität

`scene.pick` reicht bei überlagerten Daten- und Scope-Primitives nicht. Der zentrale
WorldView-Pick-Resolver verwendet pro Pointer-Event höchstens ein
`scene.drillPick(position, 16)` und priorisiert:

1. explizite UI-/Handle-Picks;
2. operative Datenobjekte wie Track, Event, Facility, Vessel oder Aircraft;
3. `spatial-child`;
4. Legacy-Country-Surface-Hit ausschließlich bei deaktiviertem Spatial-Flag;
5. blank globe.

Damit verschluckt eine transparente Child-Fläche keine operativen Punkte. `EntityClickHandler` bekommt eine typisierte `ResolvedWorldviewPick`-Union und enthält keine Layer-spezifische `any`-Kaskade.

Im Spatial-Modus stammt `SpatialChildPickId.scopeKey` aus dem schema-validierten,
Source-Lock-gebundenen Child-Pack. `country-endonyms.json._topoIndex`, Displayname
oder ein lokal zusammengesetztes `country:${iso3}` dürfen keinen Command erzeugen.
Solange das Catalog-Pack nicht pickbar ist, gibt es keinen Legacy-Identitätsfallback;
Search und Deep Link bleiben als semantische Einstiege verfügbar. Bei deaktiviertem
Flag darf der alte Hit-Test weiterhin Legacy-Selection/Spotlight bedienen, besitzt
aber keinen Zugriff auf `SpatialScopeModule.dispatch`.

Die pickbare Child-Fläche ist pro `stateRevision` fest an
`childrenLods[preferredLod]` gebunden. Der Adapter pinnt diesen Descriptor beim
semantischen Commit und behält die daraus gebaute Primitive über dessen gesamte
Presentation-Lifetime; nur ein expliziter Presentation-Retry oder der nächste Commit
darf sie ersetzen. `camera.moveEnd` und `lodGeneration` dürfen sie weder ersetzen
noch neu indexieren. Kameraabhängige LOD-Swaps betreffen nur nicht pickbare Flächen
und Outlines. Fehlt oder verletzt das Preferred-Child-Asset seinen Descriptor, ist
die Darstellung `unavailable`; eine andere Render-LOD oder Legacy-Geometrie wird
nicht zur Pick-Quelle. Damit liefert derselbe auf den Globus projizierte
kartographische Punkt innerhalb derselben Katalogrevision unabhängig von der
Kamerahöhe denselben `SpatialChildPickId`.

Liefert Cesium genau 16 Treffer, wird `spatial_pick_saturated` gezählt; der Handler
startet im selben Frame keinen unbeschränkten zweiten Pick. Die feste Priorität wird
in einem reinen Resolver getestet, während ein kleiner Cesium-Integrationstest nur
die Instance-ID-Weitergabe absichert.

### 12.6 Kamera

Kamera ist ein abgeleiteter Best-Effort-Effekt:

- Erfolgreicher User-Commit mit Boundary: `Camera.flyToBoundingSphere` über eine aus den kartesischen Boundary-Punkten berechnete Sphere; top-down `HeadingPitchRange`, Range automatisch aus Sphere.
- `prefers-reduced-motion`: identisches Ziel mit Dauer `0`.
- Browser-Hydration darf fitten; Popstate folgt derselben Regel.
- Programmatic Consumer können im internen Command-Kontext `cameraEffect: "fit" | "preserve"` erhalten; dieser Schalter wird nicht Teil der öffentlichen semantischen Identität.
- Pointer-/Wheel-/Keyboard-Kameraeingabe cancelt nur den laufenden Flug, nie den Scope.
- Fehlende Geometrie lässt die Kamera unverändert.
- Kamera- oder Tile-Fehler erzeugen `PRESENTATION_FAILED`, rollen aber Scope und Queries nicht zurück.

### 12.7 Hover-Prefetch

- nur für bereits pickbare direkte Children;
- `MOUSE_MOVE` höchstens einmal pro Animation Frame ausgewertet;
- 200 ms stabiler Dwell vor Request;
- Abbruch bei Leave oder neuem Target;
- maximal zwei parallele Prefetches;
- deaktiviert für Touch-only und `navigator.connection.saveData === true`, sofern vorhanden;
- Cache-Promotion beim Click statt erneutem Download;
- lädt Target-Metadaten sowie bevorzugte Outline-/Child-LOD, aber keine alternativen
  LODs und keine GPU-Primitives;
- niemals URL-, Scope-, Selection- oder Kamera-Mutation.

### 12.8 Cache-Budgets

- Scope-Metadaten: LRU, 256 Einträge.
- Dekodierte Geometry/Child-Packs: LRU, maximal 8 Bundles und 64 MiB geschätzter Heap.
- aktuelles Containment-Asset ist innerhalb dieses Budgets gepinnt, solange
  Punktlayer es leasen; bei Budgetüberschreitung wird der Consumer unavailable statt
  auf Render-LOD auszuweichen.
- In-flight: key aus `catalogRevision + assetId`, ref-counted.
- GPU: nur aktiver und aktuell bauender Scope-Container.
- Bei Memory Pressure werden Prefetch-Einträge zuerst verworfen; der committed Scope bleibt.

### 12.9 Performance-Akzeptanz

- gecachter Core-Commit unter 50 ms;
- kalter Scope-Metadaten-/Boundary-Wechsel p95 unter 800 ms im lokalen Deployment;
- kein eigener Main-Thread-Task über 50 ms, Ziel pro Chunk unter 16 ms;
- maximal drei Scope-Primitive-Gruppen plus Labels;
- Pick-Auflösung höchstens einmal pro Animation Frame;
- nach 100 Wechseln `world ↔ country ↔ admin1` keine monotone Zunahme der Scope-Primitive-Anzahl und kein retained Staging-Container;
- keine sichtbare veraltete Geometrie oder Daten unter neuer Scope-Beschriftung.

---

## 13. Layer-Semantik statt pauschalem „Filter alles“

Jeder Layer registriert eine räumliche Fähigkeit. Die Registry ist Code, kein LLM-Entscheid:

```ts
type SpatialRelation = "occurs-in" | "about" | "intersects" | "context";
type ScopeBehavior = "strict" | "dim-outside" | "global-context" | "unsupported";

interface LayerSpatialCapability {
  readonly layerId: string;
  readonly relation: SpatialRelation;
  readonly behavior: ScopeBehavior;
  readonly supportedKinds: readonly ScopeKind[];
  readonly precision:
    | "semantic-key"
    | "point-in-boundary"
    | "bbox-approximate"
    | "global";
}
```

Initiale Matrix:

| Layerklasse | Relation | V1-Verhalten | Bemerkung |
|---|---|---|---|
| CHRONIK Events | `occurs-in` | strict | zunächst BBox-approx., später semantische Location-Keys |
| Geo-Events/Hotspots/Earthquakes | `occurs-in` | strict oder dim-outside | clientseitiger Point-in-Boundary möglich |
| Aircraft/Vessel Tracks | `intersects` | dim-outside | Track gilt als Treffer, wenn mindestens ein Punkt im Scope liegt; nicht Punkte wegclippen |
| Satelliten | `global-context` | global | Orbit ist nicht sinnvoll einem Admin-Scope zugeordnet |
| Cables/Pipelines | `intersects` | context | nicht nach Startpunkt filtern; echte Geometry-Intersection nötig |
| Facilities | `occurs-in` | strict | Punktgeometrie, Coverage offenlegen |
| Terrain/Imagery/3D Tiles | `context` | global | Basiskarte bleibt global |
| Country/Admin-Borders | `context` | scope presentation | keine operative Datenquelle |

Die UI zeigt pro aktiviertem Layer ein kompaktes Scope-Verhalten, sobald es nicht `strict + semantic-key` ist. Ein globaler Context-Layer darf nicht wie ein exakt gefiltertes Resultat aussehen.

Alle clientseitig gefilterten Punktlayer verwenden ausschließlich den festen
Containment-Port aus
[§10.9](04-spatial-catalog-contracts.md#109-frontend-catalog-port-und-interne-resolve-form).
Kein Layer ruft `polygonContains` auf der gerade sichtbaren
Render-LOD auf. Ein Layer ohne Koordinate behält sein heutiges globales Verhalten nur,
wenn seine Registry `global-context` sagt; ein als strict deklarierter Layer schließt
den Record aus und meldet Coverage.

Ein `boundary-uncertain`-Resultat aus dem Containment-Port zählt nicht als strict
inside: strict Layer verbergen und zählen den Punkt, `dim-outside`-Layer markieren ihn
als unsicher. Der Layer meldet `excluded_boundary_uncertain_count`, damit das
50-m-Containment-Budget nicht als exakte administrative Wahrheit erscheint.

Erste Scope-Bindung ist CHRONIK. Danach folgen reine Punktlayer. Tracks, lineare Infrastruktur und Satelliten werden nicht in denselben Slice gezwungen.

---
