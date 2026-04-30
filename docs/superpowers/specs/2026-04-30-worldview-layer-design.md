# Worldview Layer-Design — Hlíðskjalf Noir · Forensic Lens

**Spec-Datum:** 2026-04-30
**Sprint:** S2 (Worldview-Port) — visuelle Schicht
**Aesthetic-Anker:** [Hlíðskjalf Noir](2026-04-14-odin-4layer-hlidskjalf-design.md) §2
**Inspirations-Set:** kuratierte 13 Bilder (TRON Pinterest-Board · `tags.json: odin`)

---

## §1 Vision & Scope

### §1.1 Was diese Spec ist

Diese Spec definiert das **visuelle Layer-System des CesiumJS-Globe** in der Worldview-Page (`/worldview`). Sie sitzt unterhalb des bereits in [`2026-04-14-odin-4layer-hlidskjalf-design.md`](2026-04-14-odin-4layer-hlidskjalf-design.md) §4.2 spezifizierten Overlay-Panel-Chrome (§ Layers · § Search · § Inspector · § Ticker) und beschreibt, was *im* Globe-Bild zu sehen ist.

### §1.2 Was diese Spec nicht ist

- Keine Chrome-/Panel-Spec — die liegt in `2026-04-14-odin-4layer-hlidskjalf-design.md` §4.2.
- **Keine Layer-Engine-Migration.** Die existierenden 16 `LayerVisibility`-Keys (siehe `services/frontend/src/types/index.ts:257`) bleiben strukturell separate React-Komponenten mit jeweils eigener `BillboardCollection` und eigenem `onSelect`-Handler. Diese Spec organisiert sie neu in der § Layers Panel UI nach den 4 Gruppen und vereinheitlicht ihre Glyph-Family-Tokens (siehe §3.8 Mapping-Tabelle). Eine Konsolidierung in eine einzige `EventGlyphs`-Komponente ist eigene Sprint-Arbeit (S2.5 oder später) und nicht Teil dieser Spec.
- **Keine Almanac-Datasourcing-Spec.** Country-Mode (§5) beschränkt sich in S2 auf das visuelle MVP: Polygon-Highlight + Capital-Pulse + Multilingual-Cartouche aus statischem Endonym-JSON. REST Countries · Wikidata SPARQL · Munin-Briefs · Neo4j Country-Queries · Active-Intel-Pulses bekommen eine eigene Backend-Spec (`2026-05-XX-country-almanac-data.md`).
- Keine Performance-Budget-Bestimmung — übernimmt das implementations-Plan.

### §1.3 Aesthetic Statement

**Kalt-warm-Forensik.** Schwarzes Void als Bühne · steel-blue Atmosphäre als Grenze · obsidian-vector Erde als geometrische Wahrheit · stone/ash Borders & Hydrography als feine kartographische Schrift · amber Network-Mesh als Nervensystem · sentinel/amber/sage Glyph-Familie für Live-Events · ember-warmer Photo-Reveal nur lokal in einer Spotlight-Linse, die der Nutzer per Zoom · Pin · Search · Country-Click öffnet.

Die warme Farb-Temperatur ist *belohnungs-codiert*: nur was der Nutzer aktiv investigiert, wird warm. Der Default-State ist kalt-stahlblau-grau.

### §1.4 Verbindlichkeiten gegen Hlíðskjalf

- Alle Farben sind CSS-Tokens aus `services/frontend/src/theme/hlidskjalf.css` oder neue Tokens im Delta (§6).
- Typografie nur Instrument Serif italic / Hanken Grotesk / Martian Mono.
- Grain-Overlay konsistent zur Landing/Briefing-Page.
- §-Eyebrow-Grammar (`§ <num> · <label>`) auch im Globe-Chrome.
- Hair-Lines statt Boxen, keine Rounded Corners außer Orrery.

---

## §2 Layer Stack — 10 Schichten, 4 Gruppen

Render-Reihenfolge **von unten nach oben**. Jede Schicht ist explizit benannt, hat eine eigene Cesium-Render-Strategie, und ist (außer Group A) im § Layers Panel toggle-bar.

> **Notation:** Die 10. Schicht „Chrome" ist intern in zwei DOM-Render-Pässe aufgeteilt — `09a` (Cartouche, Spotlight-adaptiv) und `09b` (HUD Frame, statisch). Beide bilden zusammen die Chrome-Schicht; in der Tabelle separat geführt für Klarheit der Render-Strategie.

| ID | Group | Name | Toggle | Render Strategy |
|---|---|---|---|---|
| 00 | A · Sky | Void & Stars | always-on | `Cesium.SkyBox` + procedural starfield |
| 01 | A · Sky | Atmosphere Halo | always-on | `Cesium.SkyAtmosphere` (rim 60–78% radius) |
| 02 | B · Earth | Globe Surface | always-on | bestehender Cesium-ImageryLayer-Stack (Google 3D Tiles + WorldImagery + Black Marble Ion 3812) — siehe §3.3, S2 ändert hier nichts |
| 03 | B · Earth | Graticule | toggle | `PolylineCollection` · 10° lat/long · clipped to globe |
| 04 | B · Earth | Country Borders | toggle | `PolylineCollection` · admin-0 polygons (`countries-110m.json` TopoJSON, bereits geladen via `MuninLoader`) |
| 05 | B · Earth | Hydrography | toggle | `PolylineCollection` · DEFERRED auf S2.5: rivers-Asset noch nicht im Repo (siehe §9). Coastlines liefert Layer 04 implizit. |
| 06 | C · Signal | Network Mesh | per-source toggle | bestehende `CableLayer` + `PipelineLayer` + `SatelliteLayer` (orbit lines) — getokenized auf `--mesh-line` |
| 07 | C · Signal | Event Glyphs | per-source toggle | 14 bestehende Glyph-Komponenten + 2 nicht-glyph Toggles (`countryBorders`, `cityBuildings`); siehe §3.8 Mapping. Eigene Cesium-Primitive-Collection pro Source (`BillboardCollection` oder `PointPrimitiveCollection`). S2 vereinheitlicht nur Tokens, keine Konsolidierung. |
| 08 | D · Lens | Spotlight | always-on (driven by `focusTarget`) | Polymorphic: `kind ∈ {circle, country}`. `Cesium.GroundPrimitive` mit `EllipseGeometry` (circle) bzw. `PolygonGeometry` (country, MultiPolygon-aware). Siehe §10.2. |
| 09a | D · Chrome | Cartouche | always-on, content adaptive | DOM overlay · adapts to `spotlight.kind` |
| 09b | D · Chrome | HUD Frame | always-on | DOM overlay · 4 corners + crosshair + scale-bar + UTC clock |

### §2.1 Group Semantics

- **A · Sky** — was außerhalb des Globe liegt. Always-on, statisch, nicht toggle-bar.
- **B · Earth** — geometrische Wahrheit der Erde. Gemeinsam toggle-bar als Gruppe „Cartography" + einzeln granular.
- **C · Signal** — alle Live-Daten. Pro existierendem Cesium-Datensource ein Toggle.
- **D · Lens & Chrome** — Spotlight-Reveal-Mechanismus + globales HUD. Always-on; Spotlight-Sichtbarkeit ist eine Funktion von `focusTarget`, nicht ein User-Toggle.

### §2.2 § Layers Panel UI

Das § Layers Panel (top-left, 240 px) zeigt drei Sektionen:

```
§ LAYERS                                7 / 9
─────────────────────────────────────
A · sky                       (always)
  · Void & Stars              [on]
  · Atmosphere                [on]
B · earth
  · Globe Surface             [vec]
  · Graticule                 [10°]
  · Country Borders           [on]
  · Hydrography               [s2.5]
C · signal · network mesh
  · Cables                    [on]
  · Pipelines                 [on]
  · Satellites (orbits)       [off]
C · signal · glyphs           (16 keys aus LayerVisibility)
  · flights                   [1247]
  · satellites                [off]
  · earthquakes               [4]
  · vessels                   [off]
  · cctv                      [off]
  · events                    [38]
  · cables                    [on]
  · pipelines                 [on]
  · countryBorders            [on]
  · cityBuildings             [off]
  · firmsHotspots             [412]
  · milAircraft               [12]
  · datacenters               [on]
  · refineries                [off]
  · eonet                     [on]
  · gdacs                     [off]
D · lens & chrome             (auto)
```

Die Glyph-Keys oben sind 1:1 die `LayerVisibility`-Felder aus `services/frontend/src/types/index.ts:257`. Jede Zeile mappt nicht auf eine eigene neue Komponente, sondern auf die bereits existierende Layer-Komponente in `services/frontend/src/components/layers/`. Group A bleibt anzeigend, aber nicht klickbar. Group D zeigt aktuellen Spotlight-Status (z.B. „pin · sinjar" oder „country · grc" oder „idle"), nicht toggle-bar.

> Hinweis zu `countryBorders` und `cityBuildings`: diese sind im aktuellen `LayerVisibility`-Contract als Glyph-Keys geführt, weil sie als Toggle-Items existieren. In dieser Spec gehört die Polyline-Border-Geometrie konzeptuell zu **Layer 04 · B · Earth**. Die `countryBorders`-Toggle-Logik bleibt unverändert; sie wird im § Layers Panel UI unter Group B angezeigt, nicht unter Group C.

---

## §3 Per-Layer Specifications

### §3.1 Layer 00 · Void & Stars

- **Geometry source:** procedural — kein Asset.
- **Render:** `Cesium.Scene.skyBox` mit eigener 6-faces SkyBox aus `pure black + sub-pixel star dust`. Stars als Distribution mit Density ≈ 0.0005/px², size ≤ 1.5 px.
- **Tokens:** background `--void` · stars `--star-dust` (color-mix --bone 70% transparent).
- **Motion:** statisch.

### §3.2 Layer 01 · Atmosphere Halo

- **Render:** `Cesium.Scene.skyAtmosphere` aktiviert mit custom-tinted hue-shift Richtung steel-blue.
- **Visuals:** outer rim glow zwischen 60–78% des Globe-Radius. Innerer 60% transparent. Outer 78% fade-out.
- **Tokens:** `--steel` mix mit 0.13 alpha.
- **Motion:** statisch (kein Breathing — bewusst gegen TRON-Klischee).

### §3.3 Layer 02 · Globe Surface

- **Existing-State (verifiziert in `GlobeViewer.tsx:74–145`):** der Globe besteht heute aus drei gestackten ImageryLayern, die Cesium intern komponiert und über Day/Night-Side-Blending darstellt:
  1. Google Photorealistic 3D Tiles (Standard-Day-Side; mit Custom-GLSL-Darken zur Nachtseite)
  2. `Cesium.createWorldImageryAsync` (Borders-Style, brightness 0.9)
  3. NASA Black Marble VIIRS (Ion Asset 3812, `dayAlpha:0 / nightAlpha:0.9`) — Stadtlichter auf der Nachtseite
- **S2-Änderung:** **keine.** S2 lässt die existierende ImageryLayer-Setup unverändert. Die warme Glow-Reveal-Wirkung kommt aus Layer 08 Spotlight (siehe §3.9 + §10.2), nicht aus einer Modifikation dieser Schicht.
- **Toggle-Kontrolle:** keine. Layer 02 ist always-on; einzelne ImageryLayer-Toggles sind Future Work (S2.5+).
- **Tokens:** keine eigenen — Imagery-Quellen liefern ihre Farben selbst. Hlíðskjalf-Tokens betreffen nur die *darüberliegenden* Layers 03–09b.

### §3.4 Layer 03 · Graticule

- **Geometry:** 10° Lat/Long-Linien, clipped to globe sphere.
- **Render:** `PolylineCollection` als single batch, GPU-instanced.
- **Tokens:** `--graticule` (color-mix --granite 80% --steel 20%) · 0.4 px stroke.
- **Motion:** rotiert mit dem Globe (kein eigenständiges Layer im Welt-Koordinatensystem).

### §3.5 Layer 04 · Country Borders

- **Geometry source:** **S2 MVP:** `services/frontend/public/countries-110m.json` (Natural Earth 1:110m TopoJSON, bereits geladen via `MuninLoader.tsx:25`). **S2.5 Upgrade-Pfad:** Natural Earth admin-0 1:50m als optionaler GeoJSON-Asset-Drop, sobald visuelle Auflösung gewünscht.
- **Render:** `PolylineCollection` single batch. TopoJSON wird via `topojson-client` zu GeoJSON dekodiert beim Mount, danach in eine Polyline-Geometrie umgewandelt.
- **Tokens:** `--stone` 0.6 px. Disputed/de-facto Borders dashed 4-2 (nur wenn die Asset-Quelle das markiert; 1:110m hat das nicht).
- **Hit-testing:** Polygon-Hit-Test für Layer 08 country-click trigger lebt in dieser Layer (siehe §4.4). Verwendet das gleiche TopoJSON, indexed via R-Tree (siehe §10.3).
- **Toggle-Kontrolle:** `LayerVisibility.countryBorders` (existing key).

### §3.6 Layer 05 · Hydrography

- **Status:** **DEFERRED auf S2.5.** Asset (Natural Earth rivers L1) ist nicht im Repo. Coastlines werden implizit von Layer 04 mitgerendert (TopoJSON-Country-Polygone enthalten die Küstenlinien).
- **Wenn implementiert:** `PolylineCollection` single batch · `--ash` 0.4 px · alpha 0.7.
- **Acceptance-Kriterium für S2:** Layer 05 darf fehlen, ohne dass das Worldview als „unfertig" gilt. Toggle wird im § Layers Panel als `[s2.5]` markiert (disabled mit Hover-Tooltip).

### §3.7 Layer 06 · Network Mesh

- **Geometry sources** (existing components, in S2 nicht konsolidiert):
  - `CableLayer` — submarine cables
  - `PipelineLayer` — pipeline network
  - `SatelliteLayer` — orbit polylines
  - Aktive Flight-Route — als Sub-Feature von `FlightLayer`, optional „pin a track" via Inspector
- **Render:** weiterhin pro Source eine eigene `PolylineCollection`. **S2 ändert nur Tokens** — alle Polylines bekommen `--mesh-line` (color-mix --amber 60% transparent) · 0.5 px · 0.55 alpha als shared visual identity.
- **Single active route:** ant-trail via `stroke-dashoffset` Animation, 8 s linear (nur für die eine vom User selektierte Track).
- **Toggle-Kontrolle:** weiterhin pro existierendem Layer-Key (`cables`, `pipelines`, `satellites`).

### §3.8 Layer 07 · Event Glyphs · Mapping-Tabelle

**Architektur (S2):** weiterhin **eine eigene Layer-Komponente pro `LayerVisibility`-Key**. Jede behält ihre Cesium-Primitive-Collection (Type variiert pro Layer — `BillboardCollection` oder `PointPrimitiveCollection`, je nach existierendem Code). Diese Spec ändert nur die *Tokens* (Glyph-Family pro Source) und die *Panel-Gruppierung*.

**Glyph-Familien:**
- **Sentinel pulse** (`--sentinel`) — incidents, threats, sudden events
- **Amber triangle** (`--amber`) — armed conflict / alert events
- **Stone square** (`--stone`) — static infrastructure
- **Sage ring** (`--sage`) — atmospheric / earth observation / hotspot signals

**Kanonische Mapping-Tabelle** — alle 16 `LayerVisibility`-Keys mit existierender Komponente, Cesium-Primitive-Type, und Glyph-Family-Zuordnung:

| Key | UI Label | Existing Component | Cesium Primitive | Glyph Family | Notes |
|---|---|---|---|---|---|
| `flights` | Flights | `FlightLayer.tsx` | `BillboardCollection` | stone square | civilian air traffic; pulse only on incident-tagged tracks |
| `satellites` | Satellites | `SatelliteLayer.tsx` | **`PointPrimitiveCollection`** | stone square | orbit endpoints; orbit-line in Layer 06 (NetworkMesh) |
| `earthquakes` | Earthquakes | `EarthquakeLayer.tsx` | `BillboardCollection` | sentinel pulse | USGS feed; magnitude scales pulse radius |
| `vessels` | Vessels | `ShipLayer.tsx` | `BillboardCollection` | stone square | AIS tracks; pulse on incident-tagged |
| `cctv` | CCTV | `CCTVLayer.tsx` | `BillboardCollection` | stone square | static fixed assets |
| `events` | Graph Events | `EventLayer.tsx` | `BillboardCollection` | **per event-type from codebook** | UCDP · GDELT · Telegram · custom feeds — glyph family lookup via `event_codebook.yaml` (NOT hardcoded; Two-Loop guarantee) |
| `cables` | Cables | `CableLayer.tsx` | `BillboardCollection` (incidents) + `PolylineCollection` (routes, see Layer 06) | sentinel pulse on incidents · stone square otherwise | dual-mode |
| `pipelines` | Pipelines | `PipelineLayer.tsx` | `BillboardCollection` (incidents) + `PolylineCollection` (routes) | sentinel pulse on incidents · stone square otherwise | dual-mode |
| `countryBorders` | Country Borders | (Layer 04, see §3.5) | `PolylineCollection` | — (not a glyph) | toggle lives in panel under Group B |
| `cityBuildings` | City Buildings | (Cesium 3D tileset) | `Cesium3DTileset` | — (not a glyph) | not in Group C; toggle lives in panel under Group B as „City Buildings" |
| `firmsHotspots` | FIRMS Hotspots | `FIRMSLayer.tsx` | `BillboardCollection` | sage ring | NASA fire detections |
| `milAircraft` | Mil-air | `MilAircraftLayer.tsx` | `BillboardCollection` | amber triangle | military air tracks |
| `datacenters` | Datacenters | `DatacenterLayer.tsx` | `BillboardCollection` | stone square | static infra |
| `refineries` | Refineries | `RefineryLayer.tsx` | `BillboardCollection` | stone square | static infra |
| `eonet` | EONET | `EONETLayer.tsx` | `BillboardCollection` | sage ring | NASA earth observation events |
| `gdacs` | GDACS | `GDACSLayer.tsx` | `BillboardCollection` | sentinel pulse | global disaster alerts |

> **Tabellen-Diktat:** Die Cesium-Primitive-Type-Spalte ist *deskriptiv*, nicht *präskriptiv* — sie dokumentiert was im Code heute existiert. S2 ändert keine Primitive-Types. Falls eine Layer-Komponente in S2.5+ konsolidiert wird, kann sich das ändern.

> **Click-Tag-Konvention:** Jede dieser Komponenten muss am Primitive ein Custom-Property mit Coords liefern (z.B. `_aircraftData.lat/lon`, `_eventData.lat/lon`, `_cableData.lat/lon`), damit der `EntityClickHandler` aus §10.4 sowohl Inspector als auch Spotlight feed kann. Die Tag-Konvention existiert bereits für `_eventData` und `_cableData` (siehe `EntityClickHandler.tsx`); für die anderen Sources wird sie in S2 vereinheitlicht.

> Der `events` key ist absichtlich generisch und delegiert die Glyph-Family-Wahl an das ODIN Event Codebook (`services/intelligence/codebook/event_codebook.yaml`). Damit bleibt die Codebook-Single-Source-of-Truth respektiert (Two-Loop-Architektur, siehe `CLAUDE.md`).

> Der `events` key ist absichtlich generisch und delegiert die Glyph-Family-Wahl an das ODIN Event Codebook (`services/intelligence/codebook/event_codebook.yaml`). Damit bleibt die Codebook-Single-Source-of-Truth respektiert (Two-Loop-Architektur, siehe `CLAUDE.md`). Eine UCDP/GDELT/Telegram-Aufsplittung als separate `LayerVisibility`-Keys ist explizit nicht in S2.

> Sub-Filter innerhalb `events` (z.B. „nur UCDP zeigen") sind eine UI-Feature für S2.5+, nicht für S2.

### §3.9 Layer 08 · Spotlight (polymorphic)

Der zentrale Reveal-Mechanismus. Polymorph in `kind`.

**Render-Pipeline:** beide Kinds rendern als `Cesium.GroundPrimitive` mit eigener Material-Appearance über der existierenden ImageryLayer-Stack. **Kein** Custom-Shader auf `globe.material`, **keine** PostProcessStage. Details siehe §10.2.

#### `kind = 'circle'`
- Trigger sources: zoom, pin-click, search-match (siehe §4.1–4.3).
- Shape: `Cesium.EllipseGeometry` um die Center-Coordinate, default radius ~ 1° (≈ 100 km am Äquator), skalierend mit `altitude`.
- Material: warm-amber Radial-Gradient (`color-mix(--amber 60%, transparent)` an center, falloff zu transparent am Rand).
- Chrome (Layer 09a · Cartouche): Coordinate-Cartouche `name · 36.34N · 41.87E · § <ref>`.

#### `kind = 'country'` · S2 visuelles MVP
- Trigger source: country-click via `EntityClickHandler` (siehe §4.4).
- Shape: GeoJSON `Polygon` *oder* `MultiPolygon` aus dem TopoJSON (29/177 Länder sind MultiPolygon: USA, Kanada, Russland, Indonesien, Phillipinen, Japan, Griechenland, …). Pro Subpolygon eine `Cesium.PolygonGeometry`-Instance, alle in einer GroundPrimitive batched.
- Material: solider Amber-Wash (`color-mix(--amber 35%, transparent)`) mit zusätzlicher Radial-Modulation um `capital.coords` (Mitte heller).
- Chrome:
  - **Capital pulse** (`--capital-red` `#e63a26`, größer als reguläre Glyphs, mit zusätzlichem Outer-Ring) auf `capital.coords` aus statischem Endonym-JSON.
  - **Multilingual cartouche** (Layer 09a) mit Endonyms aus dem statischen JSON aus §5.3.
  - **§ Inspector** (existing) zeigt Country-Header mit ISO-3, Name, Capital. Restliche Almanac-Inhalt = `S2.5 coming soon`-Placeholder (siehe §5.2).
- **NOT in S2:** Almanac-Panel, GeoNames cities1000, NASA Sentinel-2 daytime, Active-Intel-Pulses, Munin-Briefs, REST Countries detail fields, Neo4j Country-Queries, MajorCity-Labels. Alle in der Almanac-Spec für S2.5.

### §3.10 Layer 09a · Cartouche

DOM overlay. Adaptive an `spotlight.kind`. World-zu-Screen-Position über `Cesium.SceneTransforms.wgs84ToWindowCoordinates` pro Frame.

| Kind | Render |
|---|---|
| `idle` | hidden |
| `circle` | Coordinate-Cartouche right-aligned am Spotlight, weißer Instrument-Serif-Headline + Mono-Sub mit Coords/Höhe/Source |
| `country` | Greece-Style Multi-Language-Stack: ~10 Endonyms (siehe §5.3) in Hanken Grotesk light 11 px · ISO-Name in Hanken Grotesk light 96 px · Cyrillic-Variant in `--amber` 34 px (nur wenn im Endonym-JSON vorhanden, sonst weglassen) |

### §3.11 Layer 09b · HUD Frame

DOM overlay. Statisch im Layout. Adaptiert nicht an Spotlight-Kind.

- **4 Corners** (top-left, top-right, bottom-left, bottom-right): 4 px Eckwinkel in `--ash` 0.4 px stroke.
- **Crosshair** (am Globe-Center — 50%, 54%): kleine Striche oben/unten/links/rechts in `--ash` 0.4 px.
- **Top-left Eyebrow:** `§ worldview · <state> · <date>` Mono. State = `idle` | `focus · <name>` | `country · <iso3>`.
- **Top-right:** UTC clock + offset.
- **Bottom-left Scale-Bar:** dynamic, abhängig vom Zoom-Level. Format `<near> km — — <far> km`.
- **Bottom-right Coords:** lat/long/altitude unter Cursor (oder unter Spotlight-Center wenn focus aktiv).

---

## §4 Spotlight Mechanism — `focusTarget` State Machine

### §4.1 State Shape

```ts
type SpotlightKind = 'circle' | 'country';
type SpotlightTrigger = 'zoom' | 'pin' | 'search' | 'country';

type FocusTarget =
  | null  // idle
  | {
      kind: 'circle';
      trigger: 'zoom' | 'pin' | 'search';
      center: { lon: number; lat: number };
      radius: number;          // degrees
      altitude: number;        // m
      label: string;
      ref?: string;            // e.g. § 044
      sourcePin?: { layer: string; entityId: string };  // when trigger='pin'
    }
  | {
      kind: 'country';
      trigger: 'country';
      iso3: string;
      // 29 / 177 Länder in countries-110m.json sind MultiPolygon (USA, Kanada,
      // Russland, Indonesien, Phillipinen, Japan, Griechenland, …); beide
      // Geometry-Varianten müssen unterstützt werden.
      polygon: GeoJSON.Polygon | GeoJSON.MultiPolygon;
      capital: { name: string; coords: { lon: number; lat: number } };
      // S2: nur iso3 + polygon + capital + endonyms (aus statischem JSON gelesen
      // by SpotlightCartouche, nicht im FocusTarget). Active intel + majorCities
      // werden in S2.5 (Almanac-Spec) ergänzt.
    };
```

`focusTarget` lebt in einem React-Context (`SpotlightContext`) mit Reducer-Updates.

### §4.2 Triggers

| # | Trigger | Source | Action |
|---|---|---|---|
| 1 | Zoom | Camera height ≤ 500 km | dispatch `{kind:'circle', trigger:'zoom', center: cameraCenter, radius: f(altitude)}` |
| 2 | Pin click | `EntityClickHandler` picks ein primitive mit known data-tag (`_eventData`, `_cableData`, `_aircraftData`, …) | dispatch `{kind:'circle', trigger:'pin', center: glyph.position, sourcePin: {...}}` parallel zu existierendem `setSelected`-Update an den Inspector |
| 3 | Search match | Match accepted in § Search | camera flyTo + dispatch `{kind:'circle', trigger:'search', center: matchCoord, label: matchName, ref: matchRef}` |
| 4 | Country click | `EntityClickHandler` findet kein primitive · Spotlight-Hook läuft TopoJSON-Hit-Test | dispatch `{kind:'country', trigger:'country', iso3, polygon, capital}` |

### §4.3 Conflict Resolution

**Last-writer wins.** Wenn der Nutzer schon einen Pin offen hat und dann ein Land klickt, ersetzt das Country-Spotlight das Pin-Spotlight. Der § Inspector schließt sich automatisch (er gehörte zum Pin-Trigger).

### §4.4 Hit-Testing Reihenfolge · authoritative

Click-Events laufen über den **bereits existierenden** `EntityClickHandler` (`services/frontend/src/components/globe/EntityClickHandler.tsx`). Dieser pickt via `viewer.scene.pick(position)` und prüft custom data-tags am Primitive (`_eventData`, `_cableData`, `_aircraftData`, `_satelliteData`, etc.). S2 erweitert ihn an *einer* Stelle, statt jeden Layer einzeln zu touchen:

1. **Existing-Tag-Match** (`_eventData`, `_cableData`, …): bestehende Logik — `setSelected({type, data})` an den Inspector. **Neu in S2:** zusätzlich `spotlight.dispatch({kind:'circle', trigger:'pin', center: data.lat/lon, sourcePin: {layer, entityId}})`. Beide Updates parallel.
2. **No-tag-pick** (Pick traf nichts oder ein Primitive ohne known data-tag): Spotlight-Hook führt Country-Hit-Test gegen den TopoJSON-Index. Bei Hit → `spotlight.dispatch({kind:'country', trigger:'country', iso3, polygon, capital})`. Inspector wird mit `setSelected({type:'country', data})` parallel gefüttert.
3. **Kein Hit überhaupt:** ignore (no-op).

**Konsequenz für die Architektur:** **kein** existing Layer-Component bekommt einen neuen `onSelect`-Prop. Die Spotlight-Integration sitzt komplett im erweiterten `EntityClickHandler`. Das hält das Akzeptanzkriterium aus §14 ("kein Layer-Component-Refactor") wörtlich ein.

**Spatial Index für Country-Hit-Test:**

- Beim Mount: TopoJSON aus `countries-110m.json` mit `topojson-client` zu GeoJSON-Features dekodieren, R-Tree (`rbush`) mit Bounding-Boxes bauen (177 Features, ~30 ms einmalig).
- Pro Click: Pick `cartesian → Cartographic.toDegrees()`, R-Tree-Search mit Click-Point, dann **manueller Ray-Cast Point-in-Polygon-Test** auf den Kandidaten. Manuell statt `@turf/boolean-point-in-polygon`, weil turf nicht in `package.json` ist und der Test inline ~ 25 LOC braucht (siehe §10.3).
- **MultiPolygon:** Iteriere über alle Subpolygone; ein Hit in irgendeinem reicht.
- Erwartete Latenz: < 5 ms pro Click bei 177 Polygonen + ø 1.16 Subpolygone pro MultiPolygon-Country.

### §4.5 Exit

- `ESC` Taste: `focusTarget → null`, alle abhängigen Panels (Inspector, Almanac) schließen.
- Click ins Void (außerhalb Globe): same.
- Schließen-Button (X) am Cartouche oder Almanac-Panel: same.
- Kamera zoomt aus über 1500 km: nur wenn `trigger === 'zoom'` — dann auto-exit. Andere Triggers bleiben sticky.

### §4.6 Transitions

- Idle → Focused (any kind): 320 ms ease-out für Spotlight-Mask-Alpha 0→1, 240 ms ease-out für Cartouche-Opacity.
- Focused → Idle: 200 ms ease-in für Spotlight-Mask-Alpha 1→0, 160 ms für Cartouche.
- Focused (kind A) → Focused (kind B): cross-fade 240 ms (parallel out/in).

---

## §5 Country Mode · S2 visuelles MVP (Almanac als S2.5)

### §5.1 Scope-Definition für S2

S2 liefert das **visuelle** Country-Mode-Erlebnis. Die datengetriebenen Aspekte (REST Countries, Wikidata SPARQL, Munin-Briefs, Active-Intel-Queries, Neo4j Country-node-schema) werden in eine **separate Backend-Spec** ausgelagert: `2026-05-XX-country-almanac-data.md` (S2.5).

**S2 country-mode liefert:**
- Polygon-Highlight (`Cesium.GroundPrimitive` mit Material-Overlay, MultiPolygon-aware, siehe §3.9 + §10.2)
- Capital-Pulse (`--capital-red`, größer als reguläre Glyphs)
- Multilingual-Cartouche (Endonyms aus statischem JSON, siehe §5.3)
- § Inspector slide-in mit minimalem Country-Header und „§ Almanac · S2.5 coming soon"-Placeholder

**S2 country-mode liefert NICHT:**
- Static facts (population, GDP, government, military, etc.)
- §Context Narrative (2-Satz-Brief)
- §Active Intel Pulses
- „read full dossier" / „ask Munin about" Actions

### §5.2 § Inspector Layout im country-mode (S2-Version)

`§ Inspector` (existing slide-in panel) zeigt im country-mode:

```
§ INSPECTOR · COUNTRY · GRC
─────────────────────
Hellenic Republic                       (Instrument Serif italic 22 px)
Ελληνική Δημοκρατία · iso · grc        (eyebrow)

CAPITAL    Athens · 37.98N 23.73E

§ ALMANAC · S2.5 COMING SOON
[hairline · 220px · ash placeholder block]

▸ esc · close spotlight
```

Dieser Inhalt rendert aus dem statischen Endonym-JSON allein. Kein Backend-Call, keine Datenbank-Query.

### §5.3 Statisches Endonym-JSON (S2 Asset)

**Datei:** `services/frontend/public/country-endonyms.json` (~ 60 KB, Root-relativ — konsistent mit `countries-110m.json`).

**Schema:**

```json
{
  "GRC": {
    "iso3": "GRC",
    "names": {
      "en": "Greece",
      "official": "Hellenic Republic",
      "native": "Ελληνική Δημοκρατία",
      "endonyms": {
        "el": "Ελλάδα",
        "ru": "Греция",
        "de": "Griechenland",
        "fr": "Grèce",
        "es": "Grecia",
        "it": "Grecia",
        "tr": "Yunanistan",
        "ar": "اليونان",
        "zh": "希腊",
        "ja": "ギリシャ"
      }
    },
    "capital": {
      "name": "Athens",
      "lat": 37.9838,
      "lon": 23.7275
    }
  }
}
```

**Generierung:** einmaliger Wikidata-Snapshot beim Repo-Build (offline, nicht per User-Click). Skript `scripts/build-country-endonyms.mjs` queryt Wikidata SPARQL für alle ~190 Länder, schreibt das JSON. Kommt ins Git-Repo, wird nicht zur Laufzeit aktualisiert.

### §5.4 Capital Pulse (Layer 08, country-mode · S2)

- Position: `capital.lat / capital.lon` aus dem JSON oben.
- Visual: 6 px solid `--capital-red` (`#e63a26`) + Outer-Ring 14 px `rgba(230,58,38,.5)` 1 px stroke + Glow 14 px box-shadow.
- City Label: `Hanken Grotesk 11 px · --city-label · text-shadow 0 0 4px black` rechts vom Pulse.
- Größere Sichtbarkeit als reguläre Glyphs (Layer 07), damit das Capital sofort heraussticht.

### §5.5 City Labels · S2.5

Top-N Major Cities sind **out of scope für S2** (kein GeoNames cities1000 Asset im Repo). Im Implementation-Plan: Capital allein reicht für das visuelle MVP.

---

## §6 Token Delta zu `hlidskjalf.css`

Bestehende Hlíðskjalf-Tokens decken alle Glyph-Farben ab. Neu erforderlich:

| Token | Value | Used by |
|---|---|---|
| `--steel` | `#3a5a78` | Atmosphere rim · Spotlight inner glow |
| `--mesh-line` | `color-mix(in srgb, var(--amber) 60%, transparent)` | Network Mesh stroke |
| `--graticule` | `color-mix(in srgb, var(--granite) 80%, var(--steel) 20%)` | 10° grid hairlines |
| `--lens-bracket` | `var(--amber)` | Spotlight corner brackets |
| `--star-dust` | `color-mix(in srgb, var(--bone) 70%, transparent)` | Void starfield |
| `--capital-red` | `#e63a26` | Capital pulse (intentional shift from `--sentinel` für extra Distinktion) |
| `--city-label` | `#ffd07a` | City labels in country-mode (warm yellow consistent mit Greece-reference) |

Diese Tokens werden in `services/frontend/src/theme/hlidskjalf.css` direkt nach den existierenden Accents eingefügt. Keine Hex-Werte direkt in Components.

---

## §7 Motion Budget

| Layer | Motion | Params | Reduced-Motion fallback |
|---|---|---|---|
| 00 Void & Stars | static | — | no change |
| 01 Atmosphere | static (kein breathing) | — | no change |
| 02 Globe Surface | user-driven rotation | drag · momentum 0.92 | disable momentum |
| 03 Graticule | rotates with globe | — | no change |
| 04 Borders | rotates with globe | — | no change |
| 05 Hydrography | rotates with globe | — | no change |
| 06 Network Mesh | nodes static · 1 active route ant-trail | `stroke-dashoffset` · 8 s linear | disable ant-trail |
| 07 Event Glyphs (sentinel) | radial pulse on incidents only | opacity 0.4→0 + r 1→2x · 1.6 s | single static halo |
| 08 Spotlight | mask-alpha fade | 320 ms ease-out (in) · 200 ms ease-in (out) | 120 ms hard cut |
| 08 Capital Pulse (country-mode) | radial pulse | opacity 0.5→0 + r 1→2.4x · 2.0 s | single static halo |
| 09a Cartouche | opacity-rotate on focus change | 240 ms ease-out | hard set |
| 09b HUD Frame | static, content live-update | — | no change |

**Globaler Performance-Floor:** ≥ 55 FPS bei Kamera-Rotation mit allen Layers on, 1080p. Verifikation per Lighthouse + Cesium FPS counter. Wird im Implementation-Plan budgetiert mit Profiling-Task.

---

## §8 Chrome Integration mit §4.2 Panels

Das Layer-Stack-System sitzt unter den bereits gespeccten Hlíðskjalf-Overlay-Panels (`2026-04-14-odin-4layer-hlidskjalf-design.md` §4.2). Folgende Konsequenzen:

| Panel | Spec-Update durch dieses Dokument |
|---|---|
| § Layers | Inhalt wird *neu strukturiert* nach den 4 Gruppen (A · Sky / B · Earth / C · Signal / D · Lens & Chrome). Group A nicht-toggle-bar (deaktiviert), Group D zeigt Spotlight-Status statt Toggles. Die 16 existierenden `LayerVisibility`-Keys werden 1:1 in Group B und C eingegliedert (siehe §3.8 Tabelle); kein Contract-Change. |
| § Search | Match-Acceptance triggert 3. Spotlight-Trigger (siehe §4.2). |
| § Inspector | Im pin-mode unverändert (existing per-layer `onSelect`-Handlers wirken weiter). Im country-mode zeigt der § Inspector den minimalen Country-Header aus statischem Endonym-JSON (§5.2). ESC schließt beides. |
| § Ticker | Unverändert. Click auf Ticker-Item triggert internen `focusTarget`-Dispatch (`circle` mit Item-Coords). |

---

## §9 Data Dependencies

**Verifiziert gegen aktuellen Repo-Stand am 2026-04-30.** Nur was hier mit *Existing in repo* markiert ist, ist tatsächlich vorhanden; alles andere ist neue Asset-Pipeline-Arbeit.

| Source | Use | Existing? | Action für S2 |
|---|---|---|---|
| `countries-110m.json` (Natural Earth admin-0 1:110m TopoJSON) | Layer 04 Borders + Layer 08 country polygon hit-test | **Existing** in `services/frontend/public/`, geladen via `MuninLoader.tsx:28` aus `/countries-110m.json` (Repo-Root-relativ, **NICHT** `/geo/`) | Wiederverwenden, **gleicher Pfad** behalten |
| NASA Black Marble VIIRS (Ion Asset 3812) | Globe Layer 02 Nachtseite Stadtlichter | **Existing** — `GlobeViewer.tsx:128` integriert das via `IonImageryProvider.fromAssetId(3812)` mit `dayAlpha:0 / nightAlpha:0.9` | Unverändert lassen |
| Google Photorealistic 3D Tiles | Globe Layer 02 Tagseite | **Existing** — `GlobeViewer.tsx:74` mit Custom-GLSL für Nachtseiten-Darken | Unverändert lassen |
| Natural Earth admin-0 1:50m (höhere Auflösung) | optional visuelles Upgrade Layer 04 | **Not in repo** | DEFERRED auf S2.5 wenn 1:110m visuell ausreicht |
| Natural Earth rivers L1 | Layer 05 Hydrography | **Not in repo** | DEFERRED auf S2.5 |
| `country-endonyms.json` (Wikidata-Snapshot) | Layer 08 country-mode multilingual cartouche + capital coords | **Not in repo** | NEU: build script `scripts/build-country-endonyms.mjs`, einmalig generiert, ~ 60 KB. **Pfad: `services/frontend/public/country-endonyms.json`** (Root-relativ, konsistent mit `countries-110m.json`) |
| `rbush@^4` | Spatial-Index für Country-Hit-Test | **Transitiv im Lockfile**, nicht als direkte Dependency | Add zu `package.json` `dependencies` als `"rbush": "^4.0.1"` |
| `@turf/boolean-point-in-polygon` | Point-in-Polygon-Test | **Not present** | NICHT installiert — stattdessen inline 25-LOC Ray-Cast PIP (siehe §10.3) |
| Sentinel-2 daytime composite | Layer 02 day-mode | **Not integrated** | Out of scope · S2.5+ |
| GeoNames cities1000 | Layer 08 country-mode major cities | **Not integrated** | Out of scope · S2.5 (Country-Almanac-Spec) |
| REST Countries · Wikidata SPARQL · Munin briefs · Neo4j Country-node-schema | Almanac dynamic content | **Not integrated** | Out of scope · S2.5 (separate Spec `2026-05-XX-country-almanac-data.md`) |

---

## §10 Cesium Implementation Notes

### §10.1 Pflicht-Patterns aus CLAUDE.md

- **BillboardCollection / PointPrimitiveCollection** statt Entity-API für Bulk-Rendering. Welche der beiden — folgt der existierenden Per-Layer-Wahl (siehe §3.8 Tabelle).
- **CallbackProperty** für smooth tracking ohne React re-renders.
- **GroundPrimitive mit eigener Material** für Spotlight-Overlay (siehe §10.2 — *kein* Custom-GLSL auf `globe.material`, *kein* PostProcessStage).
- Async cleanup mit `if (viewer.isDestroyed()) return;` guard (siehe S2-Backlog `project_s2_worldview_backlog.md`).

### §10.2 Spotlight Render-Pipeline · authoritative · revised

**Schlüsselbeobachtung:** Der existierende `GlobeViewer.tsx:128` integriert NASA Black Marble bereits als `Cesium.IonImageryProvider.fromAssetId(3812)` mit `dayAlpha:0 / nightAlpha:0.9`. Auf der Nachtseite des Globe **sind die Stadtlichter bereits sichtbar** — Cesium handhabt das Day/Night-Blending intern. Die ursprüngliche „Photo-Reveal"-Idee war ein Missverständnis dieser Architektur.

**Was Spotlight tatsächlich rendert:** ein **warm-ember Highlight-Overlay** auf dem bereits sichtbaren Globe, nicht eine Photo-Imagery-Reveal-Mask. Das Greece-Reference-Bild zeigt genau das: Black Marble Stadtlichter (von Cesium gerendert) + ein zusätzlicher Amber-Wash über dem Polygon (das ist der Spotlight-Beitrag).

**Pipeline (S2 · authoritative):**

1. **Spotlight-Geometrie als Cesium GroundPrimitive:**
   - `kind = 'circle'`: `Cesium.GeometryInstance` mit `Cesium.EllipseGeometry` um Center-Coord, Radius `f(altitude)`. Eine Geometry-Instance pro Spotlight.
   - `kind = 'country'`: für `Polygon` → eine `Cesium.PolygonGeometry`-Instance; für `MultiPolygon` → mehrere Instances, alle in einer `Cesium.GroundPrimitive` als ein Batch.
2. **Material:** `Cesium.MaterialAppearance` mit Custom `Material` aus dem Cesium-Material-System (`Material.fabric` JSON). Die Material-Definition:
   - `kind = 'circle'`: `Material.RadialGradient` (Cesium-Built-in) mit Center=spotlight-center, color=`color-mix(--amber 60%, transparent)`, falloff radial.
   - `kind = 'country'`: einfaches `Material.Color` mit `color-mix(--amber 35%, transparent)` plus Multiplikator-Channel der zur Polygon-Mitte hin warmer wird (anchored an `capital.coords`).
3. **Z-Order:** GroundPrimitive `classificationType: Cesium.ClassificationType.TERRAIN` — clamped auf die Erdoberfläche, sichtbar über Black Marble aber unter den Glyph-BillboardCollections.
4. **Fade-In/Out:** Material-Color-Alpha über `Cesium.CallbackProperty` interpoliert (320 ms in, 200 ms out). Bei `alpha → 0` wird die GroundPrimitive aus `viewer.scene.primitives` entfernt.
5. **Capital-Pulse + Cartouche:** unabhängig von der GroundPrimitive — als DOM-Overlays gerendert (`SpotlightCartouche.tsx`, `HudFrame.tsx`), weltkoordinaten-zu-screen via `Cesium.SceneTransforms.wgs84ToWindowCoordinates` pro Frame.

**Was diese Pipeline NICHT braucht:**
- Kein Custom Shader auf `globe.material`.
- Keine `PostProcessStage`.
- Keine Off-Screen-Canvas Mask-Texture.
- Keine zusätzliche `ImageryLayer`-Anbindung (Black Marble bleibt unverändert wo es jetzt ist).

**Was an `GlobeViewer.tsx` zu ändern ist:** **nichts** für die Spotlight-Pipeline. Der Mount-Code in `useEffect` ist unangetastet. Die Spotlight-Komponenten registrieren ihre GroundPrimitive auf `viewer.scene.primitives` und räumen wieder auf.

> **Risiko:** Cesium's `Material.RadialGradient` verlangt evtl. einen Custom-`fabric.source` GLSL-Snippet je nach Cesium-Version. Falls die eingebaute Material-Library keinen passenden Built-in liefert, ist ein **kleiner** Custom-Material-GLSL-Snippet im `Material`-System der Fallback (~ 15 LOC). Das ist deutlich schmaler als ein voller globe.material-Refactor und im Implementation-Plan als Spike-Task budgetiert.

### §10.3 Manueller Point-in-Polygon-Test (kein turf-Dependency)

Da `@turf/boolean-point-in-polygon` nicht in `package.json` ist und für strict TS ein zusätzliches Type-Package nötig wäre, implementieren wir den Ray-Cast PIP inline:

```ts
// services/frontend/src/components/globe/hooks/pointInPolygon.ts
type Ring = [number, number][];

function ringContains(ring: Ring, lon: number, lat: number): boolean {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i];
    const [xj, yj] = ring[j];
    const intersect =
      yi > lat !== yj > lat &&
      lon < ((xj - xi) * (lat - yi)) / (yj - yi) + xi;
    if (intersect) inside = !inside;
  }
  return inside;
}

export function polygonContains(
  polygon: GeoJSON.Polygon | GeoJSON.MultiPolygon,
  lon: number,
  lat: number
): boolean {
  const polygons = polygon.type === "Polygon" ? [polygon.coordinates] : polygon.coordinates;
  for (const poly of polygons) {
    const [outer, ...holes] = poly as Ring[];
    if (!ringContains(outer, lon, lat)) continue;
    if (holes.some((h) => ringContains(h, lon, lat))) continue;
    return true;
  }
  return false;
}
```

**Spatial-Index:** `rbush@^4` ist bereits transitiv im Lockfile. Für expliziten Import wird `rbush` als direkte Dependency in `package.json` hinzugefügt:

```json
{
  "dependencies": {
    "rbush": "^4.0.1"
  }
}
```

Bbox per Country (für rbush): aus den GeoJSON-Coordinates beim Mount ableiten — kein zusätzlicher Asset-Drop, kein Pre-Build-Step.

### §10.4 Existing-Layer-Strategie · authoritative · revised

**Diese Spec konsolidiert NICHT.** Die 16 existierenden `LayerVisibility`-Keys mit ihren jeweiligen Komponenten bleiben unverändert. Was diese Spec ändert:

- **Token-Vereinheitlichung** — alle existierenden Glyph-Layer ziehen Glyph-Family-Tokens aus §6 statt eigener Hex-Werte. Pro Layer: ein einzeiliger Color-Swap auf das passende Token aus §3.8.
- **Spotlight-Integration über `EntityClickHandler`, NICHT per-Layer onSelect** — der bestehende `EntityClickHandler` bekommt drei Erweiterungen (alle in dieser einen Datei):
  1. Bei jedem `_eventData`/`_cableData`/`_aircraftData`/etc. Match: zusätzlich zum `setSelected({type, data})` auch `spotlight.dispatch(...)` rufen.
  2. Bei "no tag" Pick: Country-Hit-Test (R-Tree + manueller PIP) gegen TopoJSON, bei Hit: Spotlight + Inspector parallel füttern.
  3. Bei ESC oder Click ins Void: `spotlight.dispatch({type:'reset'})`.
- **Panel-Re-Gruppierung** — `LayersPanel.tsx` UI ändert die Reihenfolge der Toggle-Items entsprechend §3.8 Mapping, ohne die `LayerVisibility`-Keys selbst zu touchen.

**Konsolidierung (`useGlyphMerger`, single `BillboardCollection`) ist eine separate Sprint-Spec für S2.5+** und nicht Teil dieser Spec.

---

## §11 Open Questions / Out-of-Scope

### §11.1 Out of Scope für S2

- **Layer-Engine-Migration** — die 16 existierenden Layer-Komponenten bleiben separat. Konsolidierung in `EventGlyphs` mit `useGlyphMerger` ist eigene Sprint-Arbeit (S2.5+).
- **Country-Almanac-Datasourcing** — REST Countries · Wikidata SPARQL (zur Laufzeit) · Munin briefs · Active-Intel-Pulses · Neo4j Country-node-schema bekommen eigene Backend-Spec `2026-05-XX-country-almanac-data.md`.
- **GeoNames cities1000** — Major-City-Labels (außer Capital) sind S2.5-Feature.
- **Layer 05 Hydrography** — Rivers-Asset nicht im Repo. Coastlines kommen implizit von Layer 04 Country Borders.
- **Natural Earth 1:50m Asset-Upgrade** — S2 verwendet das bereits geladene `countries-110m.json`. Höhere Auflösung in S2.5 nur wenn visuell nötig.
- **Sentinel-2 daytime imagery composite** — Black Marble allein deckt den Forensic-Aesthetic. Verschoben auf S2.5+.
- **Disputed-territory rendering policy** — z.B. Western Sahara, Crimea, Taiwan. Aktuell: Asset-default. Editorial-Entscheidung später.
- **Animated time-slider** — Feature für War Room (S4).
- **Country-zu-Country Comparison-Mode** — Multi-select Spotlight ist Future Work.

### §11.2 Offene Fragen für Implementation-Plan

1. **Mask-Texture-Resolution für country-mode:** 1024×1024 ist konservativ (ausreichend für ~177 Länder); ggf. 2048 für Russland/China. Empfehlung: dynamisch nach Polygon-Bbox-Diagonale.
2. **Black Marble GIBS Tile-Caching:** GIBS-Endpunkt direkt anrufen oder Browser-Cache + ODIN-Backend-Proxy? Empfehlung für S2: direkter GIBS-Call (Standard-Cesium-Pattern), Proxy in S2.5 wenn Latency-Issues auftauchen.
3. **Endonym-Sprachen-Pool:** `country-endonyms.json` enthält pro Land ~ 8–12 Endonyms (10 Beispielsprachen aus §5.3). Welche genau? Empfehlung: top-10 Wikipedia-Languages global + offizielle Endonym, also identischer Set für alle Länder. Reduziert Code-Komplexität.

Diese drei werden im Implementation-Plan addressed (oder explizit deferred).

---

## §12 Test Surface

### §12.1 Unit / Component Tests

- `SpotlightContext` reducer: alle Trigger-Übergänge (idle → kind-A → kind-B → idle) decken.
- Country-click hit-test (`useCountryHitTest`): gegeben (lon, lat) → korrektes ISO-3 (Test-Daten: 10 known coordinates spanning continents).
- Country-Inspector-Header: gegeben `iso3 = 'GRC'` → endonym + capital aus statischem JSON gerendert, missing-data fallback graceful.
- Pin-Trigger-Adapter: jeder existierende Layer-Component dispatched korrekt zum Spotlight-Reducer und behält gleichzeitig sein `setSelected`-Update an den Inspector.

### §12.2 Visual Regression — out of scope für S2

Visual Regression ist konsistent mit der Parent-Spec (`2026-04-14-odin-4layer-hlidskjalf-design.md` §13.1) **nicht in S2 verpflichtend**. Dev-Snapshots als optionales Hilfsmittel sind erlaubt, aber kein Acceptance-Gate. Diese Sektion existiert nur als Future-Hook für eine eigene QA-Spec.

### §12.3 Performance

- Cesium FPS counter aktiv halten in Dev-Mode.
- Lighthouse audit auf `/worldview` mit allen Layers on: ≥ 55 FPS bei Kamera-Rotation.

---

## §13 Mapping zu existierender Codebase

Nach S2-Port ergibt sich folgende File-Struktur. **Bestehende Layer-Komponenten unter `services/frontend/src/components/layers/` bleiben erhalten** — diese Spec fügt nur neue Files hinzu und edited bestehende Token-Stellen.

```
services/frontend/src/
├── theme/hlidskjalf.css                    # erweitert mit §6 Token-Delta (7 neue Tokens)
├── pages/WorldviewPage.tsx                 # existing — wird in S2 zu Hlidskjalf-Chrome refactored, behält 16 Layer-Mounts
├── components/
│   ├── globe/                              # existing — bleibt strukturell erhalten
│   │   ├── GlobeViewer.tsx                 # existing — unverändert (Black Marble bleibt wo es ist)
│   │   ├── EntityClickHandler.tsx          # existing — wird in S2 erweitert um Spotlight-Dispatch (siehe §10.4)
│   │   ├── visual-layers/                  # NEU — die rein-visuellen Layer aus §3.4–3.6
│   │   │   ├── Graticule.tsx               # Layer 03
│   │   │   ├── CountryBorders.tsx          # Layer 04 (Polyline-Render aus countries-110m)
│   │   │   └── Hydrography.tsx             # Layer 05 — DEFERRED auf S2.5, leerer Stub mit Toggle [s2.5]
│   │   ├── spotlight/                      # NEU
│   │   │   ├── SpotlightContext.tsx        # focusTarget Reducer
│   │   │   ├── SpotlightOverlay.tsx        # Layer 08 — Cesium GroundPrimitive + Material (Ellipse / Polygon / MultiPolygon)
│   │   │   ├── SpotlightCartouche.tsx      # Layer 09a — DOM overlay, adaptiv
│   │   │   ├── HudFrame.tsx                # Layer 09b — DOM overlay statisch
│   │   │   └── CountryHeader.tsx           # §5.2 minimal country-header für § Inspector
│   │   └── hooks/
│   │       ├── pointInPolygon.ts           # 25-LOC Ray-Cast PIP, MultiPolygon-aware (§10.3)
│   │       ├── useCountryHitTest.ts        # rbush + pointInPolygon
│   │       └── useSpotlightTrigger.ts      # bündelt zoom/search-Trigger (pin + country sind im EntityClickHandler)
│   └── layers/                             # existing — bleibt unverändert in der Struktur
│       ├── FlightLayer.tsx                 # nur Token-Updates (Glyph-Family aus §6)
│       ├── SatelliteLayer.tsx              # nur Token-Updates
│       ├── EarthquakeLayer.tsx             # nur Token-Updates
│       ├── … (alle 13 weiteren existierenden Layer-Komponenten)
│       └── (kein Eintrag wird hier entfernt in S2)
└── public/
    ├── countries-110m.json                 # existing TopoJSON (Root-relativ, unverändert)
    └── country-endonyms.json               # NEU (Root-relativ, NICHT in /geo/)

scripts/
└── build-country-endonyms.mjs              # NEU, einmalig generiert das Endonym-JSON

# NICHT in dieser Spec: services/data-ingestion/feeds/country_almanac/ — siehe S2.5 Almanac-Spec.
```

---

## §14 Akzeptanzkriterien für S2-Worldview-Port (relevant für dieses Spec)

- [ ] Layer-Stack 00, 01, 02, 03, 04, 06, 07, 08, 09a, 09b implementiert mit den oben dokumentierten Render-Strategies (Layer 05 Hydrography ist S2.5).
- [ ] § Layers Panel zeigt die 4-Gruppen-Struktur. Group A nicht-toggle-bar, Group D zeigt Spotlight-Status. 16 existierende `LayerVisibility`-Keys werden 1:1 unter Group B/C eingegliedert.
- [ ] Vier Trigger funktionieren: zoom (camera ≤ 500 km), pin click (über erweiterten `EntityClickHandler` aus §10.4 — *kein* per-Layer `onSelect`-Adapter), search match, country click (Polygon + MultiPolygon hit-test gegen TopoJSON).
- [ ] Country-Hit-Test funktioniert für alle 177 Country-Polygone, inklusive der 29 MultiPolygon-Länder (USA, Kanada, Russland, Indonesien, Phillipinen, Japan, Griechenland, Vereinigtes Königreich, Italien, Norwegen, …) — Click auf Alaska und Hawaii beide erkennen `USA`.
- [ ] `focusTarget` Reducer ist last-writer-wins, ESC räumt auf, kein Layer-Component-Refactor nötig.
- [ ] Country-mode rendert Polygon-Mask-Reveal, Capital-Pulse, Multilingual-Cartouche aus statischem `country-endonyms.json`. § Inspector zeigt Country-Header mit `S2.5 coming soon`-Hinweis für Almanac.
- [ ] Token-Delta aus §6 in `hlidskjalf.css` integriert. Existing Layer-Komponenten verwenden die neuen Tokens statt eigener Hex-Werte.
- [ ] ≥ 55 FPS Kamera-Rotation bei allen Layers on, 1080p (verifiziert per Cesium FPS counter).
- [ ] Reduced-motion: alle Animationen schalten korrekt um (verifiziert via DevTools `prefers-reduced-motion`).
- [ ] Existing 16 Layer-Komponenten in `services/frontend/src/components/layers/*.tsx` bleiben strukturell unverändert (kein Konsolidierungs-Refactor).

---

## §15 Anhang A · Inspirations-Mapping

| Reference Image | Pinterest ID | Beeinflusst |
|---|---|---|
| Greece (warm ember country mass + multilingual cartouche) | `463730092907532051` | §3.9 country-mode · §3.10 cartouche · §5 almanac panel |
| Total Recall opening | `463730092907211848` | §3.3 globe surface · §3.10 cartouche typography |
| Australia 6 Sec Before Impact | `463730092907211872` | §3.11 HUD Frame (corners + crosshair + scale) |
| Bilbao Layer Stack Diagram | `463730092907211878` | §2 layer-stack core metaphor |
| Blockchain Earth (warm orange nodes on cool earth) | `463730092907211941` | §3.7 network mesh nodes · §3.2 globe surface |
| True Anomaly Space-Force UI | `463730092907470064` | §3.10 cartouche · §5 almanac panel layout |
| London 3D Block | `463730092907507320` | §3.9 spotlight circle (alternate hero presentation) |
| Lake Atitlán | `463730092907507322` | §3.9 spotlight chrome bracket detail |
| South America Wireframe | `463730092907532047` | §3.4 country borders treatment |
| Africa Mesh in C4D | `463730092907532048` | §3.7 network mesh density target |
| Sochi 2014 Projection | `463730092907532051` | §3.9 country fill texture inspiration |
| Cape Town SPECTRE Forensic | `463730092907536478` | §3.11 HUD information density · §5.3 panel data-stack |
| Dense Atmosphere (echophon) | `463730092876757638` | §3.1 starfield density · §3.2 globe edge dust |

---

**End of Spec**
