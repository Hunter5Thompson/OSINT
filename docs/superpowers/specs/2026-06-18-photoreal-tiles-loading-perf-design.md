# Photorealistic 3D Tiles — Loading-Performance Tuning

- **Datum:** 2026-06-18
- **Status:** Design approved + Review eingearbeitet → Plan/Umsetzung folgt
- **Scope:** Frontend (`services/frontend`), Cesium package range `^1.132.0`, lokal verifiziert gegen **1.139.1**
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

Der CesiumJS-Default ist **16** (verifiziert gegen 1.139.1). Ein Wert von `2` verlangt für
*jeden* Blick ~8× feinere Tiles als der Default → ein Vielfaches an Tile-Requests, durch das
Single-Thread Tile-Processing → durchgehende Trägheit. Verstärkt durch den kleinen
Default-Cache (512 MiB), der bereits besuchte Regionen beim Zurückschwenken neu lädt.

`addBuildingsTileset` ist der gemeinsame Pfad für die Google-Photoreal-Tiles **und** den
OSM-Buildings-Fallback (`createOsmBuildingsAsync`). Beide profitieren vom Tuning, daher ist
die Konfiguration tileset-typ-neutral.

## Verifikation gegen die installierte Version (1.139.1)

Das Review hat ergeben: mehrere ursprünglich geplante Tuning-Werte sind in 1.139.1 bereits
die Defaults und damit reine No-ops. Direkt im Build verifiziert:

| Property | Geplant gewesen | Default 1.139.1 | Verdikt |
|---|---|---|---|
| `RequestScheduler.maximumRequestsPerServer` | 18 | **18** (seit 1.113) | No-op → **gestrichen** |
| `dynamicScreenSpaceError` | true | `?? true` | No-op |
| `dynamicScreenSpaceErrorDensity` | 2.0e-4 | `?? 2e-4` | No-op |
| `dynamicScreenSpaceErrorFactor` | 24 | `?? 24` | No-op |
| `dynamicScreenSpaceErrorHeightFalloff` | 0.25 | `?? 0.25` | No-op |
| `cullRequestsWhileMoving` | true | `true` | No-op |
| `maximumCacheOverflowBytes` | 512 MiB | `536870912` (= 512 MiB) | No-op |

Entscheidung: **keine No-op-Properties setzen** (Prinzip „kein toter Tuning-Code"). Diese
Defaults werden hier nur dokumentiert, nicht im Code gesetzt.

## Goals / Non-Goals

**Goals**
- Spürbar schnelleres Tile-Streaming bei "ausgewogenem" Qualitäts-Trade-off (Detail aus
  typischer Betrachtungshöhe weitgehend erhalten).
- Die zwei echten Hebel testbar an einer Stelle bündeln statt im Viewer verstreut.
- Vorher/Nachher messbar machen (kein Bauchgefühl).

**Non-Goals**
- Kein adaptives SSE-Koppeln an den `PerformanceGuard` (Ansatz C — verworfen, Overkill).
- Keine Render-Optimierungen (`requestRenderMode`) — inkompatibel mit den Live-Layern
  (Flights/Trails/Pulses animieren kontinuierlich).
- Kein Anfassen globaler Cesium-Zustände (`RequestScheduler` etc.) — gestrichen, s.o.
- `skipLevelOfDetail` wird in Stufe 1 **nicht** aktiviert (siehe Stufe 2).

## Ansatz — Approach B, gestuft

### Neues Modul: `src/components/globe/tilesetConfig.ts`

Kapselt die echten Tuning-Werte und ihre Anwendung. Begründung: testbar (Stub-Tileset →
Properties asserten, erfüllt das TDD-Gebot aus CLAUDE.md), self-documenting via benannte
Konstanten, ein einziger Anwendungspunkt für beide Tileset-Pfade (Google + OSM-Fallback).

Exportierte API (Skizze, finalisiert in der Plan-Phase):

```ts
// Stufe-1-Tuningwerte als benannte Konstanten (Single Source of Truth)
export const PHOTOREAL_TUNING = {
  maximumScreenSpaceError: 8,
  cacheBytes: 1024 * 1024 * 1024, // 1 GiB
} as const;

// Setzt das Tileset-Bundle. Tileset-typ-neutral (Photoreal + OSM-Fallback).
export function applyTilesetPerformanceConfig(tileset: Cesium.Cesium3DTileset): void;
```

### Stufe 1 — wird gebaut (nur echte Hebel)

| Property | Wert | Default (1.139.1) | Wirkung |
|---|---|---|---|
| `maximumScreenSpaceError` | `8` | 16 | **Hauptfix** — ersetzt 2; deutlich weniger geforderte Tiles (SSE = Pixel-Fehlerschwelle, höher ⇒ weniger Tiles, nicht-linear) |
| `cacheBytes` | 1 GiB | 512 MiB | weniger Re-Downloads beim Zurückschwenken (32-GB-Workstation); Overflow bleibt auf Default-512-MiB |

### Integration in `GlobeViewer.tsx`

Eine einzige Änderung: in `addBuildingsTileset` (Z. 77–85) die Zeile
`tileset.maximumScreenSpaceError = 2;` ersetzen durch `applyTilesetPerformanceConfig(tileset);`
(vor `viewer.scene.primitives.add`). Kein globaler Setup-Code, kein Anfassen von
`Cesium.RequestScheduler` → keine StrictMode-/Doppel-Init-Erwägung nötig, da ausschließlich
Properties eines frisch erzeugten Tileset-Objekts gesetzt werden.

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
- `applyTilesetPerformanceConfig` setzt auf einem Stub-Tileset `maximumScreenSpaceError` und
  `cacheBytes` exakt auf die Werte aus `PHOTOREAL_TUNING`.

VS-Code-Test-Panel bleibt intakt (kein Bruch bestehender Frontend-Tests).

## Geänderte/neue Dateien

- **neu:** `services/frontend/src/components/globe/tilesetConfig.ts`
- **neu:** `services/frontend/src/components/globe/tilesetConfig.test.ts`
- **geändert:** `services/frontend/src/components/globe/GlobeViewer.tsx` (eine Zeile: SSE-Zeile
  → `applyTilesetPerformanceConfig(tileset)`)

## Risiken / offene Punkte

- SSE 8 statt 2: Städte aus nächster Nähe minimal weniger knackig — bewusst akzeptiert
  ("ausgewogen"). Falls zu weich, ist SSE die erste Stellschraube zurück Richtung 4–6.
- Picking/Hit-Test der Photoreal-Oberfläche (`isPhotorealSurfacePick`) ist von SSE
  unabhängig — kein Einfluss.

## Notizen

- `src/components/globe/GoogleTiles.tsx` enthält einen separaten Photoreal-Ladepfad
  (`createGooglePhotorealistic3DTileset`), der laut `rg` aktuell **nicht referenziert** ist
  (inaktiver Legacy-Pfad). **Nicht Teil dieser Änderung** — weder angefasst noch entfernt.
