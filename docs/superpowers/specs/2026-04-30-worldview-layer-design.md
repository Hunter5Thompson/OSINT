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
- Keine Daten-Layer-Auswahl — die existierenden 14 Cesium-Datensquellen (FlightLayer, SatelliteLayer, EarthquakeLayer, FIRMSLayer, …) bleiben strukturell unverändert; sie werden in dieser Spec lediglich der Schicht-Gruppe **C · Signal** zugeordnet.
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
| 02 | B · Earth | Globe Surface | toggle | Custom `globe.material` shader · vector default · raster reveal in Spotlight |
| 03 | B · Earth | Graticule | toggle | `PolylineCollection` · 10° lat/long · clipped to globe |
| 04 | B · Earth | Country Borders | toggle | `PolylineCollection` (single batch) · Natural Earth admin-0 |
| 05 | B · Earth | Hydrography | toggle | `PolylineCollection` (single batch) · Natural Earth coastline + rivers L1 |
| 06 | C · Signal | Network Mesh | per-source toggle | `PolylineCollection` per source (cables · routes · pipelines) |
| 07 | C · Signal | Event Glyphs | per-source toggle | `BillboardCollection` (single batch) · all 14 data sources collapse here |
| 08 | D · Lens | Spotlight | always-on (driven by `focusTarget`) | Polymorphic: `kind ∈ {circle, country}`. Cesium PostProcess Stage with radial-mask (circle) or polygon-clip (country) |
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
  · Hydrography               [off]
C · signal
  · Network Mesh              [3 src]
  · Glyphs · UCDP             [38]
  · Glyphs · FIRMS            [412]
  · Glyphs · Mil-air          [12]
  · Glyphs · Satellites       [off]
  · Glyphs · Earthquakes      [4]
  · Glyphs · Cables           [on]
  · Glyphs · Vessels          [off]
  · Glyphs · CCTV             [off]
  · Glyphs · Pipelines        [on]
  · Glyphs · Refineries       [off]
  · Glyphs · Datacenters      [on]
  · Glyphs · EONET            [on]
  · Glyphs · GDACS            [off]
  · Glyphs · Hotspots         [on]
