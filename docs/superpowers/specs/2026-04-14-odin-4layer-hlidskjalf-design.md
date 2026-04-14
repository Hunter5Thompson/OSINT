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
| Akzent Munin (Agent) | `--amber` | `#c4813a` |
| Akzent Hugin (Ingestion) | `--sage` | `#7a8a68` |
| Akzent Sentinel (Incident) | `--sentinel` | `#b85a2a` |
| Akzent Critical | `--rust` | `#8a4a3a` |

> **Naming:** Im Codebase ist **Hugin** bereits die Ingestion-Engine (RSS/GDELT/FIRMS/UCDP Collectors — „sieht, sammelt"). Der konversationelle ReAct-Agent heißt daher **Munin** (Memory/Erinnerung — „reasoned über Gespeichertes"). Odin schickt Hugin aus, um zu beobachten; er befragt Munin, um zu verstehen. Amber ist Munin zugeordnet, Sage dem Hugin-Feed.

Nur *ein* Akzent pro Kontext. Rot-Orange (Sentinel/Rust) ist reserviert für aktive Incidents und Alerts.

### 2.2 Typografie

| Rolle | Familie | Verwendung |
|---|---|---|
| Display | **Instrument Serif** (italic 400/700) | Alle Headlines, Report-Titel, Zahlen-Hero, Agent-Antworten — immer kursiv |
| Body | **Hanken Grotesk** (300/400/500/600) | UI-Labels, Navigation, Body-Text außerhalb von Reports |
| Mono | **Martian Mono** (300/400/500) | Koordinaten, IDs, Timestamps, Tool-Calls, Metriken |

`font-feature-settings: 'ss01', 'cv01'` wo anwendbar. Instrument Serif italic ist Signatur; wo Serif in Aufrecht auftaucht, ist es ein Signal für etwas technisches (Code, Pfade).

**Minimum font sizes für Text, der gelesen werden muss:**
- Instrument Serif: 11 px (Index-Einträge, kleinste Anwendung)
- Hanken Grotesk: 10 px (Eyebrows/Labels), 12 px (Body)
- Martian Mono: 10 px (absolutes Minimum — Timestamps, IDs, Tool-Calls). **Nichts unter 10 px darf lesbarer Inhalt sein**; reine Deko-Mono unter 10 px ist nicht zulässig, weil Martian Mono bei kleinen Größen schnell unlesbar wird.

**Ash (`#6b6358`) ist Deko-Only.** Auf Void-Hintergrund erreicht Ash nur ≈ 3.8:1 (unter WCAG AA 4.5:1 für Body-Text). Ash ist reserviert für:
- Eyebrows und Section-Labels (kurz, redundant mit visueller Hierarchie)
- Disabled-Zustand
- Ornamentale Timestamps neben Primärinhalt

Jeder lesbare Fließtext und jede Metrik nutzt mindestens **Stone (`#958a7a`, ≈ 6.5:1)** oder höher.

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

**`prefers-reduced-motion: reduce`** — global respektiert:
- Orrery rendert statisch (Körper auf `θ=π/3`, sichtbare Konstellation, keine rAF-Loop).
- Incident-Marker und War-Room-Tab-Dot pulsieren nicht; stattdessen permanente volle Opazität.
- Landing-Reveal entfällt; Numerals erscheinen direkt in Endposition.
- Amber-Flash bei Klick entfällt; Button-Zustand wechselt ohne Transition.

### 2.5 Orrery (Marken-Signatur)

Animiertes SVG-Element, eigenständig einsetzbar in drei Größen (S 40 px · M 110 px · L 220 px).

- **Drei elliptische Umlaufbahnen** um einen Amber-Kern:
  - Munin (Agent): `rx=50, ry=18, tilt=-12°, ω=+0.35 rad/s, φ=0` · Amber-Körper
  - Hugin (Ingestion): `rx=38, ry=14, tilt=+25°, ω=-0.52 rad/s, φ=2.1` · Sage-Körper
  - Sentinel (Incident): `rx=26, ry=10, tilt=-4°, ω=+0.78 rad/s, φ=4.2` · Sentinel-Körper
