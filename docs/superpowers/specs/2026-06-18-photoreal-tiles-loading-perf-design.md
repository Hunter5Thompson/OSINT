# Photorealistic 3D Tiles — Loading-Performance Tuning

- **Datum:** 2026-06-18
- **Status:** Design approved (Brainstorming) → Plan/Umsetzung folgt
- **Scope:** Frontend (`services/frontend`), CesiumJS 1.132
- **Codename-Kontext:** WorldView Globe

## Problem

Das Nachladen der Google Photorealistic 3D Tiles fühlt sich **generell überall träge** an —
nicht an einer einzelnen Stelle (Übersicht, Zoom, Schwenk), sondern durchgehend.

## Root Cause

In `services/frontend/src/components/globe/GlobeViewer.tsx:79` (im gemeinsamen Handler
`addBuildingsTileset`, Zeilen 77–85) steht:

```ts
tileset.maximumScreenSpaceError = 2;
```

Der CesiumJS-Default ist **16** (verifiziert gegen die 1.132 Ref-Doc). Ein Wert von `2`
verlangt für *jeden* Blick ~8× feinere Tiles als nötig → ein Vielfaches an Tile-Requests,
durch das Single-Thread Tile-Processing → durchgehende Trägheit. Verstärkt durch den kleinen
Default-Cache (512 MB), der bereits besuchte Regionen beim Zurückschwenken neu lädt.

`addBuildingsTileset` ist der gemeinsame Pfad für die Google-Photoreal-Tiles **und** den
OSM-Buildings-Fallback (`createOsmBuildingsAsync`). Beide profitieren vom Tuning, daher ist
die Konfiguration tileset-typ-neutral.

## Goals / Non-Goals

**Goals**
- Spürbar schnelleres Tile-Streaming bei "ausgewogenem" Qualitäts-Trade-off (Detail aus
  typischer Betrachtungshöhe weitgehend erhalten).
- Tuning testbar und an einer Stelle bündeln statt im Viewer verstreut.
- Vorher/Nachher messbar machen (kein Bauchgefühl).

**Non-Goals**
- Kein adaptives SSE-Koppeln an den `PerformanceGuard` (Ansatz C — verworfen, Overkill).
- Keine Render-Optimierungen (`requestRenderMode`) — inkompatibel mit den Live-Layern
  (Flights/Trails/Pulses animieren kontinuierlich).
- `skipLevelOfDetail` wird in Stufe 1 **nicht** aktiviert (siehe Stufe 2).

## Ansatz — Approach B, gestuft

### Neues Modul: `src/components/globe/tilesetConfig.ts`

Kapselt die Tuning-Werte und ihre Anwendung. Begründung: testbar (Stub-Tileset →
Properties asserten, erfüllt das TDD-Gebot aus CLAUDE.md) und hält `GlobeViewer.tsx` schlank.

Exportierte API (Skizze, finalisiert in der Plan-Phase):

```ts
// Stufe-1-Tuningwerte als benannte Konstanten (Single Source of Truth)
export const PHOTOREAL_TUNING = {
  maximumScreenSpaceError: 8,
  cacheBytes: 1024 * 1024 * 1024,          // 1 GiB
  maximumCacheOverflowBytes: 512 * 1024 * 1024, // 512 MiB
  dynamicScreenSpaceError: true,
  dynamicScreenSpaceErrorDensity: 2.0e-4,
  dynamicScreenSpaceErrorFactor: 24,
  dynamicScreenSpaceErrorHeightFalloff: 0.25,
  cullRequestsWhileMoving: true,
} as const;

export const MAX_REQUESTS_PER_SERVER = 18;

// Setzt das Tileset-Bundle. Tileset-typ-neutral (Photoreal + OSM-Fallback).
export function applyTilesetPerformanceConfig(tileset: Cesium.Cesium3DTileset): void;

// Setzt den globalen RequestScheduler-Wert. Idempotent, einmalig beim Viewer-Setup.
export function configureRequestScheduler(): void;
```

### Stufe 1 — wird gebaut

Werte, die `applyTilesetPerformanceConfig` setzt:

| Property | Wert | Default (1.132) | Wirkung |
|---|---|---|---|
| `maximumScreenSpaceError` | `8` | 16 | **Hauptfix** — ersetzt 2; deutlich weniger geforderte Tiles (SSE = Pixel-Fehlerschwelle, höher ⇒ weniger Tiles, nicht-linear) |
| `cacheBytes` | 1 GiB | 512 MB | weniger Re-Downloads beim Zurückschwenken (32-GB-Workstation) |
| `maximumCacheOverflowBytes` | 512 MiB | 512 MB | Headroom über `cacheBytes` |
| `dynamicScreenSpaceError` | `true` | `true` | gröbere Tiles für Distanz/streifende Winkel |
| `dynamicScreenSpaceErrorDensity` | `2.0e-4` | — | Kamera-Distanz-Steuerung des Effekts |
| `dynamicScreenSpaceErrorFactor` | `24` | — | Intensität |
| `dynamicScreenSpaceErrorHeightFalloff` | `0.25` | — | Höhenbereich für Maximaleffekt |
| `cullRequestsWhileMoving` | `true` | `true` | keine Requests für Tiles, die bei Kamerabewegung ungenutzt bleiben |