D · lens & chrome             (auto)
```

Group A bleibt anzeigend, aber nicht klickbar. Group D zeigt aktuellen Spotlight-Status (z.B. „pin · sinjar" oder „country · grc" oder „idle"), nicht toggle-bar.

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

- **Default state:** vector — solid `--obsidian` fill für alle Tiles, kein Imagery-Provider.
- **Spotlight state:** in der Spotlight-Region wird Photographic-Imagery (NASA Black Marble nightly + optional Sentinel-2 daytime composite) geclippt. Außerhalb bleibt vector.
- **Render:** Cesium `globe.material` mit custom GLSL-Shader, der per Frame ein Mask-Texture aus `spotlight.shape` konsumiert. Bei `kind=circle` ist die Mask ein Radial Gradient; bei `kind=country` ist es ein gerasteriertes Polygon (admin-0 GeoJSON pre-baked nach 4096×4096 R8 Texture mit einem Feathering-Pass).
- **Tokens:** vector fill `--obsidian` · imagery raw (Black Marble: warm orange/yellow city lights baked in).

### §3.4 Layer 03 · Graticule

- **Geometry:** 10° Lat/Long-Linien, clipped to globe sphere.
- **Render:** `PolylineCollection` als single batch, GPU-instanced.
- **Tokens:** `--graticule` (color-mix --granite 80% --steel 20%) · 0.4 px stroke.
- **Motion:** rotiert mit dem Globe (kein eigenständiges Layer im Welt-Koordinatensystem).

### §3.5 Layer 04 · Country Borders

- **Geometry source:** Natural Earth admin-0 polygons, level 1:50m für Performance.
- **Render:** `PolylineCollection` single batch.
- **Tokens:** `--stone` 0.6 px. Disputed/de-facto Borders dashed 4-2.
- **Hit-testing:** Polygon-Hit-Test für Layer 08 country-click trigger lebt in dieser Layer (siehe §4.4).

### §3.6 Layer 05 · Hydrography

- **Geometry source:** Natural Earth coastline (subset) + rivers level 1 (Major rivers only — Nile, Amazon, Mississippi, etc. — nicht alle).
- **Render:** `PolylineCollection` single batch.
- **Tokens:** `--ash` 0.4 px · alpha 0.7. Bewusst sehr subtil.

### §3.7 Layer 06 · Network Mesh

- **Geometry sources** (multi):
  - Submarine cables (already integrated · `CableLayer`)
  - Pipeline network (already integrated · `PipelineLayer`)
  - Aktive Routes — flight tracks ant-trail (max 1 hervorgehoben, Rest grau)
  - Comm-Links (Satellites: `SatelliteLayer` orbits)
- **Render:** `PolylineCollection` pro Source, sub-tinted. Nodes als kleine Billboard-Punkte (1.5 px radius).
- **Tokens:** `--mesh-line` (color-mix --amber 60% transparent) · 0.5 px · 0.55 alpha.
- **Single active route:** ant-trail via `stroke-dashoffset` Animation, 8 s linear.

### §3.8 Layer 07 · Event Glyphs

- **Geometry sources** (alle 14 existierenden Data-Layers): UCDP · FIRMS · Mil-air · Satellites · Earthquakes · Cables (event-mode) · Vessels · CCTV · Pipelines (event-mode) · Refineries · Datacenters · EONET · GDACS · Hotspots.
- **Render:** **Single** `BillboardCollection` für alle Glyphs gemeinsam. Jeder Glyph hat einen pre-rendered Sprite-Atlas mit den vier Familien-Marken:
  - **Sentinel pulse** (`--sentinel`) — incidents, threats: roter Punkt + radiale Pulse-Welle
  - **Amber triangle** (`--amber`) — armed conflict events, alerts
  - **Stone square** (`--stone`) — infrastructure (refineries, datacenters)
  - **Sage ring** (`--sage`) — atmospheric / earth observation (FIRMS, EONET, GDACS)
- **Mapping** (existing data → glyph family):
  - UCDP → amber triangle
  - FIRMS → sage ring
  - Mil-air → amber triangle
  - Satellites → stone square (orbit endpoints)
  - Earthquakes → sentinel pulse
  - Cables incidents → sentinel pulse
  - Vessels → stone square
  - CCTV → stone square
  - Pipelines incidents → sentinel pulse
  - Refineries → stone square
  - Datacenters → stone square
  - EONET → sage ring
  - GDACS → sentinel pulse
  - Hotspots → sage ring

### §3.9 Layer 08 · Spotlight (polymorphic)

Der zentrale Reveal-Mechanismus. Polymorph in `kind`.

#### `kind = 'circle'`
- Trigger sources: zoom, pin-click, search-match (siehe §4.1–4.3).
- Shape: Kreis um eine Koordinate, default radius ~1° (≈ 100 km am Äquator), abhängig vom Zoom-Level.
- Render: PostProcess Stage mit Radial-Mask. Photographic-Imagery (Black Marble) gemischt mit Vector-Untergrund über mask alpha.
- Chrome (Layer 09a · Cartouche): Coordinate-Cartouche `name · 36.34N · 41.87E · § <ref>`.

#### `kind = 'country'`
- Trigger source: country-click auf Globe-Surface (Point-in-Polygon-Test gegen Layer 04 admin-0).
- Shape: admin-0 Polygon des angeklickten Landes.
- Render: PostProcess Stage mit Polygon-Mask Texture (pre-baked nach R8 Texture, Feathering 1px).
- Imagery layering im Polygon:
  - Base: NASA Black Marble Nightly (city lights baked in)
  - Mask-Modulation: Ember-Radial-Gradients an Major Cities (GeoNames cities1000, top N=12 nach population)
  - Composite mode: screen
- Chrome:
  - **Capital pulse** (Sentinel-Rot, größer als reguläre Glyphs, mit zusätzlichem Outer-Ring) auf `capital.coords`.
  - **City labels** (yellow `#ffd07a`, Hanken Grotesk 11 px) auf top 5 cities.
  - **Multilingual cartouche** (Layer 09a) mit Endonyms aus Wikidata.
  - **Almanac-Panel** (siehe §5).

### §3.10 Layer 09a · Cartouche

DOM overlay. Adaptive an `spotlight.kind`.