- **Pro-Körper-Depth** — jeder Körper hat seinen eigenen Orbital-Winkel `θᵢ = ωᵢ · t + φᵢ` und damit eigene Phase. `depthᵢ = (sin(θᵢ) + 1) / 2` → `opacityᵢ = 0.35 + depthᵢ·0.65`, `scaleᵢ = 0.7 + depthᵢ·0.5`. Die drei pulsieren **nicht synchron**; jeder folgt seiner Bahn unabhängig.
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
- **§ Layers** (top-left) — Layer-Toggle-Liste, gruppiert nach Dimension (Incidents / Infrastructure / Transport / Atmosphere). Aktive Layer werden mit Amber-Dot markiert. **Default: collapsed** (nur 32 px breite Tab-Leiste mit Icon sichtbar, Klick expandiert).
- **§ Search** (top-right, fokussierbar mit `/`) — Entity-Search (Orte, UCDP-IDs, NORAD-IDs). Mit Auto-Complete. **Default: collapsed**; wird beim Drücken von `/` geöffnet.
- **§ Inspector** (rechts, slide-in bei Entity-Klick) — Zeigt Entity-Details aus Neo4j + zugehörige Reports + "Ask Munin about this". **Default: hidden**, erscheint nur on-demand.
- **§ Ticker** (bottom-left) — Vertikaler Live-Feed, identisch zum Landing-Feed. **Default: expanded** (der Ticker ist der permanente situational-awareness Anker und rechtfertigt die Screen-Real-Estate; er nimmt nur ~280 px in der Höhe und verdeckt den Globe kaum).

Insgesamt ist beim Erstbesuch **nur der Ticker und die drei Tab-Leisten** sichtbar — der Globe bleibt zu ≥ 85% frei. User kann Panels via Tab-Klick oder Hotkey (`L` Layers, `/` Search) öffnen.

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
┌─── Index (220px) ──┬─────── Dossier (flex) ─────────┬─── Munin (300px) ───┐
│ § 044 · Sinjar     │ § 044 · Kurdistan · Escalation │ § Munin · agent    │
│ § 043 · Barents    │ [Header · Findings · Numbers]  │ [You]              │
│ § 042 · Taiwan     │ ──────────────────────────────│ Cross-border...?   │
│ § 041 · Red Sea    │ [Body (editorial, on demand)]  │ [Munin]            │
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

#### 4.3.3 Munin-Panel (rechte Spalte)

- **Chat-Messages** als Karten mit Basalt-Hintergrund und 2 px Linksrand:
  - Stone-Rand für User
  - Amber-Rand für Munin
- Munin-Antworten in Instrument Serif italic 12 px — nicht als Mono-Chat-Bubble.
- Inline-Zitate als `·src·¹` mit Amber-Farbe — Klick öffnet Quelle in einer Modal-Margin.
- **Eingabefeld** unten, sticky. Placeholder: `▸ ask Munin about this section…` · `⌘↩` zum Senden.
- Chat ist **report-scoped** — jeder Report hat seinen eigenen Dialog, persistiert serverseitig.

**Agent-Backend:** Existierender `services/intelligence` Service (Port 8003), SSE-Stream.

#### 4.3.4 Neuer Report

Button `+ New Dossier` oben im Index öffnet einen leeren Report mit Munin bereit für "Brief me on …". Munin generiert initiales Header + Findings, User kann dann den Body entfalten und zur Publikation editieren.

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
│ §III · Munin · stream   │ §IV · Raw · sources                     │
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
- Meta-Zeile (Koordinaten + Confidence) in Martian Mono 10 px Stone
- Rechts: Clock `T+02:14:08` — **relativ zum Trigger**, nicht absolute Zeit.

**Zwei Uhren, visuell differenziert:**
Die Top-Bar zeigt Absolutzeit (`14·IV / 16:42Z`) in Martian Mono 10 px **Ash**, rechts-bündig, kleine Schrift, dekorativ. Die Incident-Bar-Clock (`T+02:14:08`) nutzt Martian Mono 13 px **Sentinel**, mit sichtbarem `T+`-Prefix. Größer, farbig, mit Prefix — klar als *Incident-Counter* markiert. Der Kontrast in Größe (10 vs. 13 px) und Farbe (Ash vs. Sentinel) verhindert Verwechslung.

Wenn mehrere Incidents aktiv: Bar wird zur Liste, neuester zuerst, andere eingeklappt mit Klick-to-expand.

