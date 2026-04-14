# ODIN — 4-Layer App Restructure · Hlíðskjalf Noir

**Datum:** 2026-04-14
**Status:** Design approved · pending implementation plan
**Scope:** Frontend-Restrukturierung von Single-Globe-App → 4 dedizierte Ansichten mit kohärenter Design-Sprache

---

## 1 · Motivation

Die aktuelle ODIN-Oberfläche ist ein einzelner CesiumJS-Globe. Mit Hugin (Ingestion Engine), Qdrant + Neo4j (Knowledge Graph) und dem Intelligence-Service (LangGraph ReAct Agent) entsteht Wert jenseits von Situational Awareness — nämlich **Analysen und Berichte**. Eine Ein-Ansicht-App zwingt Analyse-Workflows in die Globe-Chrome hinein und verschenkt Bildschirm-Real-Estate für Deep-Work.

Die Restrukturierung trennt vier Aufgaben-Modi in eigene Ansichten und bindet sie durch eine gemeinsame Design-Sprache (**Hlíðskjalf Noir**) visuell zusammen.

## 2 · Ästhetik · Hlíðskjalf Noir

Nordic Brutalism × Astronomical Geometry. Eine Oberfläche, die sich wie ein deklassifiziertes Lagedokument liest — mit der editorialen Ruhe einer Zeitschrift und der Präzision eines Messinstruments.

### 2.1 Palette

| Rolle | Token | Hex |
|---|---|---|
| Hintergrund tief | `--void` | `#0b0a08` |
| Hintergrund Panel | `--obsidian` | `#12110e` |
| Hintergrund Card | `--basalt` | `#1a1814` |
| Rahmen / Hair-line | `--granite` | `#2a2720` |
| Text schwach | `--ash` | `#6b6358` |
| Text sekundär | `--stone` | `#958a7a` |
| Text primär | `--bone` | `#d4cdc0` |
| Text Headline | `--parchment` | `#e8e2d4` |
| Akzent Hugin | `--amber` | `#c4813a` |
| Akzent Munin | `--sage` | `#7a8a68` |
| Akzent Sentinel | `--sentinel` | `#b85a2a` |
| Akzent Critical | `--rust` | `#8a4a3a` |

Nur *ein* Akzent pro Kontext. Rot-Orange (Sentinel/Rust) ist reserviert für aktive Incidents und Alerts.

### 2.2 Typografie

| Rolle | Familie | Verwendung |
|---|---|---|
| Display | **Instrument Serif** (italic 400/700) | Alle Headlines, Report-Titel, Zahlen-Hero, Agent-Antworten — immer kursiv |
| Body | **Hanken Grotesk** (300/400/500/600) | UI-Labels, Navigation, Body-Text außerhalb von Reports |
| Mono | **Martian Mono** (300/400/500) | Koordinaten, IDs, Timestamps, Tool-Calls, Metriken |

`font-feature-settings: 'ss01', 'cv01'` wo anwendbar. Instrument Serif italic ist Signatur; wo Serif in Aufrecht auftaucht, ist es ein Signal für etwas technisches (Code, Pfade).

### 2.3 Grain + Geometrie

- **Grain-Overlay** via inline SVG (`feTurbulence`, baseFrequency 0.9, 2 Oktaven) mit `mix-blend-mode: screen`, Opazität 0.45–0.6. Pro Panel-Root eingeblendet.
- **Hair-lines** (1 px `--granite`) statt Kästen; keine `border-radius` außer bei runden Orrery-Elementen.
- **§-Paragraphen-Nummerierung** (§I, §II, § 044) als Sprache — jede Sektion, jeder Report hat eine Nummer.
- **Orrery** ist die Marke (siehe 2.5).

### 2.4 Motion

Sparsam, präzise, niemals dekorativ.

- **Orrery** läuft kontinuierlich (rAF, siehe 2.5).
- **Incident-Marker** pulsieren (Sentinel-Orange, 1.4 s ease-in-out, 0.5 → 1.0 Opazität).
- **Page-Load** der Landing: gestaffeltes Reveal der vier Zahlen (120 ms Delay, Instrument Serif von 98%→100% Opazität + 2 px Y-Versatz).
- Keine Hover-Animationen auf Routinelinks. Buttons bekommen ein 1-Frame-Amber-Flash beim Klick, sonst nichts.