| Kind | Render |
|---|---|
| `idle` | hidden |
| `circle` | Coordinate-Cartouche right-aligned an der Lens, weißer Instrument-Serif-Headline + Mono-Sub mit Coords/Höhe/Source |
| `country` | Greece-Style Multi-Language-Stack: 6–9 Endonyms in Hanken Grotesk light 11 px · ISO-Name in Hanken Grotesk light 96 px · Cyrillic-Variant (für Slavic-Speakers oder Kazakh) in `--amber` 34 px |

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
      polygon: GeoJSON.Polygon;
      capital: { name: string; coords: { lon: number; lat: number } };
      majorCities: { name: string; coords: { lon: number; lat: number }; pop: number }[];
    };
```

`focusTarget` lebt in einem React-Context (`SpotlightContext`) mit Reducer-Updates.

### §4.2 Triggers

| # | Trigger | Source | Action |
|---|---|---|---|
| 1 | Zoom | Camera height ≤ 500 km | dispatch `{kind:'circle', trigger:'zoom', center: cameraCenter, radius: f(altitude)}` |
| 2 | Pin click | Click on glyph (Layer 07) | dispatch `{kind:'circle', trigger:'pin', center: glyph.position, sourcePin: {...}}` |
| 3 | Search match | Match accepted in § Search | camera flyTo + dispatch `{kind:'circle', trigger:'search', center: matchCoord, label: matchName, ref: matchRef}` |
| 4 | Country click | Click on Layer 04 polygon (no glyph hit) | dispatch `{kind:'country', trigger:'country', iso3, polygon, capital, majorCities}` |

### §4.3 Conflict Resolution

**Last-writer wins.** Wenn der Nutzer schon einen Pin offen hat und dann ein Land klickt, ersetzt das Country-Spotlight das Pin-Spotlight. Der § Inspector schließt sich automatisch (er gehörte zum Pin-Trigger).

### §4.4 Hit-Testing Reihenfolge

Bei einem Click-Event auf den Globe:
1. Pick auf Layer 07 (Event Glyphs). Hit → `{trigger:'pin', ...}`.
2. Sonst: Pick auf Layer 04 (Country Borders / admin-0 polygon containing click point). Hit → `{trigger:'country', ...}`.
3. Sonst: ignore (no-op).

Der Point-in-Polygon-Test braucht eine räumliche Index-Struktur (RBush oder ähnlich) auf den admin-0 Polygons; sonst wird der Click-Hit-Test bei 250+ Polygons pro Click zu langsam. Wird im Implementation-Plan budgetiert.

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

## §5 Country Mode · Almanac Panel

### §5.1 Layout

Slide-in von rechts, 340 px breit, full-height, `background: rgba(8,7,5,.92)` + 1 px granite border-left + backdrop-blur 14px. Ersetzt im country-mode den § Inspector (gleicher Slot).

### §5.2 Sektions-Struktur

```
§ ALMANAC · GRC · BRIEF
─────────────────────
Hellenic Republic                       (Instrument Serif italic 22 px)
Ελληνική Δημοκρατία · iso · grc        (eyebrow)

CAPITAL    Athens · 37.98N 23.73E
AREA       131 957 km² · ranked 96
POP        10.34 M · density 78/km²
GDP        $ 248 B · ppp $ 405 B
GOVT       Parliamentary republic
HEAD       K. Mitsotakis · since 2019
MILITARY   NATO · 142 700 active
BORDERS    ALB · MKD · BGR · TUR
LANGS      Greek (official)
CURRENCY   EUR · €

§ CONTEXT · 2 SENTENCES
[2-Satz editorial brief, Instrument Serif italic]

§ ACTIVE INTEL · ODIN GRAPH
● UCDP · Aegean tension              § 042
○ FIRMS · 0 hotspots                 24h
● Submarine cable · EAGLE-1          live
● Mil-air · NATO-SOU                 3 trk