#### 4.4.2 Quadranten

Alle vier gleichwertig, kein Primär-Panel. Feste Grid-Struktur: `grid-template-columns: 1.2fr 1fr; grid-template-rows: 1fr 1fr`.

- **§I · Theatre** — CesiumJS-Instanz (wiederverwendet aus Worldview-Code), auto-gezoomt auf Incident-Bbox + 20% Padding. Layer automatisch aktiviert basierend auf Incident-Typ. Pulsierende Marker für Primärsignale.
- **§II · Timeline** — Chronologische Event-Liste mit T-Zeit, Farb-Dot (Sentinel/Amber/Sage/Stone nach Severity), Instrument-Serif-Kursiv-Beschreibung. Baseline-Referenz als Ash-Eintrag ganz unten.
- **§III · Munin · Agent Stream** — **Tool-Calls live sichtbar** in Martian Mono 10 px. Jede Zeile: `[T+hh:mm.ss] tool/→ <detail>`. Darunter Hair-line und eine "working hypothesis" in Instrument Serif italic 12 px, die Munin kontinuierlich verfeinert (Websocket/SSE vom intelligence-Service).
- **§IV · Raw · Sources** — Quellen als Basalt-Karten (2×2 Grid). Pro Karte: Mono-Source-Tag in Akzentfarbe, Serif-Titel, Mono-Timestamp. Action-Zeile unten:
  - `▸ Promote to dossier` (Sentinel-underline) — erstellt neuen Briefing-Report, Findings + Zahlen-Triptychon aus Incident-State vorausgefüllt, Agent-Chat mit Incident-Kontext initialisiert.
  - `Silence alert` — markiert Incident als bestätigt-but-no-action
  - `Ask Munin` — öffnet Free-Form-Prompt in §III

#### 4.4.3 Incident-Lifecycle

- **Trigger-Quelle:** Ein neuer Backend-Service `services/incident-detector` (Out of Scope für diese Spec — siehe §8) konsumiert die existierenden Ingestion-Feeds und detectet Muster. Für v1 ist dieser Service ein **Stub**, der Incidents manuell über eine interne REST-Admin-Route anlegen kann. Echte Detection (FIRMS-Cluster-Schwelle, UCDP-Severity-Change, AIS-Anomaly) ist eine eigene Folge-Spec. Frontend kennt nur den SSE-Consumer.
- **Trigger-Payload:** Incident wird in Neo4j geschrieben (via deterministische Cypher-Templates, kein LLM-generiertes Cypher — Projekt-Regel) und auf `/api/incidents/stream` published.
- **Notification-Pattern (alle Ansichten):** Wenn ein neuer Incident eintrifft, erscheint **oben rechts ein Sentinel-getönter Toast** mit Incident-Titel + Coords + `▸ Open War Room`-Button. Kein automatisches Navigieren. Der Toast bleibt 12 s sichtbar, danach verfügbar über den pulsierenden War-Room-Tab-Dot in der Top-Bar. Dieses Pattern ist in allen vier Ansichten identisch — kein Kontext-Bruch, keine aggressive Weiterleitung.
- **Munin startet automatisch** seinen Analyse-Lauf im Hintergrund (streamed nach §III, auch wenn der User den War Room noch nicht geöffnet hat).
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

**Migrations-Regel für bisherige Deep-Links:** Die Pre-Restructure-App war faktisch Globe-zentriert unter `/`. Damit existierende Bookmarks / Telegram-Links / externe Referenzen nicht brechen:
- Legacy-Patterns wie `/?entity=…` oder `/?layer=…` werden auf `/worldview?…` redirected (301 auf Server-Seite, `<Navigate replace>` client-seitig).
- Der Root-Pfad `/` zeigt aber künftig die Landing-Page. User ohne Query-Parameter landen dort — das ist bewusst, weil Landing das Command Center für Session-Start ist.
- Es gibt keine Legacy-Deep-Links für Briefing oder War Room (beide sind neu); keine Migration nötig.

