# WorldView UX-Politur — Design Spec

**Datum:** 2026-06-16
**Branch:** `feature/worldview-ux-polish`
**Scope:** Sieben gemeldete UI-/UX-Mängel in der WorldView-Oberfläche (Globe, Timeslider, Briefing Room, War Room). Reine Frontend-Arbeit (`services/frontend`) plus ein statischer Datensatz. Keine Backend-/Graph-/RAG-Änderungen.

## Ausgangslage (verifiziert)

Alle Befunde unten sind im Code verifiziert (Datei:Zeile), nicht vermutet:

- Es gibt **keinen** benannten „politisch/geografisch"-Umschalter. Was der User so nennt:
  **„geografisch" = Google-Photorealistic-3D-Tiles an** (Layer `cityBuildings`, `GlobeViewer.tsx:83`), **„politisch" = flache ROAD-Imagery** mit sichtbaren Grenzen.
- `EntityClickHandler.tsx:349-351` — `if (picked) { return; }`: jeder Pick auf ein Primitive, das kein bekannter Daten-Tag ist, bricht **vor** dem Country-Hit-Test (Z. 354–377) ab. Über den 3D-Tiles trifft der Klick ein Tile-Primitive → Almanac öffnet nicht.
- `CountryBorders.tsx` — Polylines `width: 0.6`, Material `--stone` (#958a7a) α 0.7, **kein** `disableDepthTestDistance` → über Photoreal-Terrain praktisch unsichtbar.
- `public/country-endonyms.json` — Capital-Daten für **nur 8** Länder. Renderer (`CapitalPulse.tsx`) zeigt nur die Capital des fokussierten Landes; mehr Daten = mehr Hauptstädte.
- `SpotlightCartouche.tsx:34` — `<h2 class="cartouche-title">{t.name}</h2>` ist das On-Globe-Ländername-Label; InspectorPanel sitzt `top:86 right:16 width:360` (`WorldviewPage.tsx:744`) und verdeckt es.
- Briefings: `deleteReport(id)` existiert (`api.ts:388`), wird **nie** aufgerufen; kein Delete-UI in `BriefingPage.tsx`.
- Munin-Text: `MuninStreamQuadrant.tsx` Instrument Serif, `italic`, `12px`; Briefing-Munin-Messages `.serif` italic `0.95rem`.

**Capital-Objektform (präzise):** Roh-JSON `capital: {name, lat, lon}` → Loader `useCountryHitTest.ts:86-87` transformiert zu `{name, coords:{lon,lat}}` → Renderer konsumieren `capital.coords.{lat,lon}`. P4 erweitert nur die Roh-JSON in der flachen Form; keine Renderer-/Typ-Änderung.

---

## Cluster A — Globe / Karte (Punkte 2–5)

### P3 — Almanac auf der geografischen (3D) Karte (Kern-Fix)

**Problem:** Über den Photoreal-Tiles bricht `EntityClickHandler` ab, bevor der Country-Hit-Test läuft.

**Fix:** Eine kleine, **rein testbare** Helper-Funktion extrahieren:

```ts
// isPhotorealSurfacePick(picked, photorealTileset): boolean
// true, wenn der Pick die Photoreal-/Globe-Oberfläche ist (kein echtes UI-/Layer-Primitive)
```

Duck-Typing, nicht nur `instanceof` (Cesium-Picks sind je nach Provider/Primitive nicht zuverlässig über `instanceof` klassifizierbar):
- `picked instanceof Cesium.Cesium3DTileFeature` **oder**
- `picked?.primitive` referenziert das bekannte Photoreal-/Buildings-Tileset (eigene Referenz/Marker durchreichen) **oder**
- `picked?.tileset` / `picked?.content?.tileset` ist das Photoreal-Tileset.

`EntityClickHandler` ändert dann den Frühabbruch in Z. 349–351: **nur** bei echten UI-/Layer-Picks (die 6 onSelect-Layer + Cesium-Entities) `return`; bei `isPhotorealSurfacePick(...) === true` in den Country-Hit-Test (Z. 354 ff.) **durchfallen**. Der Hit-Test nutzt bereits `scene.pickPosition` → funktioniert über Tiles.

**Referenz-Hochreichung (explizit):** `buildingsTilesetRef.current` lebt aktuell **nur lokal** in `GlobeViewer` (`GlobeViewer.tsx:26,80`) — `EntityClickHandler` kann sie sonst nicht robust kennen. `GlobeViewer` reicht das Tileset per Callback nach `WorldviewPage` hoch, z.B. `onPhotorealTilesetReady(tileset | null)`: gesetzt nach `addBuildingsTileset` (Z. 80), beim Cleanup/Unmount wieder `null`. `WorldviewPage` reicht die Referenz an `EntityClickHandler` durch.

**Test:** Reiner Unit-Test der Helper-Funktion mit konstruierten Pick-Objekten (Cesium3DTileFeature-artig, Layer-Primitive-artig, null) — kein voller Cesium-Viewer nötig. Plus ein Test, der bestätigt: Photoreal-Pick → Hit-Test-Pfad; Layer-Pick → kein Hit-Test.

### P2 — Ländergrenzen sichtbarer (über Photoreal-Tiles)

**Fix (`CountryBorders.tsx`):**
- Linienbreite `0.6 → 1.5–2.0`.
- **Helle, neutrale** Linie (off-white/stone mit Alpha), **keine** kräftige Akzentfarbe — eine Akzentfarbe würde wie ein Datenlayer gelesen.
- `polyline.disableDepthTestDistance = Number.POSITIVE_INFINITY` (oder am Material/Primitive-Äquivalent), damit die Grenzen nicht vom Photoreal-Terrain verdeckt werden.

**Test:** Assertion auf Polyline-Width und gesetztes `disableDepthTestDistance` (bzw. die gewählte neutrale Material-Farbe) im konstruierten `PolylineCollection`-Aufruf.

### P4 — Hauptstädte für alle Länder

**Problem:** Datenlücke (8 von ~195).

**Fix:** `public/country-endonyms.json` mit Capitals für alle souveränen Staaten erweitern, in der bestehenden flachen Form `capital: {name, lat, lon}`, ISO3-gekeyed.

**Quelle:** **Natural Earth** (Public Domain) — Admin-0 Capitals / Populated Places gefiltert auf `FEATURECLA = "Admin-0 capital"`, gekeyed über `ADM0_A3` → ISO3. Quelle + Generierungsschritt im Daten-Header/Commit dokumentieren. Bewusste Sonderfälle (z.B. Staaten ohne eindeutige/de-facto Hauptstadt) bleiben **explizit `null`** und werden in einer dokumentierten Ausnahmeliste geführt.

**Test:** Daten-Vollständigkeit gegen die **tatsächlichen ISO3-Keys aus `countries-110m.json`** (nicht hart gegen „~195"): jeder dort vorhandene ISO3 hat entweder einen Capital-Eintrag (mit `name` + numerischem `lat`/`lon` im plausiblen Bereich) **oder** steht explizit in der Ausnahmeliste (`null`). Test schlägt fehl, wenn ein ISO3 weder das eine noch das andere ist.

### P5 — Ländername nicht mehr vom Panel verdeckt

**Entscheidung:** **Kartusche verschieben, Panel bleibt rechts.** Das InspectorPanel ist stabile App-Chrome; die Kartusche ist kontextuelle Globe-UI.

**Fix (CSS, nicht TSX):** Die Cartouche-Positionierung sitzt in `services/frontend/src/components/worldview/worldviewHudLoader.css` — konkret `.cartouche-country { right: 36px; … text-align: right }` (Z. 230) und `.cartouche-title` (Z. 232). Diese nach **links / links-mittig** umstellen (z.B. `left`-basiert + `text-align: left`), sodass sie nicht in die rechte Panel-Zone (~390px) ragt, wenn das InspectorPanel offen ist. Auf Mobile separat positionieren (Panel-Layout unterscheidet sich dort).

**Test:** Positions-/Style-Assertion (Kartusche liegt links der Panel-Zone bei offenem Panel) + visuelle Verifikation.

---

## Cluster B — Timeslider (Punkt 1: „Beides / voll")

**Fix (`ChronikTimeline.tsx` Button-Row + `ScrubberMount` + `TimeContext`):**

Volle Transport-Steuerung. **Speed-Magnitude und Richtung getrennt** — **minimaler Weg (entschieden):** `TimeContext.speed` bleibt **signiert** (kein neues API), `ScrubberMount`/`ChronikTimeline` behandeln `Math.abs(speed)` als UI-Magnitude und das **Vorzeichen** als Richtung. Kein Erweitern der TimeContext-Schnittstelle.

Buttons:
- `⏮ Step-back` = `pause()` + `seek(−1 Bucket)`
- `◀ Reverse-Play` = Richtung rückwärts, `play()` mit negativer Effektiv-Geschwindigkeit
- `⏸/▶ Play/Pause`
- `▶ Forward-Play` = Richtung vorwärts, `play()`
- `⏭ Step-forward` = `pause()` + `seek(+1 Bucket)`
- **Speed-Select**: 0.5× / 1× / 5× / 20× (Magnitude, unabhängig von der Richtung)

Bucket-Größe = Fenster-Span / Bucket-Anzahl (aus dem Histogram-State ableitbar).

**Zeitgrenzen (explizit):** Reverse-Play am **unteren** Limit **pausiert/clampt** (kein Wraparound, außer ausdrücklich gewünscht); Forward-Play am oberen Limit verhält sich symmetrisch (in LIVE: am `now`-Rand). `TimeContext` clampt im REPLAY-Modus bereits an Fenster-Grenzen (`clockRange = CLAMPED`) — Reverse muss negativen Multiplier **plus** dieses Clamp-Verhalten korrekt zusammenführen.

`TimeContext` hat `setSpeed`/`seek`/`play`/`pause` schon. Neu: getrennte Richtung (Vorzeichen des Multipliers) von der UI-Speed-Magnitude; Step-Helper in `ScrubberMount` (`seek(getTimeMs() ± bucketMs)`).

**Test:**
- Reverse setzt einen **negativen** Effektiv-Multiplier; Forward einen positiven; Speed-Select ändert nur die Magnitude, nicht das Vorzeichen.
- Step-back/-forward rufen `seek` mit korrektem `± bucketMs`-Offset und pausieren.
- Reverse am unteren Limit pausiert/clampt (kein Wraparound).

---

## Cluster C — Briefing & War Room (Punkte 6, 7)

### P6 — Briefings löschen

**Fix (`BriefingPage.tsx`):** Delete-Button in `.briefing-actions-row` (Z. 418) **mit Bestätigung**.

**Reihenfolge (explizit):** State-Entfernung **erst nach erfolgreichem** `deleteReport(id)` (`api.ts:388`) — oder optimistic delete **mit Rollback bei Fehler**. Wird der aktuell selektierte Report gelöscht: Selektion auf den **nächsten** Report (oder `null`, falls keiner mehr da) setzen; zugehörige Chat-Messages aus dem `Record<string, ReportMessage[]>`-State entfernen.

**Test:**
- Erfolgreicher Delete: API aufgerufen, Report aus `reports`-State entfernt, Selektion sinnvoll neu gesetzt.
- Fehlgeschlagener Delete (optimistic): Rollback — Report bleibt/erscheint wieder im State.

### P7 — Munin lesbarer („Serif entschärfen")

**Entscheidung:** Instrument Serif **behalten** (Hlíðskjalf-Identität), aber:
- `font-style: italic → normal` (aufrecht)
- Größe `≥ 15px` (War Room `MuninStreamQuadrant.tsx` von 12px; Briefing-Munin-Messages von `0.95rem`)
- `line-height` leicht erhöhen für Lesbarkeit.

**Scope-Guard (wichtig):** **Nicht** die globale `.serif`-Utility (`hlidskjalf.css`) ändern — das würde Titel/Branding quer durch die App treffen. Nur Munin-spezifische Selektoren überschreiben: War Room via `MuninStreamQuadrant.tsx` (inline/eigene Klasse), Briefing via munin-spezifischem Selektor wie `.briefing-chat-item.is-munin p` (statt `.briefing-chat-item p.serif`, `briefingPage.css:422`).

**Test:** Gezielter Regressions-Style-Test: `font-style !== "italic"` und `font-size >= 15px` für den Munin-Textknoten. (Bewusst schmal gehalten — Style-Tests sind brittle, aber als Regressionsanker ok.)

---

## Nicht im Scope (YAGNI)

- Kein echter Basemap-Picker (Satellit/Terrain/Politisch) — der User toggelt über bestehende Layer.
- Kein Wraparound/Loop-Playback im Timeslider.
- Keine Capital-Daten-API zur Laufzeit — statischer Datensatz reicht.
- Keine Umstellung der Munin-Schriftfamilie weg von Instrument Serif.

## Test-/Build-Gates

`npm run lint`, `npm run type-check`, `npm run build`, Vitest grün. Tests pro Cluster klein geschnitten; P3-Logik primär über die extrahierte Helper-Funktion getestet (minimaler Cesium-Test-Schmerz).

## Branch / Commits

Ein Branch `feature/worldview-ux-polish`, gruppierte Commits entlang der drei Cluster (A Globe, B Timeslider, C Briefing/War Room). TDD pro Punkt wo sinnvoll testbar.
