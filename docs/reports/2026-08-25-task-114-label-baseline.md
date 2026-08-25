# TASK-114 Task 1 — Label Baseline

**Date:** 2026-08-25 · **Branch:** `feature/TASK-114-declutter-p1-render-and-labels` @ `418c338`
**Plan:** [`2026-08-25-task-114-declutter-p1-render-and-labels.md`](../superpowers/plans/2026-08-25-task-114-declutter-p1-render-and-labels.md)

## Method

Measured, not eyeballed. The plan's original Step 2 asked for visually counted labels; that is unreliable and irreproducible. Instead a temporary probe (`src/dev/labelBaselineProbe.ts`, **not for merge**) reproduces the comparison Cesium performs internally:

```
drawn  ⇔  label.show
       ∧  Cartesian3.distance(camera.positionWC, label.position) ∈ [ddc.near, ddc.far]
```

`label.show` reports authoring intent only — Cesium evaluates the `DistanceDisplayCondition` per object per frame and never writes the verdict back, which is why "created" and "drawn" must be counted separately.

**Harness:** headless Chromium (Playwright-cached `chromium-1223`) against `npm run dev` on the branch, with `redis`/`qdrant`/`neo4j`/`backend` up. **No vLLM** — the globe needs none.

**Data:** 144 live USGS earthquakes; 38 GDACS events. GDACS required `since_hours=720` because the local Qdrant copy is older than the endpoint's 168 h default (collector has not run recently) — a temporary one-line change in `WorldviewPage.tsx`, also not for merge.

**Sweep centre 140°E / 36°N (Japan).** A first run over 15°E / 45°N returned `created: 0` below globe scale: central Europe has no recent M4.5+ events, so the earthquake layer's own `selectVisible` culled every candidate. That first run measured an empty set, not a DDC effect.

**Collections:** `#6` = Earthquakes (`M6.7`, `M6.2`, `M6.0`), `#30` = GDACS (`Flood`, `Wildfire`). Both carry `ddcFar: 5 000 000`. All other label collections were empty (their layers off).

## Sweep — five plan altitudes, nadir and 45° oblique

| Altitude | Pitch | drawn / created | Earthquakes | GDACS |
|---:|---:|---:|---|---|
| 15 000 km | −90° | **0 / 182** | 0 / 144 | 0 / 38 |
| 3 000 km | −90° | 10 / 46 | 8 / 8 | 2 / 38 |
| 500 km | −90° | 13 / 39 | 1 / 1 | 12 / 38 |
| 100 km | −90° | 13 / 39 | 1 / 1 | 12 / 38 |
| 10 km | −90° | 12 / 38 | — | 12 / 38 |
| 15 000 km | −45° | **0 / 182** | 0 / 144 | 0 / 38 |
| 3 000 km | −45° | **2 / 39** | 0 / 1 | 2 / 38 |
| 500 km | −45° | 16 / 42 | 4 / 4 | 12 / 38 |
| 100 km | −45° | 12 / 38 | — | 12 / 38 |
| 10 km | −45° | 12 / 38 | — | 12 / 38 |

At 15 000 km the nearest label is 16 110 km (earthquakes) / 15 022 km (GDACS) from the camera, against a DDC far of 5 000 km.

## Fine sweep — where the cut sits (nadir, 140°E / 36°N)

| Altitude | drawn / created | Earthquakes | GDACS |
|---:|---:|---|---|
| 3 000 km | 10 / 46 | 8 / 8 | 2 / 38 |
| 4 000 km | 12 / 51 | 11 / 13 | 1 / 38 |
| 4 500 km | 9 / 57 | 8 / 19 | 1 / 38 |
| **5 000 km** | **0 / 63** | **0 / 25** | **0 / 38** |
| 5 500 km | 0 / 182 | 0 / 144 | 0 / 38 |
| 6 000 km | 0 / 182 | 0 / 144 | 0 / 38 |
| 8 000 km | 0 / 182 | 0 / 144 | 0 / 38 |

## Findings