**API-Prefix-Konvention:** **Alle Backend-Calls vom Frontend nutzen `/api/*`.** Kein gemischter Gebrauch. Jeder Stream-Endpoint, jede REST-Route. In Dokumenten, Error-State-Texten und Logs ist der vollständige Pfad inklusive `/api`-Prefix anzugeben.

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
- `AgentMessage` (User / Munin Variant)
- `AgentStreamLine` (Mono-Tool-Call-Zeile)
- `IncidentBar`
- `GrainOverlay` (SVG-feTurbulence, preloaded)

Alle Komponenten sind Presentational, erhalten Daten via Props. Page-Komponenten orchestrieren State via existierende `hooks/` und `services/`.

### 5.4 Design-Tokens

Ein zentraler `src/theme/hlidskjalf.css`:
- CSS-Variablen aus Palette (Abschnitt 2.1)
- **Font-Faces: selbst-gehostet.** WOFF2-Dateien unter `public/fonts/` mit `@font-face` + `font-display: swap`. Google Fonts ist nur Entwicklungs-Fallback. Grund: Offline-Betrieb möglich, keine externen Abhängigkeiten, < 200 ms Ladezeit aus Success Criterion #6 ist realistisch nur lokal.
- Utility-Klassen (`.eyebrow`, `.mono`, `.serif`, `.hair`, `.dim`, `.stone`, `.amb`, `.sage`, `.sent`, `.rust`)

Keine Tailwind-Migration erforderlich — pures CSS mit Variablen reicht für diese Ästhetik und bleibt stabil.

### 5.5 Zustand

- **Shared:** Aktueller Timestamp, aktive Incidents (SSE-gebunden), letzte N Signal-Events. Provider in `AppShell`.
- **Per-Page:** Lokal in Page-Komponenten (existierende Hooks wiederverwenden).
- **Briefing-Reports:** Persistierung via Backend (`/api/reports`, neuer Router). Chat-Historie pro Report in Neo4j als `(:Report)-[:HAS_MESSAGE]->(:Message)`.

### 5.6 Testing

- **Vitest + React Testing Library** für Komponenten, bestehendes Setup.
- Snapshot-Test für Orrery-SVG-Struktur (nicht Animation).
- **Visual Regression** (Playwright o.ä.) ist explizit Out of Scope für alle vier Sprints und Thema einer eigenen Folge-Spec. Manueller visueller Abgleich in Code-Review genügt bis dahin.

## 6 · Backend-Ergänzungen

Notwendig für die Umstellung, nicht Kernfokus dieser Spec:

- **`/api/reports`** · CRUD für Briefing-Reports. **Persistence via Neo4j-Cypher-Templates** (`services/backend/app/cypher/report_write.py`), keine LLM-generierten Queries (Projekt-Regel). Schema: `(:Report {id, paragraph_num, title, header_block, body_block, status, created_at, updated_at})-[:HAS_MESSAGE]->(:Message {id, role, text, ts})`. Templates sind parametrisiert und read-only für den Agent; nur das Backend schreibt.
- **`/api/incidents/stream`** · SSE-Stream aktiver Incidents. Payload: id, type, trigger_ts, title, coords, severity, status.
- **`/api/signals/stream`** · SSE-Stream der letzten Ingestion-Events für Signal-Feed (Landing + Worldview-Ticker).
- **`services/intelligence`** · existiert, bleibt. Agent-Stream wird für War Room auf WebSocket (nicht SSE) umgestellt, weil bidirektional (User kann während des Streams Zwischenfragen stellen). Fallback SSE zulässig für v1.

## 6.1 · Realtime-Contract (SSE/WS)

Alle Stream-Endpoints folgen einem gemeinsamen Event-Schema, damit Reconnect-Replay, Dedupe und Ordering klar sind.

**Event-Envelope (JSON pro Message):**
```json
{
  "event_id": "01J7Z8K2...",   // ULID, monoton steigend, global eindeutig
  "ts": "2026-04-14T16:42:03.482Z",
  "type": "incident.open" | "signal.firms" | "report.updated" | ...,
  "payload": { ... }
}
```

**SSE-spezifisch:**
- `id:`-Feld jedes SSE-Chunks enthält `event_id`.
- Client sendet beim Reconnect `Last-Event-ID`-Header. Server replay-t alle Events mit `event_id > last` aus einem **Ring-Buffer der letzten 15 Minuten**. Events älter als 15 min gelten als verloren — Client re-fetched Basis-Zustand (z. B. `/api/incidents` für aktive Incidents) und startet Stream neu.
- Ordering: **pro-Topic garantiert monoton**. Cross-Topic nicht garantiert.

