# Teil-Spec 11 — UX und 3D-Metriken

> **Parent:** [Spatial-Scope-Index](../2026-07-31-spatial-scope-drilldown-design.md)
>
> **Normativer Besitz:** Breadcrumb, Click-/Escape-Semantik, Selection-Lifecycle,
> Pending/Stale-Wahrheit, Reduced Motion, Attribution und spätere datengetriebene
> Extrusion.
>
> **Voraussetzungen:** [03 — Frontend-Core](03-frontend-core-and-navigation.md) und
> [06 — Cesium](06-cesium-and-layer-semantics.md).

---

## 18. UX und Interaktion

### 18.1 Breadcrumb

Beispiel:

```text
WORLD / UKRAINE / DONETSK OBLAST
```

- semantisches `<nav aria-label="Spatial scope">`;
- jeder Ancestor ist ein Button, Current hat `aria-current="location"`;
- separater Button „Eine Ebene hoch“, nicht „Browser zurück“;
- vollständige Bedienung per Tab/Enter/Space;
- Fokus bleibt nach Commit auf dem auslösenden Breadcrumb beziehungsweise wechselt nach Child-Click nicht unkontrolliert;
- pending Target und Presentation-Warning werden textuell, nicht nur farblich angezeigt.
- Styling verwendet vorhandene Hlíðskjalf-Typografie/Theme-Tokens; keine kopierten
  Hex-Farben oder HUD-Komponenten aus der externen Referenz.

### 18.2 Click-Semantik

- Country-Klick im World-Scope: Catalog-Pick-ID dispatchen, danach Country-Detail/
  Almanac mit dem committed kanonischen `scopeKey` öffnen. Displayname, M49/ISO3 aus
  `country-endonyms.json` und Click-Koordinate erzeugen keinen Scope-Key.
- Child-Klick: `enter(childKey)`.
- Klick auf operatives Entity über Child-Fläche: Entity gewinnt; kein Drilldown.
- Blank globe: darf Selection/Spotlight löschen, aber Scope nicht verändern.
- Nicht verfügbare Children besitzen keine Drill-Affordance.
- Pin-/Such-Fokus setzt weiterhin Circle-Spotlight; ein Search-Result ändert Scope nur bei einer expliziten „Gebiet öffnen“-Action.
- Jedes direkte Child ist zusätzlich in einer DOM-Liste mit kanonischem Label als
  `<button type="button">` erreichbar. Tab fokussiert, Enter/Space dispatcht denselben
  `enter(childKey)`-Command wie der Globus-Pick; Hover/Fokus synchronisieren nur die
  nicht-semantische Hervorhebung. Damit ist der Globus nie der einzige Child-Pfad.

Scope und Zeit bleiben orthogonal: Ein Scope-Commit bewahrt CHRONIK-Range, Cursor,
Live/Replay und Playback-Speed; lediglich die Daten werden für denselben Zeitraum neu
gefragt. Zeit-Seek/Brush verändert umgekehrt niemals den Scope. Das ergibt den
beabsichtigten Filterraum `Raum × Zeit` ohne versteckte Resets.

Selection bleibt eine eigene Domäne, erhält aber eine explizite Commit-Policy: V1
löscht Event-/Track-/Facility-Selection und Event-Callout beim Scope-Commit, weil ihre
Zugehörigkeit noch nicht für jeden Layer bewiesen werden kann. Das Country-Almanac des
soeben betretenen Country darf geöffnet bleiben. Ein Circle-Spotlight wird bei einem
expliziten „Gebiet öffnen“ nach erfolgreichem Commit gelöscht; bei fehlgeschlagenem
Scope-Resolve bleibt er bestehen. Spätere Layer dürfen Selection nur dann erhalten,
wenn ihre Capability einen membership check für den neuen Scope implementiert.

Um keinen Ein-Frame-Stale-Flash bis zu einem React-Effect zu erzeugen, trägt eine
operative `SelectionEnvelope` die `selectedAtScopeStateRevision`. Der abgeleitete
Renderer zeigt sie nur bei gleicher Revision oder nach positivem membership check.
Der Cleanup-Effect entfernt die verborgene Selection danach aus ihrem eigenen Store.
Country-Selection trägt stattdessen ihren kanonischen `scopeKey` und bleibt sichtbar,
wenn er dem neuen `current.key` entspricht.