### 2.5 Orrery (Marken-Signatur)

Animiertes SVG-Element, eigenständig einsetzbar in drei Größen (S 40 px · M 110 px · L 220 px).

- **Drei elliptische Umlaufbahnen** um einen Amber-Kern:
  - Hugin: `rx=50, ry=18, tilt=-12°, ω=+0.35 rad/s` · Amber-Körper
  - Munin: `rx=38, ry=14, tilt=+25°, ω=-0.52 rad/s` · Sage-Körper
  - Sentinel: `rx=26, ry=10, tilt=-4°, ω=+0.78 rad/s` · Sentinel-Körper
- **Depth-Simulation** via `opacity = 0.35 + depth·0.65` und `scale = 0.7 + depth·0.5`, wo `depth = (sin(t)+1)/2` — vordere Hälfte der Ellipse erscheint größer und heller.
- **Kein Three.js.** Ein inline-Script mit `requestAnimationFrame` animiert alle Orreries gleichzeitig. Zielgröße < 5 kB minified, null Dependencies.
- Kann animiert oder statisch (bei `prefers-reduced-motion: reduce`) gerendert werden.

## 3 · Navigation

**Persistente Top-Bar**, 48 px hoch, immer sichtbar.

```
┌─────────────────────────────────────────────────────────────────────────┐
│ ⊙ Hlíðskjálf       HOME  WORLDVIEW  BRIEFING  WAR ROOM    14·IV / 16:42Z │
└─────────────────────────────────────────────────────────────────────────┘
```

- Links: Orrery-Marke (S) + Wordmark "Hlíðskjálf" in Instrument Serif italic.
- Mitte: 4 Tabs, Label in Hanken Grotesk uppercase, 0.22em letter-spacing. Aktiver Tab: Parchment + 5 px Amber-Dot vorangestellt. Im War Room: Dot pulsiert in Sentinel-Orange wenn ein Incident aktiv ist.
- Rechts: Timestamp + grobe Location in Martian Mono.
- Ergänzend: `⌘K` öffnet Command-Palette (Schnellsprung zu Berichten, Entities, Filtern). Nicht in Sprint 1 erforderlich.

## 4 · Seiten

### 4.1 Landing · Astrolabe

**Zweck:** Command Center beim Session-Start. "Was ist seit gestern passiert?" in zehn Sekunden beantwortbar.

**Layout:**
```
┌── Top-Bar ────────────────────────────────────────────────────────┐
│   Index Rerum · last 24h                               corr 0.84  │
│   ┌────────┐  ┌────────┐  ┌────────┐  ┌────────┐                 │
│   │  187   │  │   44   │  │   28   │  │   12   │                 │
│   │Hotspots│  │Conflict│  │ Nuntii │  │  Libri │                 │
│   └────────┘  └────────┘  └────────┘  └────────┘                 │
│   ──────────────────────────────────────────────                 │
│   § Signal Feed · live              ┌────────────┐               │
│   ● 14:32Z  sinjar cluster         │            │               │
│   ● 13:58Z  tu-95 barents          │   orrery   │               │
│   ● 13:12Z  ucdp·#44821            │   (110px)  │               │
│   ● 12:44Z  celestrak tle          └────────────┘               │
└──────────────────────────────────────────────────────────────────┘
```

**Komponenten:**
- **Hero-Numerals:** Vier große Instrument-Serif-Kursiv-Zahlen (58 px), Latinisierte Labels (Hotspots / Conflictus / Nuntii / Libri), Sentinel / Amber / Sage / Parchment. Darunter pro Tile: Mono-Diff (`▲ 12%`) + kurze Quelle.
- **Signal Feed:** Live-Liste der neuesten Ingestion-Events (letzte 6), gestreamt via SSE vom Backend. Zeit in Martian Mono, Event-Typ in Farbe, Ort als Text.
- **Orrery M** rechts unten als ruhiger Anker.
- Klick auf ein Numeral → Worldview mit vorgewähltem Filter. Klick auf Feed-Item → Entity-Inspector in Worldview.

**Page-Load-Animation:** Numerals staffeln sich ein (0 / 120 / 240 / 360 ms Delay). Orrery startet nach 500 ms. Feed-Items erscheinen einzeln mit 80 ms Offset.