**1. The highest altitude at which any label is drawn is between 4 500 km and 5 000 km.**
The cut is sharp and lands exactly on the shared `DistanceDisplayCondition(0, 5_000_000)`. At nadir the camera-to-object distance for the nearest object is ≈ the altitude, so the altitude cut coincides with the distance cut. Above it: zero labels, from both layers, at every pitch tested.

**2. `created` ≫ `drawn`, and the gap is structural, not marginal.**
At 15 000 km both layers build all 182 labels and Cesium discards every one. GDACS is the worse case at every altitude — it has no viewport culling, so it always creates all 38 and draws between 0 and 12. Earthquakes stay close to parity below globe scale only because `selectVisible` (`EarthquakeLayer.tsx:109`) already culls to the viewport; above it the layer keeps all 144 and draws none.

This is wasted work the collective budget can reclaim: the arbiter decides membership before any label is built.

**3. Pitch changes the count at a fixed altitude — the DDC is distance-based, confirmed empirically.**
At 3 000 km: nadir draws 10, 45° oblique draws 2. Earthquakes go 8 → 0. At 500 km the same tilt goes the other way, 13 → 16. No altitude threshold can reproduce either. Any plan text describing `QUAKE_LABEL_ALTITUDE_M` as an altitude guard is wrong; it is a distance condition that happens to be named for an altitude.

## Input to Task 10 (DDC decision)

| Budget row | Band | Verdict from measurement |
|---|---|---|
| `street` | < 50 km | live |
| `city` | < 250 km | live |
| `metro` | < 1 000 km | live |
| `regional` | 1 000 – 8 000 km | **live to ≈4 700 km, dead above — keep the row** |
| `global` | ≥ 8 000 km | **0 drawn at every sample — delete the row** |

Under **Option B** the matrix must be clipped to `street`/`city`/`metro`/`regional`, with acceptance over 0 – ~5 000 km. The earlier "street/city/metro only" formulation would have removed the budget from 1 000–5 000 km, which the table above shows is the busiest live band. Under **Option A** (arbiter replaces the DDC) the `global` and upper-`regional` rows become reachable for the first time and need a visual sign-off at globe scale.

## Task 4 — what this harness could and could not establish

**Established:**
- The governor is installed and sets its flags: `maximumRenderTimeChange` reads back `Infinity`.
  (An earlier run reported `null` — that was `JSON.stringify(Infinity)` in the harness, not the governor.)
- With the default layer set the scene is in **continuous** mode (`requestRenderMode === false`), exactly as the plan's "does NOT deliver" section predicts: four default-on layers own per-frame animators and each holds.

**Not established, and not establishable here:**
- **Idle mode was never reached.** The harness failed to turn the animated layers off — its text-matched clicks found no controls (`toggled: []`), so both frame windows measured the same continuous state.
- **The frame counts are meaningless as a GPU claim.** Headless Chromium falls back to SwiftShader; the scene painted 16 frames / 10 s (1.6 fps) purely because it is software-rendered. That number says nothing about the RTX 5090.

**Task 4 Steps 5–7 therefore still need a real browser on the real GPU**: the 15-layer toggle matrix, the spotlight-fade check, the spatial-scope drilldown check, and the before/after GPU delta. The frame-counting probe (`window.__odinLabelProbe.measureFrames(label, ms)`) is available there and is a better idle metric than a task-manager percentage — in idle it should fall to near zero between interactions, in continuous it should track the display refresh rate.

## Temporary changes on the branch — revert before Task 9

| File | Change |
|---|---|
| `services/frontend/src/dev/labelBaselineProbe.ts` | new, probe only |
| `services/frontend/src/components/globe/GlobeViewer.tsx` | probe install/uninstall, two lines + import |
| `services/frontend/src/pages/WorldviewPage.tsx` | `useGDACSEvents(effectiveLayers.gdacs, 720)` |

Raw output: `sweep-result.json`, `fine-result.json`, `idle-result.json` and five `baseline-*.png` in the session scratchpad (not committed).