Die neue `CountrySelection` enthält mindestens `{ scopeKey, label }`, aber keine
Polygongeometrie. Der Backend-Almanac-Adapter löst den kanonischen Scope serverseitig
auf und liefert ISO/M49, Kapital und weitere Präsentationsdaten; ein fehlender
Almanac-Eintrag ändert den bereits committed Scope nicht.

Der neue Read-Vertrag lautet
`GET /api/almanac/country?scope_key=<encoded>&catalog_revision=<exact>`. Er akzeptiert
nur einen aufgelösten Country-Scope, mappt über den serverseitigen kanonischen
Crosswalk auf den bestehenden `CountryAlmanac` und gibt bei vorhandenem Scope ohne
Almanac `404` zurück. Der bestehende `/countries/{country_id}`-Pfad bleibt während der
Legacy-Phase, ist aber kein Spatial-Identitätsadapter.

### 18.3 Escape-Koordination

Der globale Escape-Listener wird aus `SpotlightProvider` entfernt. Ein zentraler WorldView-Keyboard-Coordinator verwendet diese Reihenfolge:

1. offenes Modal/temporären Inspector schließen beziehungsweise Selection löschen;
2. Circle-Spotlight löschen;
3. pending Scope-Resolve abbrechen und committed Scope halten;
4. wenn nichts Transientes aktiv und Scope nicht `world`: `ascend("keyboard")`.

Ein Keypress führt genau eine Action aus.

### 18.4 Pending und stale Wahrheit

- Während Resolve: alter Scope bleibt vollständig committed; Breadcrumb zeigt zusätzlich „opening …“.
- Nach Commit: alte Boundary und alte scope-abhängige Daten werden sofort verborgen.
- Boundary baut: neutraler Scope-Loading-State, keine alte Geometrie.
- CHRONIK lädt: Skeleton/leer mit Scope-Label, keine Daten des Vorgängers.
- Presentation fehlt: Scope bleibt mit sichtbarem „boundary unavailable“ nutzbar.
- Filter nur approximativ: Badge „bbox approximation“ beziehungsweise lokalisierter deutscher Text.
- Partial Coverage: Anzahl ausgeschlossener unlocated/conflicting Records in Detail/Tooltip.

### 18.5 Reduced Motion und Langzeitsitzung

```ts
interface WorldviewMotionSnapshot {
  readonly mode: "full" | "reduced" | "static";
  readonly source: "default" | "media-query" | "user";
  readonly revision: number;
}

interface WorldviewMotionStore {
  getSnapshot(): WorldviewMotionSnapshot;
  subscribe(listener: () => void): () => void;
  setUserMode(mode: WorldviewMotionSnapshot["mode"]): void;
}
```

`WorldviewMotionSnapshot` ist der eine live abonnierbare In-process-Zustand für
`full | reduced | static`; kein Modul liest `matchMedia` als Modulkonstante.
`prefers-reduced-motion` initialisiert `reduced`, eine sichtbare Einstellung darf auf
`static` wechseln und nur eine explizite Nutzeraktion auf `full` hochstufen.
`reduced` setzt Kamera-/Reveal-Dauer auf `0`, entfernt Ambient-Motion und aktualisiert
reale Live-Daten ohne dekorative Interpolation. `static` besitzt keine dauerlaufende
Animationsschleife, bewahrt aber Marks, Picks, Legenden und Datenupdates. Budgetierte,
pausierbare Ambient-Motion ist nur in `full` zulässig. Alle Layer und Presenter
konsumieren denselben Snapshot. Der 100-Zyklen-Disposal-Test bleibt Release-Gate.

### 18.6 Kartographische Provenance und Attribution

Die Cartography-Sektion im bestehenden § Layers-Panel erhält einen zugänglichen
„Data/Boundary policy“-Link. Er zeigt aktive `boundary_policy`, Katalogrevision,
Source-Release, Dispute-/Representation-Hinweis und die aus `attribution.json`
gelieferten Attributionen. CC-BY-Attribution ist damit im Produkt auffindbar und nicht
nur in einer Build-Datei versteckt. Texte stammen ausschließlich aus dem reviewten
Katalog; kein externer Autoren-Handle wird in generierte Source-Dateien injiziert.