### 4.2 Worldview

**Zweck:** Situational Awareness. Der Globe ist die Wahrheit — alles andere ist Chrome.

**Layout:** Vollflächiger CesiumJS-Globe, halbtransparente Dossier-Panels als Overlay.

**Overlay-Panels (alle wegklappbar, je 320 px breit):**
- **§ Layers** (top-left) — Layer-Toggle-Liste, gruppiert nach Dimension (Incidents / Infrastructure / Transport / Atmosphere). Aktive Layer werden mit Amber-Dot markiert.
- **§ Search** (top-right, fokussierbar mit `/`) — Entity-Search (Orte, UCDP-IDs, NORAD-IDs). Mit Auto-Complete.
- **§ Inspector** (rechts, slide-in bei Entity-Klick) — Zeigt Entity-Details aus Neo4j + zugehörige Reports + "Ask Hugin about this".
- **§ Ticker** (bottom-left) — Vertikaler Live-Feed, identisch zum Landing-Feed.

**Panel-Stil:** `background: rgba(18,17,14,0.84)` + 1 px Granite-Border + Backdrop-Blur 12px. Hair-line-Trenner zwischen Sub-Sektionen. Jedes Panel hat eine kleine `§`-Nummer und einen Close-Button in der Ecke.

**Marker-Stile auf dem Globe:**
- Hotspots (FIRMS): kleine Sentinel-Punkte mit Glow
- Konflikte (UCDP): Amber-Dreiecke
- Militärflüge: Sage-Umrandung
- Infrastruktur: Stone-Quadrate

Cesium-Primitives (BillboardCollection), nicht Entity-API, conformant zu bestehenden Projekt-Regeln.

### 4.3 Briefing Room

**Zweck:** Asynchrone Tiefenanalyse. Reports sind das Produkt.

**Layout (drei Spalten):**
```
┌─── Index (220px) ──┬─────── Dossier (flex) ─────────┬─── Hugin (300px) ───┐
│ § 044 · Sinjar     │ § 044 · Kurdistan · Escalation │ § Hugin · agent    │
│ § 043 · Barents    │ [Header · Findings · Numbers]  │ [You]              │
│ § 042 · Taiwan     │ ──────────────────────────────│ Cross-border...?   │
│ § 041 · Red Sea    │ [Body (editorial, on demand)]  │ [Hugin]            │
│ ...                │ [Margin · Sources]             │ Negative on...     │
│                    │                                │                    │
│                    │                                │ ┌────────────────┐ │
│                    │                                │ │ ask about this…│ │
│                    │                                │ └────────────────┘ │
└────────────────────┴────────────────────────────────┴────────────────────┘
```

#### 4.3.1 Index (linke Spalte)

Vertikale Liste aller Reports, neueste zuerst. Pro Eintrag:
- `§ 044 · 14·IV` (Martian Mono, Ash)
- Titel in Instrument Serif italic 11 px
- Aktiver Report bekommt 2 px Amber-Linksrand und Parchment-Titelfarbe

Oben ein Filter-Feld (`▸ filter / search`) — filtert nach Datum, Entity, Confidence, Status (Draft / Published / Archived).

#### 4.3.2 Dossier (mittlere Spalte) · **Mischform-Report**

**Header-Teil (Operational) — immer sichtbar:**
- Section-Eyebrow `§ 044 · Draft · Conf 0.87` in Sentinel
- Report-Titel in Instrument Serif italic 20 px, zweizeilig erlaubt
- Sub-Meta `14·IV · Sinjar ridge · 36.34N 41.87E` in Ash Eyebrow
- Hair-line
- **§ Findings** · drei nummerierte Bullets (01, 02, 03), Martian-Mono-Nummer + Bone-Text
- Hair-line
- **Zahlen-Triptychon** · drei große Instrument-Serif-Kursiv-Zahlen (26 px) in je einer Akzentfarbe, jeweils mit Eyebrow-Label und Mono-Subtext (z. B. "σ · 4.2 km")
- Hair-line
- **§ Context** · ein kompakter Stone-Absatz (2–3 Sätze)
- Action-Zeile: `▸ Read full dossier  · ▸ Ask agent  · ▸ Promote to Worldview`