▸ read full dossier
▸ ask Munin about <country>
▸ filter ticker · <iso3> only
▸ esc · close spotlight
```

### §5.3 Datenquellen

| Sektion | Quelle | Refresh |
|---|---|---|
| Static facts (capital, area, pop, GDP, govt, head, military, langs, currency, borders, ISO codes, endonyms) | REST Countries (`restcountries.com`) + Wikidata SPARQL fallback | täglich · cached lokal als `services/data-ingestion/feeds/country_almanac/` snapshot |
| Endonyms / Multilingual cartouche | Wikidata `P1448` (official name) + `P2019` (spoken native name) per language code | täglich |
| §Context narrative (2 sentences) | Pre-generated by Munin agent · stored in `country_brief.country_iso3` Neo4j node, regen weekly | weekly |
| §Active intel pulses | Live Neo4j queries scoped to `country = iso3`: UCDP active conflicts, FIRMS hotspot count, Cable incidents, Mil-air recent tracks | per Spotlight-Open |

### §5.4 Capital Pulse (Layer 08, country-mode)

- Position: `capital.coords` aus REST Countries.
- Visual: 6 px solid `#e63a26` (Sentinel-Rot) + Outer-Ring 14 px `rgba(230,58,38,.5)` 1 px stroke + Glow 14 px box-shadow.
- City Label: `Hanken Grotesk 11 px · #ffd07a · text-shadow 0 0 4px black` rechts vom Pulse.
- Größere Sichtbarkeit als reguläre Glyphs (Layer 07), damit das Capital sofort heraussticht.

### §5.5 City Labels

- Top 5 cities nach population (ohne Capital, der hat seinen eigenen Pulse).
- `Hanken Grotesk 11 px · #ffd07a · text-shadow 0 0 4px black`.
- Position: 4 px rechts vom City-Center, vertikal zentriert.
- Render: DOM Overlay (nicht Cesium Label) für besseres Text-Rendering.

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
| § Layers | Inhalt wird *neu strukturiert* nach den 4 Gruppen (A · Sky / B · Earth / C · Signal / D · Lens & Chrome). Group A nicht-toggle-bar (deaktiviert), Group D zeigt Spotlight-Status statt Toggles. |
| § Search | Match-Acceptance triggert 3. Spotlight-Trigger (siehe §4.2). |
| § Inspector | Im pin-mode unverändert. Im country-mode **versteckt** — wird durch Almanac-Panel (§5) im selben Slot ersetzt. ESC schließt beides. |
| § Ticker | Unverändert. Click auf Ticker-Item triggert internen `focusTarget`-Dispatch (`circle` mit Item-Coords). |

---

## §9 Data Dependencies

| Source | Use | Existing? | Action für S2 |
|---|---|---|---|
| Natural Earth admin-0 1:50m | Layer 04 Borders + Layer 08 country polygon hit-test | Existing in repo | Verify, ggf. neu importieren als optimierten GeoJSON |
| Natural Earth coastline + rivers L1 | Layer 05 Hydrography | Existing | Same |
| NASA Black Marble nightly | Layer 02 Spotlight imagery (circle + country) | Not yet integrated | Add Cesium ImageryProvider, cached tiles |
| Sentinel-2 daytime composite (optional) | Layer 02 day-mode (out-of-scope für S2) | Not yet integrated | Out of scope · S2.5 oder S3 |
| GeoNames cities1000 | Layer 08 country-mode population centers | Not yet integrated | Static asset, ~5 MB JSON nach `services/frontend/public/geo/cities.json` |
| REST Countries | Almanac static facts | Not yet integrated | Add ingestion job in `data-ingestion/feeds/country_almanac/` (täglich) → Neo4j `Country` nodes |
| Wikidata SPARQL | Endonyms (multilingual cartouche) + Capital coordinates | Not yet integrated | Same ingestion job |
| Munin agent | Almanac §Context 2-sentence brief | Existing | New scheduled job: weekly regenerate per country → Neo4j `Country.brief` |
| Neo4j `Country` node + relationships | Almanac §Active intel pulses | Partially existing (some entities have `country` property) | New: ensure all event types tag `country` consistently · add `Country` label + index |

---

## §10 Cesium Implementation Notes

### §10.1 Pflicht-Patterns aus CLAUDE.md

- **BillboardCollection**, nicht Entity-API für Bulk-Rendering.
- **CallbackProperty** für smooth tracking ohne React re-renders.
- **PostProcessStage** mit Custom GLSL für Spotlight-Mask.
- Async cleanup mit `if (viewer.isDestroyed()) return;` guard (siehe S2-Backlog `project_s2_worldview_backlog.md`).