**Client-Dedupe:**
- Signal-Feed und Incident-Liste halten ein `Set<event_id>` der letzten 500 IDs. Bereits gesehene IDs werden verworfen. Verhindert Duplikate nach Reconnect-Replay.

**WebSocket (Munin-Stream im War Room):**
- Gleiches Envelope. Reconnect mit `last_event_id` als erstem Client-→Server-Frame. Server schickt dann verpasste Events, danach live.
- Fallback auf SSE (`/api/munin/incidents/:id/stream`) falls WS nicht verfügbar.

**Abnahme dieses Contracts:** integration-tests in `services/backend/tests/streams/` simulieren: (a) Client verbindet, erhält N Events, disconnected, neu verbindet mit Last-Event-ID → erhält nur Events `>` last, in korrekter Reihenfolge, keine Duplikate; (b) Reconnect nach > 15 min erzwingt `reset`-Event.

## 6.2 · Error-States

Service-Ausfälle dürfen die App nicht weiß lassen. Konkrete Failure-Modes:

- **SSE-Drop (`/api/incidents/stream` oder `/api/signals/stream`)** — Client versucht Reconnect mit Exponential Backoff (1s, 2s, 4s, max 30s) und sendet beim Reconnect `Last-Event-ID` (siehe §6.1 Realtime-Contract) für Replay. Während der Reconnect-Phase zeigt der Signal-Feed einen Stone-Ash-State: `§ Signal · reconnecting…` in Eyebrow + spinnende Mini-Orrery (S-Größe). Keine destruktive Meldung.
- **Intelligence-Service (Munin) down** — Das Munin-Panel in Briefing / War Room zeigt: `§ Munin · silent.` in Instrument Serif italic 14 px Stone, darunter Mono-Detail `service unreachable · retry in {n}s`. Eingabefeld bleibt disabled mit Placeholder `▸ munin is resting`. Keine Fehlermeldung als Toast.
- **Report-Fetch-Fehler** — Briefing-Index zeigt stattdessen: `§ — · dossier archive unreachable` als einzigen Eintrag, darunter ein unauffälliger `▸ retry`-Link (Hanken Grotesk 10px Ash, Klick triggert Re-Fetch). Browser-Refresh (`F5` / `Ctrl+R` / `⌘R`) bleibt ebenfalls möglich.
- **Globe-Tile-Fehler (Cesium)** — Der existierende Cesium-Error-Handler bleibt zuständig; Overlay-Panels funktionieren weiter.
- **Worst-Case (alle Backends down)** — Landing zeigt die vier Numerals mit `—` in Parchment statt Zahlen, Eyebrow-Label mit `stale`-Tag. Die App bleibt navigierbar; nichts ist zerstört.

Alle Error-States folgen dem Ästhetik-Prinzip: **kein Rot, keine Shouting-Toasts, keine Icons**. Die Abwesenheit von Daten wird mit derselben Instrument-Serif-Ruhe kommuniziert wie die Anwesenheit.

## 7 · Sichtbarer Umgang mit Legacy

Die bestehende `App.tsx` wird zur Worldview-Page (Layout 4.2). Keine Globe-Logik wird neu geschrieben — nur das Chrome. Existierende Layer (flights, satellites, earthquakes, vessels, cables, hotspots, EONET, GDACS) werden als Toggle-Gruppen ins `§ Layers`-Panel übernommen.

## 8 · Scope-Grenzen

**In Scope:**
- Alle vier Seiten mit vollständigem Chrome und Hlíðskjalf-Ästhetik
- Orrery-Komponente, Shell, Top-Bar
- Landing-Data-Wiring aus bestehenden APIs
- Briefing-Room-Shell + Report-CRUD
- War-Room-Shell + Incident-Lifecycle (Trigger-Detection ist Backend-Arbeit, für die Frontend-Spec genügt: stream-consumer + UI)
- Munin-Chat-Panel pro Report