**Body-Teil (Editorial) — entfaltet beim Klick auf "Read full":**
- Großer Instrument-Serif-Kursiv-Titel (28 px, zweizeilig)
- Hair-line
- Zwei Spalten-Grid (Main 1fr / Margin 110 px):
  - Main: Instrument Serif italic 13 px, line-height 1.55, mehrere Absätze
  - Margin: `§ Margin` Eyebrow + Mono-Zahlen, darunter `§ Sources` mit Amber-Referenzen (`·firms·¹`, `·ucdp·²`)
- Embeddable: Globe-Mini-Map (400×240), Entity-Cards, Chart-Snippets

Body ist Scroll-Container innerhalb der mittleren Spalte. Sticky-Header bleibt sichtbar beim Scrollen.

#### 4.3.3 Hugin-Panel (rechte Spalte)

- **Chat-Messages** als Karten mit Basalt-Hintergrund und 2 px Linksrand:
  - Stone-Rand für User
  - Amber-Rand für Hugin
- Hugin-Antworten in Instrument Serif italic 12 px — nicht als Mono-Chat-Bubble.
- Inline-Zitate als `·src·¹` mit Amber-Farbe — Klick öffnet Quelle in einer Modal-Margin.
- **Eingabefeld** unten, sticky. Placeholder: `▸ ask about this section…` · `⌘↩` zum Senden.
- Chat ist **report-scoped** — jeder Report hat seinen eigenen Dialog, persistiert serverseitig.

**Agent-Backend:** Existierender `services/intelligence` Service (Port 8003), SSE-Stream.

#### 4.3.4 Neuer Report

Button `+ New Dossier` oben im Index öffnet einen leeren Report mit Hugin bereit für "Brief me on …". Hugin generiert initiales Header + Findings, User kann dann den Body entfalten und zur Publikation editieren.

### 4.4 War Room

**Zweck:** Live-Cockpit für aktive Incidents. OpenBB-Dichte, Hlíðskjalf-Ästhetik.

**Layout:**
```
┌── Top-Bar ────────────────────────────────────────────────────────┐
│ [INCIDENT·LIVE] Kurdistan · Thermal Escalation   conf 0.87  T+02:14│
├─────────────────────────┬─────────────────────────────────────────┤
│ §I · Theatre            │ §II · Timeline                           │
│ [Globe-Zoom auf Incident│ T+02:14  ● cluster expansion n=14→17    │
│  mit Layer-Overlay]     │ T+01:52  ● GDELT 4 articles             │
│                         │ T+01:08  ● UCDP severity HIGH           │
│                         │ T+00:00  ● Trigger · FIRMS threshold    │
├─────────────────────────┼─────────────────────────────────────────┤
│ §III · Hugin · stream   │ §IV · Raw · sources                     │
│ [tool] qdrant.search…   │ [FIRMS · 14 det.]  [UCDP · #44821]       │
│ → 12 hits ·0.71         │ [GDELT · 4 art.]   [AIS · anomaly]       │
│ § working hypothesis    │ ──────────────────────                  │
│ cluster signature…      │ ▸ Promote to dossier  · Silence · Ask   │
└─────────────────────────┴─────────────────────────────────────────┘
```

#### 4.4.1 Incident-Bar

Sichtbar nur bei aktivem Incident. Hintergrund: linear-gradient 90° von Sentinel-Tint (12% Alpha) nach transparent.
- `INCIDENT · LIVE` Tag (Sentinel-Border, Mono, Uppercase)
- Incident-Titel in Instrument Serif italic 16 px
- Meta-Zeile (Koordinaten + Confidence) in Martian Mono 9 px Stone
- Rechts: Clock `T+02:14:08` — **relativ zum Trigger**, nicht absolute Zeit.

Wenn mehrere Incidents aktiv: Bar wird zur Liste, neuester zuerst, andere eingeklappt mit Klick-to-expand.

#### 4.4.2 Quadranten

Alle vier gleichwertig, kein Primär-Panel. Feste Grid-Struktur: `grid-template-columns: 1.2fr 1fr; grid-template-rows: 1fr 1fr`.