### §10.2 Spotlight Mask Texture-Pipeline

Für `kind = 'country'`:

1. Auf Country-Click: hol GeoJSON Polygon aus admin-0 Spatial-Index (vorgefertigt beim App-Boot).
2. Renderer rendert Polygon in eine Off-Screen-Canvas (4096×4096 R8) — schwarz=außerhalb, weiß=innerhalb, Feathering 1 px.
3. Texture wird als WebGL-Sampler in `globe.material` gepustet.
4. Custom GLSL Shader im `globe.material` mischt Vector-Background mit Black-Marble-Imagery via `mask alpha`.
5. Auto-Cleanup beim Spotlight-Exit (Texture dispose, Mask-Alpha → 0).

### §10.3 Spatial Index für Country-Click

- Beim App-Boot: lade `admin-0.geojson` einmal, baue R-Tree (rbush) mit Bounding-Boxes.
- Click-Hit-Test: Pick `cartesian → cartographic`, check rbush für candidate polygons, dann Point-in-Polygon-Test (turf.js `booleanPointInPolygon`).
- Erwartete Latenz: < 5 ms pro Click bei ~250 polygons.

### §10.4 Bestehende Layer-Migration

Existing Cesium-Layer-Dateien in `services/frontend/src/components/layers/*.tsx` werden zu Layer 07 Event Glyphs konsolidiert:

- Vor S2: 14 separate `BillboardCollection` (eine pro Layer-Datei).
- Nach S2: **eine** `BillboardCollection` mit allen Glyphs, gefüttert aus den existierenden Hooks (`useFlights`, `useSatellites`, `useEarthquakes`, …) über einen neuen `useGlyphMerger` Hook der aus allen Quellen einen flat-array-Stream merged.

Bestehende Per-Layer-Toggle-Logik bleibt erhalten — sie wird zu Filter-Pred über den merged Stream.

---

## §11 Open Questions / Out-of-Scope

### §11.1 Out of Scope für S2

- **Sentinel-2 daytime imagery composite** — nice-to-have, aber Black Marble allein deckt den Forensic-Aesthetic. Verschoben auf S2.5 oder später.
- **Disputed-territory rendering policy** — z.B. wie wird Western Sahara, Crimea, Taiwan dargestellt? Aktuell: Natural Earth admin-0 default. Editorial-Entscheidung später.
- **Animated time-slider** — Globe als statischer Snapshot der „jetzt"-State; Zeitachse als Feature für War Room (S4).
- **Country-zu-Country Comparison-Mode** — Multi-select Spotlight ist Future Work.

### §11.2 Offene Fragen

1. **Almanac §Context generation:** sollen die 2-Satz-Briefs durch Munin auf-Klick (on-demand) generiert werden oder weekly batch + cached? Empfehlung: weekly batch + cached, mit „regenerate" Button im Almanac für stale briefs (> 14 Tage).
2. **Multilingual cartouche language pool:** statisch (immer dieselben 7 Sprachen pro Country) oder dynamisch (top 7 Sprecher-Sprachen aus dem CIA-World-Factbook „Languages")? Empfehlung: dynamisch, mit Fallback auf einen festen Set für Sprachen die wenig Sprecher haben (Esperanto, Lateinisch, Sanskrit für „klassische" Anker).
3. **GeoNames cities1000 license:** 5 MB Asset im Frontend-Bundle akzeptabel oder lieber Backend-Endpunkt? Empfehlung: Backend-Endpunkt, wird beim Country-Click nachgeladen (~ 200 KB pro country).

Diese drei werden im Implementation-Plan addressed (oder explizit deferred).

---

## §12 Test Surface

### §12.1 Unit / Component Tests

- `SpotlightContext` reducer: alle Trigger-Übergänge (idle → kind-A → kind-B → idle) decken.
- `useGlyphMerger`: alle 14 Sources gemerged, nur enabled Sources sichtbar.
- Country-click hit-test: gegeben (lon, lat) → korrektes ISO-3 (Test-Daten: 10 known coordinates spanning continents).
- Almanac-Panel: gegeben `iso3 = 'GRC'` → all expected fields rendered, missing-data fallback graceful.