**Out of Scope (Folge-Specs):**
- **`services/incident-detector`** — echte Pattern-Detection auf Ingestion-Feeds (FIRMS-Cluster, UCDP-Delta, AIS-Anomaly). V1 nutzt einen Stub mit Admin-API für manuelle Incident-Erstellung.
- Command-Palette (`⌘K`)
- Playwright Visual-Regression
- Report-Publikation zu externen Zielen (PDF, Telegram)
- Multi-User / Rollen
- Mobile-Layout (Desktop-first, Breakpoint ≥ 1280 px)

## 8.1 · Sprint-Phasing

Die Umsetzung ist zu groß für einen Plan — Empfehlung: vier Sprints, jeder mit eigenem Implementierungsplan.

| Sprint | Ziel | Abhängigkeit |
|---|---|---|
| **S1 · Foundation** | Design-Tokens, Fonts self-hosted, Orrery-Komponente mit korrekter Physik, App-Shell + Top-Bar, Landing-Page mit echten Daten (Wiring zu `/api/signals/stream` + bestehenden Endpoints). Ästhetik ist danach *committed*. | keine |
| **S2 · Worldview-Port** | Existierende `App.tsx` wird `WorldviewPage`, Overlay-Panels (Layers / Search / Inspector / Ticker) ersetzen altes Chrome. Keine neue Globe-Logik. Bestehende Layer werden in die neue Panel-Struktur eingegliedert. | S1 |
| **S3 · Briefing Room** | `/api/reports` Backend-Router mit Cypher-Templates; Index + Dossier + Munin-Panel; Mischform-Report (Header + Editorial-Body); WebSocket-Upgrade für Munin-Stream optional. | S1 |
| **S4 · War Room** | Incident-Stream + Toast-Pattern (alle Ansichten), Incident-Bar, vier Quadranten, Promote-to-Dossier-Flow. Incident-Detector bleibt Stub mit Admin-API. | S2, S3 |

Jeder Sprint ist einzeln mergeable. Nach S1 + S2 ist die App visuell bereits umgezogen, auch ohne Analysefeatures. Nach S3 ist der primäre Value-Driver (Analyse) live.

## 9 · Success Criteria

Jedes Kriterium hat ein **Messprotokoll** — wie wird abgenommen.

1. **Visuelle Kohärenz.** *Nicht automatisiert messbar.* Abnahme via manueller Review: Dritter betrachtet Screenshots aller vier Ansichten nebeneinander und bestätigt ohne Erklärung, dass sie zur selben App gehören. Dokumentiert als Abnahme-Notiz im Sprint-Review.
2. **24-h-Awareness auf Landing.** Messprotokoll: Tester öffnet `/` kalt (Cache geleert), Stoppuhr läuft bis zur ersten gesprochenen Antwort auf "Was ist in den letzten 24 h passiert?". **Ziel: ≤ 10 s** (p95 über 5 Läufe). Ohne Tab-Wechsel.
3. **Briefing-Report in 2 min.** Messprotokoll: Tester startet "+ New Dossier", gibt freien Brief-Prompt ein (z. B. "Brief me on Sinjar"), editiert Header/Body bis Publish-fähig. Stoppuhr vom Klick auf "+ New Dossier" bis "Publish". **Ziel: ≤ 120 s** (p95 über 3 Läufe, verschiedene Themen).
4. **Incident-Toast Latenz.** Messprotokoll: Backend-Test triggert künstlichen Incident via Admin-API, Client-seitiger E2E-Assertion (`expect(toast).toBeVisible()`) mit Timestamp. **Ziel: t_toast − t_trigger ≤ 2 s** (p99 über 20 Läufe).
5. **Kein Page-Reload.** Messprotokoll: `window.performance.navigation.type === 0` beim Wechsel zwischen allen vier Routen (Unit-Test mit React Router).
6. **Typografie-Ladezeit.** Messprotokoll: Chrome DevTools Performance-Tab → Event `font load` für alle drei Familien. **Ziel: ≤ 200 ms** bei Cold-Cache und lokalem Backend. Grain-Overlay: Lighthouse-Profile auf Worldview mit aktivem Globe. **Ziel: ≥ 55 FPS bei Kamera-Rotation** (derselbe Benchmark ohne Grain als Baseline).

Kriterium 1 bleibt qualitativ; 2 und 3 sind UX-Zeiten mit expliziter p95-Grenze; 4–6 sind messbar und testbar und werden in den jeweiligen Sprint-Abnahmen geprüft.