### Integration in `GlobeViewer.tsx`

1. In `addBuildingsTileset` (Z. 77–85) die Zeile `tileset.maximumScreenSpaceError = 2;`
   ersetzen durch `applyTilesetPerformanceConfig(tileset);` (vor `viewer.scene.primitives.add`).
2. `configureRequestScheduler()` **einmalig** im Viewer-Setup aufrufen, neben
   `Cesium.Ion.defaultAccessToken = cesiumToken;` (Z. 37).

### Globaler RequestScheduler — Idempotenz & React StrictMode

`Cesium.RequestScheduler.maximumRequestsPerServer = 18` (Default 6) hebt die künstliche
Parallelitäts-Drosselung auf — Google liefert die Tiles über HTTP/2, dort bremst der 6er-Cap
ohne Nutzen.

**Wichtig (explizit dokumentiert):** Dieser Wert wird **idempotent beim Viewer-Setup** gesetzt.
Es hängt **kein React-State und kein Effect-Dependency** davon ab. In React StrictMode kann
Init-Code im Dev-Modus doppelt laufen — bei einem konstanten globalen Skalar ist das
unkritisch (zweite Zuweisung = identischer Wert, kein Seiteneffekt). Die Funktion ist bewusst
so gebaut, dass mehrfaches Aufrufen folgenlos ist.

**Kein Seiteneffekt auf das Backend:** Der `RequestScheduler` betrifft nur Cesium-`Resource`-
Requests (Tiles, Terrain, Imagery). Die `/api`-Calls des Backends laufen über fetch/axios und
sind davon unberührt.

## Stufe 2 — NICHT gebaut, nur dokumentiert

Erst nach Messung von Stufe 1. Falls dann noch zäh, als zweiter Hebel testen (kann bei
Photoreal-Tiles sichtbares Pop-in / kurzzeitig fehlende Detailstufen erzeugen — deshalb
nicht in Stufe 1 und nicht als toter/Flag-gated Code im Repo):

```ts
tileset.skipLevelOfDetail = true;
tileset.baseScreenSpaceError = 1024;
tileset.skipScreenSpaceErrorFactor = 16;
tileset.skipLevels = 1;
tileset.immediatelyLoadDesiredLevelOfDetail = false;
tileset.loadSiblings = false;
```

## Messprotokoll (Beweis statt Bauchgefühl)

Vorher (SSE=2, aktueller Stand) vs. Nachher (Stufe 1) festhalten, je für:
- **(a) Europa-Übersicht** (Default-Kamera 15°E/45°N, 15.000 km)
- **(b) Zoom auf eine Stadt**

Metriken: Anzahl Tile-Requests im Browser-Netzwerk-Tab + gefühlte Zeit bis "scharf genug".
Erwartung: deutlich weniger Requests bei (a)+(b), ohne dass aus typischer Betrachtungshöhe
sichtbar Detail fehlt.

## Testing (TDD)

`tilesetConfig.test.ts` (Vitest):
- `applyTilesetPerformanceConfig` setzt auf einem Stub-Tileset alle erwarteten Properties
  auf die Werte aus `PHOTOREAL_TUNING`.
- `configureRequestScheduler` setzt `Cesium.RequestScheduler.maximumRequestsPerServer` auf 18.
- Mehrfaches Aufrufen von `configureRequestScheduler` lässt den Wert konstant (Idempotenz).

VS-Code-Test-Panel bleibt intakt (kein Bruch bestehender Frontend-Tests).

## Geänderte/neue Dateien

- **neu:** `services/frontend/src/components/globe/tilesetConfig.ts`
- **neu:** `services/frontend/src/components/globe/tilesetConfig.test.ts`
- **geändert:** `services/frontend/src/components/globe/GlobeViewer.tsx`
  (SSE-Zeile ersetzt, `configureRequestScheduler()` im Setup)

## Risiken / offene Punkte

- SSE 8 statt 2: Städte aus nächster Nähe minimal weniger knackig — bewusst akzeptiert
  ("ausgewogen"). Falls zu weich, ist SSE die erste Stellschraube zurück Richtung 4–6.
- `maximumRequestsPerServer = 18` ist global; bei nicht-HTTP/2-Quellen theoretisch
  Head-of-Line-Effekte — für die Google-Tiles (HTTP/2) unkritisch. Bei Messauffälligkeiten
  zurück auf 12 oder 6.
- Picking/Hit-Test der Photoreal-Oberfläche (`isPhotorealSurfacePick`) ist von SSE
  unabhängig — kein Einfluss.