- **§I · Theatre** — CesiumJS-Instanz (wiederverwendet aus Worldview-Code), auto-gezoomt auf Incident-Bbox + 20% Padding. Layer automatisch aktiviert basierend auf Incident-Typ. Pulsierende Marker für Primärsignale.
- **§II · Timeline** — Chronologische Event-Liste mit T-Zeit, Farb-Dot (Sentinel/Amber/Sage/Stone nach Severity), Instrument-Serif-Kursiv-Beschreibung. Baseline-Referenz als Ash-Eintrag ganz unten.
- **§III · Hugin · Agent Stream** — **Tool-Calls live sichtbar** in Martian Mono 9 px. Jede Zeile: `[T+hh:mm.ss] tool/→ <detail>`. Darunter Hair-line und eine "working hypothesis" in Instrument Serif italic 12 px, die Hugin kontinuierlich verfeinert (Websocket/SSE vom intelligence-Service).
- **§IV · Raw · Sources** — Quellen als Basalt-Karten (2×2 Grid). Pro Karte: Mono-Source-Tag in Akzentfarbe, Serif-Titel, Mono-Timestamp. Action-Zeile unten:
  - `▸ Promote to dossier` (Sentinel-underline) — erstellt neuen Briefing-Report, Findings + Zahlen-Triptychon aus Incident-State vorausgefüllt, Agent-Chat mit Incident-Kontext initialisiert.
  - `Silence alert` — markiert Incident als bestätigt-but-no-action
  - `Ask Hugin` — öffnet Free-Form-Prompt in §III

#### 4.4.3 Incident-Lifecycle

- **Trigger:** Backend detectet ein Muster (FIRMS-Cluster über Schwelle, UCDP-Severity-Change, AIS-Anomaly). Schreibt Incident in Neo4j + published auf SSE-Stream `/api/incidents/stream`.
- **Auto-routing:** Client öffnet War Room automatisch bei aktivem Incident *nur* wenn User bereits auf Home oder Worldview ist. Nicht während aktivem Briefing-Report.
- **Hugin startet automatisch** seinen Analyse-Lauf (streamed nach §III).
- **T-Zeit** zählt ab Trigger-Timestamp vom Backend.
- **Close:** Incident gilt als geschlossen nach manuellem Silence / Promote oder nach 24 h Inaktivität.

## 5 · Frontend-Architektur

### 5.1 Routing

React Router mit vier Top-Level-Routen:

| Pfad | Komponente |
|---|---|
| `/` | `<LandingPage />` |
| `/worldview` | `<WorldviewPage />` (inkl. Cesium-Instanz) |
| `/briefing` · `/briefing/:reportId` | `<BriefingPage />` |
| `/warroom` · `/warroom/:incidentId` | `<WarRoomPage />` |

### 5.2 Shared Shell

```
<AppShell>
  ├── <TopBar />              // Persistent über allen Routen
  └── <Outlet />              // Aktive Page
  (+ <OrreryContext />)       // Globaler State der Orrery-Animation (ein rAF-Loop für alle Instanzen)
</AppShell>
```

### 5.3 Komponentenbibliothek

Neues Verzeichnis `services/frontend/src/components/hlidskjalf/` mit primitiven UI-Bausteinen:

- `Orrery` (S/M/L) + `OrreryProvider` (singleton rAF-Loop)
- `SectionHeading` (`§ I`, `§ 044`, mit optionalem Hair-line)
- `Eyebrow`, `HairLine`, `NumericHero` (Instrument-Serif-Kursiv-Zahl mit Label + Diff)
- `DossierPanel` (Basalt-Karte mit optionaler Close-Action)
- `SignalFeedItem` (Dot + T-Zeit + Serif-Text)
- `AgentMessage` (User / Hugin Variant)
- `AgentStreamLine` (Mono-Tool-Call-Zeile)
- `IncidentBar`
- `GrainOverlay` (SVG-feTurbulence, preloaded)

Alle Komponenten sind Presentational, erhalten Daten via Props. Page-Komponenten orchestrieren State via existierende `hooks/` und `services/`.

### 5.4 Design-Tokens

Ein zentraler `src/theme/hlidskjalf.css`:
- CSS-Variablen aus Palette (Abschnitt 2.1)
- Font-Faces (lokal selbst-gehostet oder über Google Fonts; Entscheidung offen; Standard: Google Fonts mit `font-display: swap`)
- Utility-Klassen (`.eyebrow`, `.mono`, `.serif`, `.hair`, `.dim`, `.stone`, `.amb`, `.sage`, `.sent`, `.rust`)