---

## 19. Datengetriebene 3D-Darstellung — späterer, separater Adapter

Der Scope macht ODIN bereits räumlich „3D“, weil er auf dem Cesium-Globus, Terrain und Photoreal Tiles liegt. Extrudierte Administrativeinheiten sind ein separater `SpatialMetricLayer`, nicht Teil des Scope-Cores.

```ts
interface SpatialMetricDefinition {
  readonly definitionRevision: string;
  readonly metricId: string;
  readonly label: string;
  readonly unit: string;
  readonly aggregation: "sum" | "mean" | "max" | "count";
  readonly scale: "linear" | "log";
  readonly domain: readonly [number, number];
  readonly heightMeters: readonly [number, number] | null;
  readonly timeBasis: "instant" | "window";
  readonly missingValue: "transparent" | "hatched";
  readonly binning:
    | { readonly kind: "none" }
    | {
        readonly kind: "fixed-grid";
        readonly revision: string;
        readonly cellSizeMeters: number;
        readonly originLongitude: number;
        readonly originLatitude: number;
      };
}

interface SpatialMetricSample {
  readonly scopeKey: ScopeKey;
  readonly value: number | null;
  readonly observedAt: string;
  readonly coverage: number;
}

interface SpatialMetricSnapshot {
  readonly query: SpatialQueryRef;
  readonly definition: SpatialMetricDefinition;
  readonly dataRevision: string;
  readonly samples: readonly SpatialMetricSample[];
  readonly accounting: {
    readonly relation: "occurs-in";
    readonly precision: "semantic-key" | "point-in-boundary";
    readonly completeness: "complete" | "partial";
    readonly candidateCount: number;
    readonly includedCount: number;
    readonly excludedUnlocatedCount: number;
    readonly excludedConflictCount: number;
    readonly excludedBoundaryUncertainCount: number;
  };
}

interface SpatialMetricPort {
  load(
    request: {
      readonly query: SpatialQueryRef;
      readonly metricId: string;
      readonly definitionRevision: string;
      readonly childScopeKeys: readonly ScopeKey[];
      readonly window: { readonly start: string; readonly end: string };
    },
    signal: AbortSignal,
  ): Promise<SpatialMetricSnapshot>;
}
```

Regeln:

- jede Höhe kodiert eine benannte Metrik und Einheit;
- Legende, Zeitbasis, Scale und Clamping sind immer sichtbar;
- der numerische Wert `0` ist gültig; ausschließlich `value === null` ist Missing Data;
- log scale wird explizit markiert;
- Geometrie und Metric-Daten besitzen getrennte Revisionen;
- keine Extrusion ohne Daten;
- Arc/Fly-Line nur für echte gerichtete Beziehungen mit Richtung, Magnitude, Zeit und Confidence; keine dekorativen Capital-to-City-Bögen.
- Country-Child-Werte dürfen nie durch eine BBox-Abfrage pro Child entstehen;
  zulässig sind nur attestierte kanonische Keys oder fixes reviewtes Child-Containment.
- Ein Snapshot enthält jeden angeforderten direkten Child-Key genau einmal und
  sortiert; fehlende Messung ist ein explizites `value: null`, kein ausgelassener
  Sample. `coverage` liegt endlich in `[0, 1]`, und `candidateCount` reconciliert
  exakt mit included plus den drei disjunkten Exclusion-Countern.
- Query-Identität, Child-Set und Definition-Revision werden gegen den Request
  validiert; `metricId` muss in der geschlossenen Metric-Registry stehen.
  `dataRevision` wird schema-validiert und generation-gebunden. Ein Mismatch ist
  unavailable und darf keinen alten Snapshot behalten.
- Die Definition wird erst aktiviert, wenn Domain, optionaler Höhenbereich,
  Transport, Coverage, Accounting und bei Extrusion Base-Height-/Build-Budget in
  einem reviewten Promotion-Record belegt sind.

Der Port besitzt einen HTTP-Adapter für Produktion und einen In-memory-Adapter für
Tests. Eine Flat-Color-Darstellung ist ohne Höhenfreigabe zulässig. Ein späterer
Extrusionsadapter darf `PolygonGeometry`/`Primitive` verwenden, den aktiven Scope
lesen, aber niemals setzen.

---