### §12.2 Visual Regression

Drei Pflicht-Snapshots:
- Idle Worldview (no spotlight).
- Pin-mode (Sinjar example).
- Country-mode (Greece example, exakt gleich wie der Reference-Frame).

Tooling: Playwright + percy.io oder lokale pixel-diff.

### §12.3 Performance

- Cesium FPS counter aktiv halten in Dev-Mode.
- Lighthouse audit auf `/worldview` mit allen Layers on: ≥ 55 FPS bei Kamera-Rotation.

---

## §13 Mapping zu existierender Codebase

Nach S2-Port ergibt sich folgende File-Struktur:

```
services/frontend/src/
├── theme/hlidskjalf.css                    # erweitert mit §6 Token-Delta
├── components/
│   ├── pages/WorldviewPage.tsx             # ersetzt App.tsx (siehe project_s2_worldview_backlog.md)
│   ├── globe/
│   │   ├── GlobeViewer.tsx                 # Cesium Viewer + skyBox + skyAtmosphere setup
│   │   ├── layers/
│   │   │   ├── Graticule.tsx               # Layer 03
│   │   │   ├── CountryBorders.tsx          # Layer 04 (mit hit-test)
│   │   │   ├── Hydrography.tsx             # Layer 05
│   │   │   ├── NetworkMesh.tsx             # Layer 06 (konsolidiert Cables, Pipelines, Routes)
│   │   │   └── EventGlyphs.tsx             # Layer 07 (konsolidiert alle 14 Sources)
│   │   ├── spotlight/
│   │   │   ├── SpotlightContext.tsx        # focusTarget Reducer
│   │   │   ├── SpotlightShader.glsl        # Layer 08 PostProcess
│   │   │   ├── SpotlightOverlay.tsx        # Layer 09a Cartouche
│   │   │   ├── HudFrame.tsx                # Layer 09b
│   │   │   └── AlmanacPanel.tsx            # §5 country-mode panel
│   │   └── hooks/
│   │       ├── useGlyphMerger.ts
│   │       ├── useCountryHitTest.ts
│   │       └── useSpotlightTrigger.ts
│   └── layers/                             # alte Per-Source-Komponenten — werden zu Hooks
│       └── (entfernt nach Konsolidierung)
└── public/geo/
    ├── admin-0.geojson                     # Natural Earth 1:50m
    ├── coastline.geojson                   # Natural Earth coastline
    └── rivers-l1.geojson

services/data-ingestion/feeds/country_almanac/
├── __init__.py
├── rest_countries_collector.py             # täglich REST Countries → Neo4j Country nodes
├── wikidata_endonyms.py                    # täglich Wikidata SPARQL → Country.endonyms
└── munin_brief_generator.py                # weekly Munin → Country.brief
```

---

## §14 Akzeptanzkriterien für S2-Worldview-Port (relevant für dieses Spec)

- [ ] Layer-Stack 00–09b implementiert mit den oben dokumentierten Render-Strategies.
- [ ] § Layers Panel zeigt die 4-Gruppen-Struktur, Group A nicht-toggle-bar, Group D zeigt Spotlight-Status.
- [ ] Vier Trigger funktionieren: zoom (camera ≤ 500 km), pin click (Layer 07), search match, country click (Layer 04 hit-test).
- [ ] `focusTarget` Reducer ist last-writer-wins, ESC räumt auf.
- [ ] Country-mode lädt Almanac-Panel mit static (REST Countries) + dynamic (Neo4j) Daten.
- [ ] Capital-Pulse + 5 City-Labels + Multilingual Cartouche im Country-mode.
- [ ] ≥ 55 FPS Kamera-Rotation bei allen Layers on, 1080p.
- [ ] Reduced-motion: alle Animationen schalten korrekt um (verifiziert via DevTools `prefers-reduced-motion`).
- [ ] Visual-Regression-Snapshots für Idle, Pin-Mode (Sinjar), Country-Mode (Greece) bestanden.
- [ ] Existing 14 Cesium-Layer-Komponenten in `services/frontend/src/components/layers/*.tsx` zu Layer 07 konsolidiert.

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