Keine Tailwind-Migration erforderlich — pures CSS mit Variablen reicht für diese Ästhetik und bleibt stabil.

### 5.5 Zustand

- **Shared:** Aktueller Timestamp, aktive Incidents (SSE-gebunden), letzte N Signal-Events. Provider in `AppShell`.
- **Per-Page:** Lokal in Page-Komponenten (existierende Hooks wiederverwenden).
- **Briefing-Reports:** Persistierung via Backend (`/api/reports`, neuer Router). Chat-Historie pro Report in Neo4j als `(:Report)-[:HAS_MESSAGE]->(:Message)`.

### 5.6 Testing

- **Vitest + React Testing Library** für Komponenten, bestehendes Setup.
- Snapshot-Test für Orrery-SVG-Struktur (nicht Animation).
- Visual Regression via Playwright für die vier Page-Routen (Landing, Worldview leer, Briefing mit Mock-Report, WarRoom mit Mock-Incident) — neu einzuführen, optional in Sprint 2.

## 6 · Backend-Ergänzungen

Notwendig für die Umstellung, nicht Kernfokus dieser Spec:

- **`/api/reports`** · CRUD für Briefing-Reports (Neo4j-backed). Felder: id, §-Nummer, title, header-block, body-block, messages[], status, created/updated.
- **`/api/incidents/stream`** · SSE-Stream aktiver Incidents. Payload: id, type, trigger_ts, title, coords, severity, status.
- **`/api/signals/stream`** · SSE-Stream der letzten Ingestion-Events für Signal-Feed (Landing + Worldview-Ticker).
- **`services/intelligence`** · existiert, bleibt. Agent-Stream wird für War Room auf WebSocket (nicht SSE) umgestellt, weil bidirektional (User kann während des Streams Zwischenfragen stellen). Fallback SSE zulässig für v1.

## 7 · Sichtbarer Umgang mit Legacy

Die bestehende `App.tsx` wird zur Worldview-Page (Layout 4.2). Keine Globe-Logik wird neu geschrieben — nur das Chrome. Existierende Layer (flights, satellites, earthquakes, vessels, cables, hotspots, EONET, GDACS) werden als Toggle-Gruppen ins `§ Layers`-Panel übernommen.

## 8 · Scope-Grenzen

**In Scope:**
- Alle vier Seiten mit vollständigem Chrome und Hlíðskjalf-Ästhetik
- Orrery-Komponente, Shell, Top-Bar
- Landing-Data-Wiring aus bestehenden APIs
- Briefing-Room-Shell + Report-CRUD
- War-Room-Shell + Incident-Lifecycle (Trigger-Detection ist Backend-Arbeit, für die Frontend-Spec genügt: stream-consumer + UI)
- Hugin-Chat-Panel pro Report

**Out of Scope (Folge-Specs):**
- Command-Palette (`⌘K`)
- Playwright Visual-Regression
- Report-Publikation zu externen Zielen (PDF, Telegram)
- Multi-User / Rollen
- Mobile-Layout (Desktop-first, Breakpoint ≥ 1280 px)

## 9 · Success Criteria

1. Ein neuer User erkennt am Orrery + der Typografie in unter 2 s, dass alle vier Ansichten zu derselben App gehören.
2. "Was ist in den letzten 24 h passiert?" ist von der Landing-Page in unter 10 s beantwortet ohne Klick in eine andere Ansicht.
3. Ein Briefing-Report (Header + Body + 3 Quellen) lässt sich in unter 2 Minuten vom User verfassen bzw. mit Hugin generieren lassen.
4. Beim Eintritt eines Incidents wird der User aus Home/Worldview innerhalb von 5 s in den War Room geführt (mit Globe-Ausschnitt gezoomt und Hugin-Stream laufend); aus Briefing Room erscheint stattdessen eine Toast-Benachrichtigung, die auf Klick den War Room öffnet.
5. Kein Page-Reload nötig, um zwischen den vier Ansichten zu wechseln (Client-Side-Routing).
6. Alle Typographie lädt in unter 200 ms (lokale Fonts bevorzugt); Grain-Overlay hat keinen messbaren FPS-Impact auf den Globe.
