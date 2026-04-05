# Globe Layers Phase 3 — Animations + Type Icons Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the ODIN Globe from static dot-markers to animated, type-aware markers with flight trails, ship course vectors, satellite orbit arcs, earthquake/event pulses, and a global FPS-based performance guard.

**Architecture:** A shared `PerformanceGuard` component monitors FPS and exposes a degradation level via React context. Each layer component reads this level to decide what to animate. Type-specific canvas icon factories replace generic shapes. Animation loops use `requestAnimationFrame` for pulses and `setInterval` for trail/position updates (matching existing FlightLayer pattern). Backend extends the Satellite model with `operator_country` + `satellite_type` fields derived from a static name-prefix mapping.

**Tech Stack:** CesiumJS (BillboardCollection, PolylineCollection, PointPrimitiveCollection), React 19, TypeScript, Canvas 2D API, satellite.js (SGP4), Pydantic v2

**Spec:** `docs/superpowers/specs/2026-04-05-globe-layers-evolution-design.md` — Phase 3

---

## File Structure

### Performance Guard (new)

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `services/frontend/src/components/globe/PerformanceGuard.tsx` | FPS monitor, degradation level context provider |

### Aircraft Type Icons + Trails (modify existing)

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `services/frontend/src/components/layers/icons/aircraftIcons.ts` | Type-specific canvas icon factory + cache |
| Modify | `services/frontend/src/components/layers/FlightLayer.tsx` | Type icons, flight trails, LOD gate, perf guard |

### Ship Type Icons + Course Vectors (modify existing)

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `services/frontend/src/components/layers/icons/shipIcons.ts` | Type-specific canvas icon factory |
| Modify | `services/frontend/src/components/layers/ShipLayer.tsx` | Type icons, course vectors, LOD gate |

### Satellite Enhancements (modify existing + backend)

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `services/backend/app/models/satellite.py` | Add operator_country + satellite_type fields |
| Modify | `services/backend/app/services/satellite_service.py` | Name-prefix → country mapping, type classification |
| Modify | `services/frontend/src/types/index.ts` | Extend Satellite type |
| Modify | `services/frontend/src/components/layers/SatelliteLayer.tsx` | Orbit arcs, footprint hover, recon highlight, country tint |

### Earthquake + Event Pulses (modify existing)

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `services/frontend/src/components/layers/EarthquakeLayer.tsx` | Pulse animation loop |
| Modify | `services/frontend/src/components/layers/EventLayer.tsx` | Severity-based pulse |

### Wiring (modify existing)

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `services/frontend/src/App.tsx` | Add PerformanceGuard wrapper |
| Modify | `services/frontend/src/components/globe/EntityClickHandler.tsx` | Extended satellite popup |

---

## Task 1: PerformanceGuard — FPS Monitor + Degradation Context

**Files:**
- Create: `services/frontend/src/components/globe/PerformanceGuard.tsx`
- Modify: `services/frontend/src/App.tsx`

- [ ] **Step 1: Create PerformanceGuard component**

Create `services/frontend/src/components/globe/PerformanceGuard.tsx`:

```typescript
import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";

/**
 * Degradation levels (higher = more features disabled):
 * 0 = full animations
 * 1 = shortened trails (10 positions instead of 30)
 * 2 = no pulse animations (static rings only)
 * 3 = no orbit arcs, no trails
 * 4 = static dots only (all animations off)
 */
export type DegradationLevel = 0 | 1 | 2 | 3 | 4;

interface PerformanceState {
  fps: number;
  degradation: DegradationLevel;
}

const PerformanceContext = createContext<PerformanceState>({ fps: 60, degradation: 0 });

export function usePerformance(): PerformanceState {
  return useContext(PerformanceContext);
}

const FPS_THRESHOLD = 30;
const SUSTAINED_LOW_FPS_MS = 2000;
const RECOVERY_MS = 5000;

export function PerformanceGuard({ children }: { children: ReactNode }) {
  const [state, setState] = useState<PerformanceState>({ fps: 60, degradation: 0 });
  const frameCountRef = useRef(0);
  const lastTimeRef = useRef(performance.now());
  const lowFpsSinceRef = useRef<number | null>(null);
  const highFpsSinceRef = useRef<number | null>(null);

  useEffect(() => {
    let animId: number;

    const measure = () => {
      frameCountRef.current++;
      const now = performance.now();

      if (now - lastTimeRef.current >= 1000) {
        const currentFps = frameCountRef.current;
        frameCountRef.current = 0;
        lastTimeRef.current = now;

        setState((prev) => {
          let nextDeg = prev.degradation;

          if (currentFps < FPS_THRESHOLD) {
            highFpsSinceRef.current = null;
            if (lowFpsSinceRef.current === null) {
              lowFpsSinceRef.current = now;
            } else if (now - lowFpsSinceRef.current >= SUSTAINED_LOW_FPS_MS && nextDeg < 4) {
              nextDeg = Math.min(4, nextDeg + 1) as DegradationLevel;
              lowFpsSinceRef.current = now; // reset timer for next escalation
            }
          } else {
            lowFpsSinceRef.current = null;
            if (highFpsSinceRef.current === null) {
              highFpsSinceRef.current = now;
            } else if (now - highFpsSinceRef.current >= RECOVERY_MS && nextDeg > 0) {
              nextDeg = Math.max(0, nextDeg - 1) as DegradationLevel;
              highFpsSinceRef.current = now;
            }
          }

          return { fps: currentFps, degradation: nextDeg };
        });
      }

      animId = requestAnimationFrame(measure);
    };

    animId = requestAnimationFrame(measure);
    return () => cancelAnimationFrame(animId);
  }, []);

  return (
    <PerformanceContext.Provider value={state}>
      {children}
    </PerformanceContext.Provider>
  );
}
```

- [ ] **Step 2: Wrap App children in PerformanceGuard**

In `services/frontend/src/App.tsx`, add import at top:

```typescript
import { PerformanceGuard } from "./components/globe/PerformanceGuard";
```

Wrap the return JSX — replace `<div className="w-full h-full relative">` block:

```tsx
    <PerformanceGuard>
      <div className="w-full h-full relative">
        {/* ... all existing children unchanged ... */}
      </div>
    </PerformanceGuard>
```

- [ ] **Step 3: Remove duplicate FPS counter from StatusBar**

In `services/frontend/src/components/ui/StatusBar.tsx`, the FPS measurement code (lines 33-51, the `useEffect` with `requestAnimationFrame`) is now redundant — PerformanceGuard measures FPS globally. Replace the local FPS state with the context:

Add import at top:

```typescript
import { usePerformance } from "../globe/PerformanceGuard";
```

Replace lines 33-51 (the fps state + useEffect) with:

```typescript
  const { fps } = usePerformance();
```

Remove the `useState`, `useRef`, and the `useEffect` for FPS measurement. Keep the `fpsColor` calculation (line 53) and the rendering unchanged.

- [ ] **Step 4: Run type-check**

```bash
cd services/frontend && npx tsc --noEmit
```

Expected: No errors.

- [ ] **Step 5: Commit**

```bash
git add services/frontend/src/components/globe/PerformanceGuard.tsx services/frontend/src/App.tsx services/frontend/src/components/ui/StatusBar.tsx
git commit -m "feat(frontend): add PerformanceGuard with FPS-based degradation context"
```

---

## Task 2: Aircraft Type Icon Factory

**Files:**
- Create: `services/frontend/src/components/layers/icons/aircraftIcons.ts`

- [ ] **Step 1: Create aircraft icon factory**

Create `services/frontend/src/components/layers/icons/aircraftIcons.ts`:

```typescript
/**
 * Aircraft type-specific canvas icon factory with heading-bucketed caching.
 *
 * Classification: callsign prefix + ADS-B category heuristics.
 * Cache key: `{type}_{headingBucket}` — max 72 headings × 6 types = 432 entries.
 */

export type AircraftIconType = "fighter" | "bomber" | "transport_mil" | "helicopter" | "uav" | "civilian";

const MILITARY_CALLSIGN_PREFIXES = [
  "RCH", "EVAC", "DUKE", "VALOR", "REACH", "FORGE", "COBRA", "HAWK",
  "VIPER", "RAPTOR", "REAPER", "SIGINT", "FORTE", "NCHO", "TOPCAT",
];

const ICON_COLORS: Record<AircraftIconType, string> = {
  fighter: "#ef4444",
  bomber: "#ef4444",
  transport_mil: "#c4813a",
  helicopter: "#ef4444",
  uav: "#a855f7",
  civilian: "#d4cdc0",
};

export function classifyAircraft(
  callsign: string | null,
  isMilitary: boolean,
  aircraftType: string | null,
  altitudeM: number,
  velocityMs: number,
): AircraftIconType {
  const cs = (callsign ?? "").toUpperCase().trim();
  const at = (aircraftType ?? "").toUpperCase();

  // Helicopter: aircraft_type contains H (e.g., H60, H47, EC35)
  if (/^H\d|^EC\d|^AS\d|^AW\d|^R22|^R44|^R66|^B06|^B47/.test(at)) return "helicopter";

  // UAV/drone heuristic: slow + low + specific names
  if (
    (cs.includes("REAPER") || cs.includes("FORTE") || cs.includes("SIGINT") || at.includes("RQ") || at.includes("MQ")) &&
    isMilitary
  ) return "uav";

  // Military transport: known callsign prefixes
  if (isMilitary && MILITARY_CALLSIGN_PREFIXES.some((p) => cs.startsWith(p))) return "transport_mil";

  // Fighter: military + fast + high
  if (isMilitary && velocityMs > 200 && altitudeM > 5000) return "fighter";

  // Bomber/heavy mil: military + large type codes
  if (isMilitary && (at.includes("B52") || at.includes("B1") || at.includes("B2") || at.includes("TU"))) return "bomber";

  // Generic military
  if (isMilitary) return "fighter";

  return "civilian";
}

const iconCache = new Map<string, string>();

export function getAircraftTypeIcon(
  type: AircraftIconType,
  headingDeg: number,
): string {
  const bucket = ((Math.round((headingDeg || 0) / 5) * 5) % 360 + 360) % 360;
  const key = `${type}_${bucket}`;

  const cached = iconCache.get(key);
  if (cached) return cached;

  const size = 24;
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d");
  if (!ctx) return canvas.toDataURL();

  const color = ICON_COLORS[type];

  ctx.translate(size / 2, size / 2);
  ctx.rotate((bucket * Math.PI) / 180);

  switch (type) {
    case "fighter":
      // Delta wings, narrow body
      ctx.beginPath();
      ctx.moveTo(0, -10);
      ctx.lineTo(-8, 6);
      ctx.lineTo(-3, 4);
      ctx.lineTo(-2, 8);
      ctx.lineTo(2, 8);
      ctx.lineTo(3, 4);
      ctx.lineTo(8, 6);
      ctx.closePath();
      break;

    case "bomber":
      // Swept wings, wide body
      ctx.beginPath();
      ctx.moveTo(0, -10);
      ctx.lineTo(-10, 4);
      ctx.lineTo(-4, 3);
      ctx.lineTo(-3, 8);
      ctx.lineTo(3, 8);
      ctx.lineTo(4, 3);
      ctx.lineTo(10, 4);
      ctx.closePath();
      break;

    case "transport_mil":
      // Wide body, straight wings
      ctx.beginPath();
      ctx.moveTo(0, -10);
      ctx.lineTo(-3, -2);
      ctx.lineTo(-10, -1);
      ctx.lineTo(-10, 2);
      ctx.lineTo(-3, 1);
      ctx.lineTo(-2, 8);
      ctx.lineTo(-5, 9);
      ctx.lineTo(-5, 10);
      ctx.lineTo(5, 10);
      ctx.lineTo(5, 9);
      ctx.lineTo(2, 8);
      ctx.lineTo(3, 1);
      ctx.lineTo(10, 2);
      ctx.lineTo(10, -1);
      ctx.lineTo(3, -2);
      ctx.closePath();
      break;

    case "helicopter":
      // Rotor disc + tail boom
      ctx.beginPath();
      ctx.arc(0, -1, 6, 0, Math.PI * 2); // rotor disc
      ctx.moveTo(-1, 5);
      ctx.lineTo(-1, 10);
      ctx.lineTo(1, 10);
      ctx.lineTo(1, 5); // tail boom
      ctx.moveTo(-3, 10);
      ctx.lineTo(3, 10); // tail rotor
      break;

    case "uav":
      // Narrow profile, small
      ctx.beginPath();
      ctx.moveTo(0, -8);
      ctx.lineTo(-6, 2);
      ctx.lineTo(-2, 1);
      ctx.lineTo(-1, 6);
      ctx.lineTo(1, 6);
      ctx.lineTo(2, 1);
      ctx.lineTo(6, 2);
      ctx.closePath();
      break;

    case "civilian":
    default:
      // Standard airliner
      ctx.beginPath();
      ctx.moveTo(0, -10);
      ctx.lineTo(-8, 4);
      ctx.lineTo(0, 2);
      ctx.lineTo(8, 4);
      ctx.closePath();
      break;
  }

  ctx.fillStyle = color;
  ctx.globalAlpha = 0.9;
  ctx.fill();
  ctx.globalAlpha = 1.0;
  ctx.strokeStyle = color;
  ctx.lineWidth = 0.5;
  ctx.stroke();

  const dataUrl = canvas.toDataURL();
  iconCache.set(key, dataUrl);
  return dataUrl;
}

export function clearAircraftIconCache(): void {
  iconCache.clear();
}
```

- [ ] **Step 2: Run type-check**

```bash
cd services/frontend && npx tsc --noEmit
```

- [ ] **Step 3: Commit**

```bash
git add services/frontend/src/components/layers/icons/aircraftIcons.ts
git commit -m "feat(frontend): add aircraft type icon factory with 6 silhouettes + heading cache"
```

---

## Task 3: FlightLayer — Type Icons + Trails + LOD Gate

**Files:**
- Modify: `services/frontend/src/components/layers/FlightLayer.tsx`

- [ ] **Step 1: Replace icon rendering with type-specific icons**

In `services/frontend/src/components/layers/FlightLayer.tsx`, replace the import section (line 1-3) with:

```typescript
import { useEffect, useRef } from "react";
import * as Cesium from "cesium";
import type { Aircraft } from "../../types";
import { classifyAircraft, getAircraftTypeIcon } from "./icons/aircraftIcons";
import { usePerformance, type DegradationLevel } from "../globe/PerformanceGuard";
```

- [ ] **Step 2: Add trail constants and PolylineCollection ref**

After the existing constants (line 23-25), add:

```typescript
const TRAIL_MAX_POSITIONS = 30;
const TRAIL_REDUCED_POSITIONS = 10;
```

Inside the `FlightLayer` component, after `interpolationTimerRef` (line 34), add:

```typescript
  const trailCollectionRef = useRef<Cesium.PolylineCollection | null>(null);
  const trailBuffersRef = useRef<Map<string, Cesium.Cartesian3[]>>(new Map());

  const { degradation } = usePerformance();
  const degradationRef = useRef<DegradationLevel>(degradation);
  degradationRef.current = degradation;
```

- [ ] **Step 3: Initialize trail PolylineCollection**

In the first `useEffect` (viewer lifecycle, line 36-58), add after `viewer.scene.primitives.add(collectionRef.current)` (line 42):

```typescript
      trailCollectionRef.current = new Cesium.PolylineCollection();
      viewer.scene.primitives.add(trailCollectionRef.current);
```

In the cleanup, add before `collectionRef.current = null` (line 52):

```typescript
        if (trailCollectionRef.current) {
          viewer.scene.primitives.remove(trailCollectionRef.current);
          trailCollectionRef.current = null;
        }
        trailBuffersRef.current.clear();
```

- [ ] **Step 4: Use type-specific icons in data update**

In the data update `useEffect` (line 60-152), replace the icon generation calls. Replace line 109-113 (the `existing.billboard.image` assignment):

```typescript
        const iconType = classifyAircraft(flight.callsign, flight.is_military, flight.aircraft_type, flight.altitude_m, flight.velocity_ms);
        existing.billboard.image = getAircraftTypeIcon(iconType, flight.heading);
```

Replace line 123 (the `image` in `bc.add`):

```typescript
          image: getAircraftTypeIcon(
            classifyAircraft(flight.callsign, flight.is_military, flight.aircraft_type, flight.altitude_m, flight.velocity_ms),
            flight.heading,
          ),
```

Remove the old `getAircraftIconCanvas` function (lines 223-266) entirely — it's replaced by the new icon factory.

Also remove the old `iconCacheRef` (line 33) — caching is now internal to `aircraftIcons.ts`.

- [ ] **Step 5: Add trail rendering to interpolation loop**

Replace the interpolation `useEffect` (lines 154-175) with an expanded version that updates trails:

```typescript
  useEffect(() => {
    if (interpolationTimerRef.current) {
      clearInterval(interpolationTimerRef.current);
      interpolationTimerRef.current = null;
    }

    if (!visible) return;

    interpolationTimerRef.current = setInterval(() => {
      const now = Date.now();
      const deg = degradationRef.current;
      const tc = trailCollectionRef.current;

      for (const [id, visual] of flightMapRef.current.entries()) {
        const newPos = projectPosition(visual, now);
        visual.billboard.position = newPos;

        // Trail: skip if degradation >= 3 (no trails)
        if (deg < 3 && tc) {
          let buffer = trailBuffersRef.current.get(id);
          if (!buffer) {
            buffer = [];
            trailBuffersRef.current.set(id, buffer);
          }

          buffer.push(newPos);

          const maxLen = deg >= 1 ? TRAIL_REDUCED_POSITIONS : TRAIL_MAX_POSITIONS;
          while (buffer.length > maxLen) {
            buffer.shift();
          }
        }
      }

      // Rebuild trail polylines (batched, not per-frame per-trail)
      if (tc && deg < 3) {
        tc.removeAll();
        for (const [id, buffer] of trailBuffersRef.current.entries()) {
          if (buffer.length < 2) continue;

          // Only draw trails for military aircraft when > 500 visible
          if (flightMapRef.current.size > 500) {
            const visual = flightMapRef.current.get(id);
            if (visual) {
              const flightData = (visual.billboard as unknown as Record<string, unknown>)?._flightData as { is_military?: boolean } | undefined;
              if (!flightData?.is_military) continue;
            }
          }

          tc.add({
            positions: buffer.slice(),
            width: 1.5,
            material: Cesium.Material.fromType("Color", {
              color: Cesium.Color.CYAN.withAlpha(0.3),
            }),
          });
        }
      }
    }, INTERPOLATION_INTERVAL_MS);

    return () => {
      if (interpolationTimerRef.current) {
        clearInterval(interpolationTimerRef.current);
        interpolationTimerRef.current = null;
      }
    };
  }, [visible]);
```

- [ ] **Step 6: Clean up stale trail buffers**

In the data update `useEffect`, after the stale flight removal loop (lines 146-151), add:

```typescript
    // Clean stale trail buffers
    for (const id of trailBuffersRef.current.keys()) {
      if (!activeIds.has(id)) {
        trailBuffersRef.current.delete(id);
      }
    }
```

- [ ] **Step 7: Add trail visibility toggle**

At the end of the visibility `useEffect` (after `bc.show = visible`), add:

```typescript
    if (trailCollectionRef.current) trailCollectionRef.current.show = visible;
```

- [ ] **Step 8: Run type-check**

```bash
cd services/frontend && npx tsc --noEmit
```

- [ ] **Step 9: Commit**

```bash
git add services/frontend/src/components/layers/FlightLayer.tsx
git commit -m "feat(frontend): add aircraft type icons + flight trails with LOD + perf guard"
```

---

## Task 4: Ship Type Icon Factory

**Files:**
- Create: `services/frontend/src/components/layers/icons/shipIcons.ts`

- [ ] **Step 1: Create ship icon factory**

Create `services/frontend/src/components/layers/icons/shipIcons.ts`:

```typescript
/**
 * Ship type-specific canvas icon factory.
 *
 * Classification: AIS ship_type numeric codes (IMO standard).
 */

export type ShipIconType = "warship" | "carrier" | "submarine" | "tanker" | "cargo" | "civilian";

export const ICON_COLORS: Record<ShipIconType, string> = {
  warship: "#ef4444",
  carrier: "#ef4444",
  submarine: "#ef4444",
  tanker: "#eab308",
  cargo: "#4fc3f7",
  civilian: "#d4cdc0",
};

export function classifyShip(shipType: number, name: string | null): ShipIconType {
  // AIS ship_type 35 = military
  if (shipType === 35) {
    const n = (name ?? "").toUpperCase();
    if (n.includes("CVN") || n.includes("CARRIER") || n.includes("NIMITZ") || n.includes("FORD")) return "carrier";
    if (n.includes("SSN") || n.includes("SSBN") || n.includes("SUBMARINE")) return "submarine";
    return "warship";
  }

  // Tanker: 80-89
  if (shipType >= 80 && shipType <= 89) return "tanker";

  // Cargo: 70-79
  if (shipType >= 70 && shipType <= 79) return "cargo";

  return "civilian";
}

const iconCache = new Map<string, HTMLCanvasElement>();

export function getShipTypeIcon(
  type: ShipIconType,
  courseDeg: number,
): HTMLCanvasElement {
  const bucket = ((Math.round((courseDeg || 0) / 5) * 5) % 360 + 360) % 360;
  const key = `${type}_${bucket}`;

  const cached = iconCache.get(key);
  if (cached) return cached;

  const size = 20;
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d");
  if (!ctx) return canvas;

  const color = ICON_COLORS[type];

  ctx.translate(size / 2, size / 2);
  ctx.rotate((bucket * Math.PI) / 180);

  switch (type) {
    case "warship":
      // Hull + superstructure + mast
      ctx.beginPath();
      ctx.moveTo(0, -8);
      ctx.lineTo(-4, 0);
      ctx.lineTo(-5, 6);
      ctx.lineTo(5, 6);
      ctx.lineTo(4, 0);
      ctx.closePath();
      ctx.fillStyle = color;
      ctx.globalAlpha = 0.9;
      ctx.fill();
      // Mast
      ctx.beginPath();
      ctx.moveTo(0, -8);
      ctx.lineTo(0, -4);
      ctx.strokeStyle = color;
      ctx.lineWidth = 1.5;
      ctx.stroke();
      break;

    case "carrier":
      // Flat deck + island
      ctx.beginPath();
      ctx.moveTo(0, -8);
      ctx.lineTo(-5, -2);
      ctx.lineTo(-5, 7);
      ctx.lineTo(5, 7);
      ctx.lineTo(5, -2);
      ctx.closePath();
      ctx.fillStyle = color;
      ctx.globalAlpha = 0.9;
      ctx.fill();
      // Island
      ctx.fillRect(3, -1, 2, 4);
      break;

    case "submarine":
      // Cigar hull + conning tower
      ctx.beginPath();
      ctx.ellipse(0, 1, 3, 8, 0, 0, Math.PI * 2);
      ctx.fillStyle = color;
      ctx.globalAlpha = 0.8;
      ctx.fill();
      // Conning tower
      ctx.fillRect(-1.5, -3, 3, 3);
      break;

    case "tanker":
      // Hull + round tanks
      ctx.beginPath();
      ctx.moveTo(0, -8);
      ctx.lineTo(-4, 0);
      ctx.lineTo(-4, 7);
      ctx.lineTo(4, 7);
      ctx.lineTo(4, 0);
      ctx.closePath();
      ctx.fillStyle = color;
      ctx.globalAlpha = 0.7;
      ctx.fill();
      // Tank circles
      ctx.globalAlpha = 0.5;
      ctx.beginPath();
      ctx.arc(0, 1, 2, 0, Math.PI * 2);
      ctx.fill();
      ctx.beginPath();
      ctx.arc(0, 5, 2, 0, Math.PI * 2);
      ctx.fill();
      break;

    case "cargo":
      // Hull + container stacks
      ctx.beginPath();
      ctx.moveTo(0, -8);
      ctx.lineTo(-5, 0);
      ctx.lineTo(-5, 7);
      ctx.lineTo(5, 7);
      ctx.lineTo(5, 0);
      ctx.closePath();
      ctx.fillStyle = color;
      ctx.globalAlpha = 0.8;
      ctx.fill();
      // Container rectangles
      ctx.globalAlpha = 0.5;
      ctx.fillRect(-3, 0, 6, 3);
      ctx.fillRect(-3, 4, 6, 2);
      break;

    case "civilian":
    default:
      // Small hull
      ctx.beginPath();
      ctx.moveTo(0, -6);
      ctx.lineTo(-3, 2);
      ctx.lineTo(-3, 5);
      ctx.lineTo(3, 5);
      ctx.lineTo(3, 2);
      ctx.closePath();
      ctx.fillStyle = color;
      ctx.globalAlpha = 0.8;
      ctx.fill();
      break;
  }

  ctx.globalAlpha = 1.0;
  ctx.strokeStyle = color;
  ctx.lineWidth = 0.5;
  ctx.stroke();

  iconCache.set(key, canvas);
  return canvas;
}
```

- [ ] **Step 2: Run type-check**

```bash
cd services/frontend && npx tsc --noEmit
```

- [ ] **Step 3: Commit**

```bash
git add services/frontend/src/components/layers/icons/shipIcons.ts
git commit -m "feat(frontend): add ship type icon factory with 5 silhouettes + course cache"
```

---

## Task 5: ShipLayer — Type Icons + Course Vectors

**Files:**
- Modify: `services/frontend/src/components/layers/ShipLayer.tsx`

- [ ] **Step 1: Replace ShipLayer with type icons + course vectors**

Replace the entire contents of `services/frontend/src/components/layers/ShipLayer.tsx`:

```typescript
import { useEffect, useRef, useCallback } from "react";
import * as Cesium from "cesium";
import type { Vessel } from "../../types";
import { classifyShip, getShipTypeIcon, ICON_COLORS } from "./icons/shipIcons";
import { usePerformance } from "../globe/PerformanceGuard";

interface ShipLayerProps {
  viewer: Cesium.Viewer | null;
  vessels: Vessel[];
  visible: boolean;
}

const COURSE_VECTOR_MINUTES = 5;
const KNOTS_TO_MS = 0.514444;
const EARTH_RADIUS_M = 6_378_137;
const LOD_ALTITUDE_THRESHOLD = 5_000_000;

/**
 * Renders AIS vessel positions with type-specific icons and course vectors.
 */
export function ShipLayer({ viewer, vessels, visible }: ShipLayerProps) {
  const collectionRef = useRef<Cesium.BillboardCollection | null>(null);
  const vectorCollectionRef = useRef<Cesium.PolylineCollection | null>(null);
  const { degradation } = usePerformance();

  useEffect(() => {
    if (!viewer || viewer.isDestroyed()) return;

    if (!collectionRef.current) {
      collectionRef.current = new Cesium.BillboardCollection({ scene: viewer.scene });
      viewer.scene.primitives.add(collectionRef.current);
    }
    if (!vectorCollectionRef.current) {
      vectorCollectionRef.current = new Cesium.PolylineCollection();
      viewer.scene.primitives.add(vectorCollectionRef.current);
    }

    return () => {
      if (!viewer.isDestroyed()) {
        if (collectionRef.current) viewer.scene.primitives.remove(collectionRef.current);
        if (vectorCollectionRef.current) viewer.scene.primitives.remove(vectorCollectionRef.current);
      }
      collectionRef.current = null;
      vectorCollectionRef.current = null;
    };
  }, [viewer]);

  // Render billboards (always) + course vectors (LOD-gated)
  const renderVessels = useCallback((showVectors: boolean) => {
    const bc = collectionRef.current;
    const vc = vectorCollectionRef.current;
    if (!bc || !vc) return;

    bc.removeAll();
    vc.removeAll();
    if (!visible) return;

    for (const vessel of vessels) {
      const position = Cesium.Cartesian3.fromDegrees(vessel.longitude, vessel.latitude, 0);
      const shipType = classifyShip(vessel.ship_type, vessel.name);

      const billboard = bc.add({
        position,
        image: getShipTypeIcon(shipType, vessel.course),
        scale: 0.6,
        eyeOffset: new Cesium.Cartesian3(0, 0, -50),
      });
      (billboard as unknown as Record<string, unknown>)._vesselData = {
        mmsi: vessel.mmsi,
        name: vessel.name,
        speed_knots: vessel.speed_knots,
        course: vessel.course,
        ship_type: vessel.ship_type,
        destination: vessel.destination,
        lat: vessel.latitude,
        lon: vessel.longitude,
      };

      // Course vector: line in heading direction, length proportional to speed
      if (showVectors && vessel.speed_knots > 0.5) {
        const speedMs = vessel.speed_knots * KNOTS_TO_MS;
        const distanceM = speedMs * COURSE_VECTOR_MINUTES * 60;
        const headingRad = Cesium.Math.toRadians(vessel.course);
        const latRad = Cesium.Math.toRadians(vessel.latitude);
        const lonRad = Cesium.Math.toRadians(vessel.longitude);

        const angDist = distanceM / EARTH_RADIUS_M;
        const endLat = Math.asin(
          Math.sin(latRad) * Math.cos(angDist) +
          Math.cos(latRad) * Math.sin(angDist) * Math.cos(headingRad),
        );
        const endLon = lonRad + Math.atan2(
          Math.sin(headingRad) * Math.sin(angDist) * Math.cos(latRad),
          Math.cos(angDist) - Math.sin(latRad) * Math.sin(endLat),
        );

        const endPosition = Cesium.Cartesian3.fromDegrees(
          Cesium.Math.toDegrees(endLon),
          Cesium.Math.toDegrees(endLat),
          0,
        );

        const vectorColor = Cesium.Color.fromCssColorString(
          ICON_COLORS[shipType] ?? ICON_COLORS.civilian
        ).withAlpha(0.4);

        vc.add({
          positions: [position, endPosition],
          width: 1.0,
          material: Cesium.Material.fromType("Color", { color: vectorColor }),
        });
      }
    }
  }, [vessels, visible]);

  // Re-render on data change
  useEffect(() => {
    if (!viewer || viewer.isDestroyed()) return;
    const cameraAlt = viewer.camera.positionCartographic.height;
    renderVessels(degradation < 3 && cameraAlt < LOD_ALTITUDE_THRESHOLD);
  }, [vessels, visible, viewer, degradation, renderVessels]);

  // Re-render vectors on camera move (LOD reactivity)
  const lastShowVectorsRef = useRef(false);

  useEffect(() => {
    if (!viewer || viewer.isDestroyed()) return;

    const onMoveEnd = () => {
      if (!viewer || viewer.isDestroyed()) return;
      const cameraAlt = viewer.camera.positionCartographic.height;
      const shouldShow = degradation < 3 && cameraAlt < LOD_ALTITUDE_THRESHOLD;

      // Only re-render if LOD state changed (avoids redundant work)
      if (shouldShow !== lastShowVectorsRef.current) {
        lastShowVectorsRef.current = shouldShow;
        renderVessels(shouldShow);
      }
    };

    viewer.camera.moveEnd.addEventListener(onMoveEnd);
    return () => {
      if (!viewer.isDestroyed()) viewer.camera.moveEnd.removeEventListener(onMoveEnd);
    };
  }, [viewer, degradation, renderVessels]);

  return null;
}
```

- [ ] **Step 2: Run type-check**

```bash
cd services/frontend && npx tsc --noEmit
```

- [ ] **Step 3: Commit**

```bash
git add services/frontend/src/components/layers/ShipLayer.tsx
git commit -m "feat(frontend): add ship type icons + course vectors with LOD gate"
```

---

## Task 6: Backend — Satellite Model Extension

**Files:**
- Modify: `services/backend/app/models/satellite.py`
- Modify: `services/backend/app/services/satellite_service.py`

- [ ] **Step 1: Extend Satellite Pydantic model**

Replace `services/backend/app/models/satellite.py`:

```python
"""Satellite data models."""

from pydantic import BaseModel


class Satellite(BaseModel):
    norad_id: int
    name: str
    tle_line1: str
    tle_line2: str
    category: str = "active"
    inclination_deg: float = 0.0
    period_min: float = 0.0
    operator_country: str | None = None
    satellite_type: str = "unknown"
```

- [ ] **Step 2: Add country mapping + type classification to service**

In `services/backend/app/services/satellite_service.py`, add after the `logger` line (line 13):

```python
# Name prefix → ISO 3166-1 alpha-2 country code
_COUNTRY_PREFIXES: dict[str, str] = {
    "USA ": "US", "NROL": "US", "NOSS": "US", "GPS ": "US", "NAVSTAR": "US",
    "DSP ": "US", "SBIRS": "US", "WGS ": "US", "GOES": "US", "NOAA": "US",
    "MILSTAR": "US", "AEHF": "US", "MUOS": "US", "TDRS": "US",
    "COSMOS": "RU", "GLONASS": "RU", "MOLNIYA": "RU",
    "YAOGAN": "CN", "CZ-": "CN", "BEIDOU": "CN", "FENGYUN": "CN", "TIANGONG": "CN",
    "GALILEO": "EU", "METEOSAT": "EU",
    "HIMAWARI": "JP", "QZS": "JP",
    "ASTRA": "LU",
    "INTELSAT": "INT", "IRIDIUM": "US", "STARLINK": "US", "ONEWEB": "GB",
}


def _detect_country(name: str) -> str | None:
    """Detect operator country from satellite name prefix."""
    upper = name.upper()
    for prefix, country in _COUNTRY_PREFIXES.items():
        if upper.startswith(prefix) or f" {prefix}" in upper:
            return country
    if "ISS" in upper:
        return "INT"
    return None


def _detect_type(name: str, category: str) -> str:
    """Detect satellite type from name + existing category."""
    upper = name.upper()
    if category == "military":
        # Sub-classify military — recon or comms (no generic "military" value)
        if any(k in upper for k in ("NROL", "USA ", "NOSS", "YAOGAN", "COSMOS 25")):
            return "recon"
        if any(k in upper for k in ("MILSTAR", "AEHF", "MUOS", "WGS", "DSCS")):
            return "comms"
        return "recon"  # conservative: unclassified mil → recon
    if category == "gps":
        return "gps"
    if category == "weather":
        return "weather"
    if category == "station":
        return "station"
    if any(k in upper for k in ("INTELSAT", "ASTRA", "SES", "VIASAT", "STARLINK", "ONEWEB", "IRIDIUM", "TDRS")):
        return "comms"
    return "unknown"
```

- [ ] **Step 3: Wire country + type into satellite construction**

In the same file, update the `Satellite(...)` constructor call inside `_fetch_celestrak` (around line 66-76). Replace:

```python
            satellites.append(
                Satellite(
                    norad_id=norad_id,
                    name=name,
                    tle_line1=line1,
                    tle_line2=line2,
                    category=category,
                    inclination_deg=round(inclination, 2),
                    period_min=round(period, 2),
                )
            )
```

With:

```python
            operator_country = _detect_country(name)
            sat_type = _detect_type(name, category)

            satellites.append(
                Satellite(
                    norad_id=norad_id,
                    name=name,
                    tle_line1=line1,
                    tle_line2=line2,
                    category=category,
                    inclination_deg=round(inclination, 2),
                    period_min=round(period, 2),
                    operator_country=operator_country,
                    satellite_type=sat_type,
                )
            )
```

- [ ] **Step 4: Run backend tests**

```bash
cd services/backend && uv run pytest tests/ -v
```

Expected: All pass (new fields have defaults, backward-compatible).

- [ ] **Step 5: Commit**

```bash
git add services/backend/app/models/satellite.py services/backend/app/services/satellite_service.py
git commit -m "feat(backend): add operator_country + satellite_type to Satellite model"
```

---

## Task 7: Frontend — Extend Satellite Type + Update SatelliteLayer

**Files:**
- Modify: `services/frontend/src/types/index.ts`
- Modify: `services/frontend/src/components/layers/SatelliteLayer.tsx`
- Modify: `services/frontend/src/components/globe/EntityClickHandler.tsx`

- [ ] **Step 1: Extend Satellite type**

In `services/frontend/src/types/index.ts`, replace the `Satellite` interface (lines 18-26):

```typescript
export interface Satellite {
  norad_id: number;
  name: string;
  tle_line1: string;
  tle_line2: string;
  category: string;
  inclination_deg: number;
  period_min: number;
  operator_country: string | null;
  satellite_type: string;
}
```

- [ ] **Step 2: Rewrite SatelliteLayer with orbit arcs, footprint hover, recon highlight**

Replace the entire contents of `services/frontend/src/components/layers/SatelliteLayer.tsx`:

```typescript
import { useEffect, useRef, useCallback } from "react";
import * as Cesium from "cesium";
import * as satellite from "satellite.js";
import type { Satellite } from "../../types";
import { usePerformance } from "../globe/PerformanceGuard";

interface SatelliteLayerProps {
  viewer: Cesium.Viewer | null;
  satellites: Satellite[];
  visible: boolean;
}

const CATEGORY_COLORS: Record<string, Cesium.Color> = {
  military: Cesium.Color.RED.withAlpha(0.8),
  weather: Cesium.Color.CYAN.withAlpha(0.8),
  gps: Cesium.Color.YELLOW.withAlpha(0.8),
  station: Cesium.Color.WHITE,
  geo: Cesium.Color.ORANGE.withAlpha(0.6),
  active: Cesium.Color.LIME.withAlpha(0.5),
};

const COUNTRY_TINT: Record<string, Cesium.Color> = {
  US: Cesium.Color.fromCssColorString("#3b82f6").withAlpha(0.6),
  RU: Cesium.Color.fromCssColorString("#ef4444").withAlpha(0.6),
  CN: Cesium.Color.fromCssColorString("#eab308").withAlpha(0.6),
  EU: Cesium.Color.fromCssColorString("#d4cdc0").withAlpha(0.6),
};

const ORBIT_ARC_POINTS = 50;
const ORBIT_LOD_ALTITUDE = 20_000_000;
const RECON_PREFIXES = ["USA ", "NROL", "COSMOS 25", "YAOGAN"];
const MIN_ELEVATION_DEG = 5;

function isReconSatellite(name: string): boolean {
  const upper = name.toUpperCase();
  return RECON_PREFIXES.some((p) => upper.startsWith(p));
}

function computeFootprintRadiusKm(altitudeKm: number): number {
  const earthR = 6371;
  const elevRad = (MIN_ELEVATION_DEG * Math.PI) / 180;
  const centralAngle = Math.acos(earthR / (earthR + altitudeKm)) - elevRad;
  return Math.max(0, earthR * centralAngle);
}

/**
 * Renders satellites with orbit arcs, recon highlights, and country-tinted orbits.
 */
export function SatelliteLayer({ viewer, satellites, visible }: SatelliteLayerProps) {
  const pointsRef = useRef<Cesium.PointPrimitiveCollection | null>(null);
  const orbitCollectionRef = useRef<Cesium.PolylineCollection | null>(null);
  const footprintRef = useRef<Cesium.Entity | null>(null);
  const { degradation } = usePerformance();

  // Initialize collections
  useEffect(() => {
    if (!viewer || viewer.isDestroyed()) return;

    if (!pointsRef.current) {
      pointsRef.current = new Cesium.PointPrimitiveCollection();
      viewer.scene.primitives.add(pointsRef.current);
    }
    if (!orbitCollectionRef.current) {
      orbitCollectionRef.current = new Cesium.PolylineCollection();
      viewer.scene.primitives.add(orbitCollectionRef.current);
    }

    return () => {
      if (!viewer.isDestroyed()) {
        if (pointsRef.current) viewer.scene.primitives.remove(pointsRef.current);
        if (orbitCollectionRef.current) viewer.scene.primitives.remove(orbitCollectionRef.current);
        if (footprintRef.current) viewer.entities.remove(footprintRef.current);
      }
      pointsRef.current = null;
      orbitCollectionRef.current = null;
      footprintRef.current = null;
    };
  }, [viewer]);

  // Propagate orbit arc positions for a satellite
  const propagateOrbitArc = useCallback((satrec: satellite.SatRec, startDate: Date): Cesium.Cartesian3[] => {
    const positions: Cesium.Cartesian3[] = [];
    for (let i = 0; i <= ORBIT_ARC_POINTS; i++) {
      const futureDate = new Date(startDate.getTime() + i * 60_000); // 1 min steps
      const posVel = satellite.propagate(satrec, futureDate);
      if (typeof posVel.position === "boolean" || !posVel.position) continue;
      const gmst = satellite.gstime(futureDate);
      const geo = satellite.eciToGeodetic(posVel.position, gmst);
      positions.push(
        Cesium.Cartesian3.fromDegrees(
          satellite.degreesLong(geo.longitude),
          satellite.degreesLat(geo.latitude),
          geo.height * 1000,
        ),
      );
    }
    return positions;
  }, []);

  // Render satellites + orbit arcs
  useEffect(() => {
    const pc = pointsRef.current;
    const oc = orbitCollectionRef.current;
    if (!pc || !oc || !viewer || viewer.isDestroyed()) return;

    pc.removeAll();
    oc.removeAll();
    if (!visible || satellites.length === 0) return;

    const now = new Date();
    const cameraAlt = viewer.camera.positionCartographic.height;
    const showOrbits = degradation < 3 && cameraAlt < ORBIT_LOD_ALTITUDE;

    for (const sat of satellites) {
      let satrec: satellite.SatRec;
      try {
        satrec = satellite.twoline2satrec(sat.tle_line1, sat.tle_line2);
      } catch {
        continue;
      }

      const posVel = satellite.propagate(satrec, now);
      if (typeof posVel.position === "boolean" || !posVel.position) continue;

      const gmst = satellite.gstime(now);
      const geo = satellite.eciToGeodetic(posVel.position, gmst);
      const lon = satellite.degreesLong(geo.longitude);
      const lat = satellite.degreesLat(geo.latitude);
      const alt = geo.height * 1000;

      const color = CATEGORY_COLORS[sat.category] ?? CATEGORY_COLORS["active"]!;
      const isRecon = isReconSatellite(sat.name);

      const point = pc.add({
        position: Cesium.Cartesian3.fromDegrees(lon, lat, alt),
        pixelSize: isRecon ? 10 : sat.category === "station" ? 8 : 3,
        color: isRecon ? Cesium.Color.RED : color,
      });

      (point as unknown as Record<string, unknown>)._satelliteData = {
        norad_id: sat.norad_id,
        name: sat.name,
        category: sat.category,
        inclination_deg: sat.inclination_deg,
        period_min: sat.period_min,
        altitude_km: geo.height,
        operator_country: sat.operator_country,
        satellite_type: sat.satellite_type,
        footprint_radius_km: Math.round(computeFootprintRadiusKm(geo.height)),
        lat,
        lon,
      };

      // Orbit arc
      if (showOrbits && sat.category !== "geo") {
        const orbitPositions = propagateOrbitArc(satrec, now);
        if (orbitPositions.length >= 2) {
          const orbitColor = sat.operator_country
            ? (COUNTRY_TINT[sat.operator_country] ?? color.withAlpha(0.3))
            : color.withAlpha(0.3);

          oc.add({
            positions: orbitPositions,
            width: 1.0,
            material: Cesium.Material.fromType("Color", { color: orbitColor }),
          });
        }
      }
    }
  }, [satellites, visible, viewer, degradation, propagateOrbitArc]);

  // Orbit LOD reactivity on camera move — re-render orbits when crossing threshold
  const lastShowOrbitsRef = useRef(false);

  useEffect(() => {
    if (!viewer || viewer.isDestroyed()) return;

    const onMoveEnd = () => {
      if (!viewer || viewer.isDestroyed()) return;
      const cameraAlt = viewer.camera.positionCartographic.height;
      const shouldShow = degradation < 3 && cameraAlt < ORBIT_LOD_ALTITUDE;

      if (shouldShow !== lastShowOrbitsRef.current) {
        lastShowOrbitsRef.current = shouldShow;
        const oc = orbitCollectionRef.current;
        if (!oc) return;

        if (shouldShow && oc.length === 0) {
          // Orbits weren't built on last render — build them now
          const now = new Date();
          for (const sat of satellites) {
            if (sat.category === "geo") continue;
            let satrec: satellite.SatRec;
            try { satrec = satellite.twoline2satrec(sat.tle_line1, sat.tle_line2); } catch { continue; }
            const orbitPositions = propagateOrbitArc(satrec, now);
            if (orbitPositions.length < 2) continue;
            const color = CATEGORY_COLORS[sat.category] ?? CATEGORY_COLORS["active"]!;
            const orbitColor = sat.operator_country
              ? (COUNTRY_TINT[sat.operator_country] ?? color.withAlpha(0.3))
              : color.withAlpha(0.3);
            oc.add({
              positions: orbitPositions,
              width: 1.0,
              material: Cesium.Material.fromType("Color", { color: orbitColor }),
            });
          }
        }
        oc.show = shouldShow;
      }
    };

    viewer.camera.moveEnd.addEventListener(onMoveEnd);
    return () => {
      if (!viewer.isDestroyed()) viewer.camera.moveEnd.removeEventListener(onMoveEnd);
    };
  }, [viewer, degradation, satellites, propagateOrbitArc]);

  // Footprint on hover
  useEffect(() => {
    if (!viewer || viewer.isDestroyed()) return;

    const handler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas);

    handler.setInputAction((movement: Cesium.ScreenSpaceEventHandler.MotionEvent) => {
      const picked = viewer.scene.pick(movement.endPosition);
      const satData = (picked?.primitive as Record<string, unknown>)?._satelliteData as
        | { footprint_radius_km?: number; lat: number; lon: number }
        | undefined;

      // Remove previous footprint
      if (footprintRef.current) {
        viewer.entities.remove(footprintRef.current);
        footprintRef.current = null;
      }

      if (satData && satData.footprint_radius_km && satData.footprint_radius_km > 0) {
        const category = (picked?.primitive as Record<string, unknown>)?._satelliteData as { category?: string } | undefined;
        const color = CATEGORY_COLORS[category?.category ?? "active"] ?? CATEGORY_COLORS["active"]!;

        footprintRef.current = viewer.entities.add({
          position: Cesium.Cartesian3.fromDegrees(satData.lon, satData.lat, 0),
          ellipse: {
            semiMajorAxis: satData.footprint_radius_km * 1000,
            semiMinorAxis: satData.footprint_radius_km * 1000,
            material: color.withAlpha(0.12),
            outline: true,
            outlineColor: color.withAlpha(0.3),
            outlineWidth: 1,
          },
        });
      }
    }, Cesium.ScreenSpaceEventType.MOUSE_MOVE);

    return () => handler.destroy();
  }, [viewer]);

  return null;
}
```

- [ ] **Step 3: Update EntityClickHandler for extended satellite popup**

In `services/frontend/src/components/globe/EntityClickHandler.tsx`, replace the satellite data type cast (lines 202-212) with:

```typescript
      const satData = (picked?.primitive as Record<string, unknown>)?._satelliteData as
        | {
            norad_id: number;
            name: string;
            category: string;
            inclination_deg: number;
            period_min: number;
            altitude_km: number;
            operator_country: string | null;
            satellite_type: string;
            footprint_radius_km: number;
            lat: number;
            lon: number;
          }
        | undefined;
```

Replace the satellite properties block (lines 216-222) with:

```typescript
        const props: Record<string, string> = {};
        props.norad = String(satData.norad_id);
        props.category = satData.category.toUpperCase();
        if (satData.operator_country) props.country = satData.operator_country;
        if (satData.satellite_type !== "unknown") props.type = satData.satellite_type.toUpperCase();
        props.altitude = `${Math.round(satData.altitude_km).toLocaleString()} km`;
        props.inclination = `${satData.inclination_deg.toFixed(1)}°`;
        props.period = `${satData.period_min.toFixed(1)} min`;
        props.footprint = `${satData.footprint_radius_km.toLocaleString()} km`;
```

- [ ] **Step 4: Run type-check**

```bash
cd services/frontend && npx tsc --noEmit
```

- [ ] **Step 5: Commit**

```bash
git add services/frontend/src/types/index.ts services/frontend/src/components/layers/SatelliteLayer.tsx services/frontend/src/components/globe/EntityClickHandler.tsx
git commit -m "feat(frontend): add satellite orbit arcs, footprint hover, recon highlight, country tint"
```

---

## Task 8: EarthquakeLayer — Pulse Animation

**Files:**
- Modify: `services/frontend/src/components/layers/EarthquakeLayer.tsx`

- [ ] **Step 1: Add pulse animation to EarthquakeLayer**

Replace the entire contents of `services/frontend/src/components/layers/EarthquakeLayer.tsx`:

```typescript
import { useEffect, useRef } from "react";
import * as Cesium from "cesium";
import type { Earthquake } from "../../types";
import { usePerformance } from "../globe/PerformanceGuard";

interface EarthquakeLayerProps {
  viewer: Cesium.Viewer | null;
  earthquakes: Earthquake[];
  visible: boolean;
}

function magnitudeToColor(mag: number): Cesium.Color {
  if (mag >= 7.0) return Cesium.Color.RED;
  if (mag >= 6.0) return Cesium.Color.ORANGE;
  if (mag >= 5.0) return Cesium.Color.YELLOW;
  return Cesium.Color.LIME;
}

function magnitudeToSize(mag: number): number {
  return Math.max(6, Math.pow(2, mag - 3));
}

interface QuakePulse {
  billboard: Cesium.Billboard;
  ringBillboard: Cesium.Billboard;
  magnitude: number;
  eventTimeMs: number;
  baseSize: number;
  color: Cesium.Color;
}

/**
 * Renders earthquakes with magnitude-based pulse animations.
 * - M >= 7.0: permanent pulse
 * - M >= 5.0: 30-second pulse after event, then static
 * - M < 5.0: single ripple then static
 */
export function EarthquakeLayer({ viewer, earthquakes, visible }: EarthquakeLayerProps) {
  const collectionRef = useRef<Cesium.BillboardCollection | null>(null);
  const labelCollectionRef = useRef<Cesium.LabelCollection | null>(null);
  const pulsesRef = useRef<QuakePulse[]>([]);
  const animFrameRef = useRef<number | null>(null);
  const { degradation } = usePerformance();
  const degradationRef = useRef(degradation);
  degradationRef.current = degradation;

  useEffect(() => {
    if (!viewer || viewer.isDestroyed()) return;

    if (!collectionRef.current) {
      collectionRef.current = new Cesium.BillboardCollection({ scene: viewer.scene });
      viewer.scene.primitives.add(collectionRef.current);
    }
    if (!labelCollectionRef.current) {
      labelCollectionRef.current = new Cesium.LabelCollection({ scene: viewer.scene });
      viewer.scene.primitives.add(labelCollectionRef.current);
    }

    return () => {
      if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);
      if (!viewer.isDestroyed()) {
        if (collectionRef.current) viewer.scene.primitives.remove(collectionRef.current);
        if (labelCollectionRef.current) viewer.scene.primitives.remove(labelCollectionRef.current);
      }
      collectionRef.current = null;
      labelCollectionRef.current = null;
      pulsesRef.current = [];
    };
  }, [viewer]);

  // Render quakes
  useEffect(() => {
    const bc = collectionRef.current;
    const lc = labelCollectionRef.current;
    if (!bc || !lc) return;

    bc.removeAll();
    lc.removeAll();
    pulsesRef.current = [];

    if (!visible) return;

    for (const quake of earthquakes) {
      const position = Cesium.Cartesian3.fromDegrees(quake.longitude, quake.latitude, 0);
      const color = magnitudeToColor(quake.magnitude);
      const size = magnitudeToSize(quake.magnitude);

      // Inner dot (static)
      const billboard = bc.add({
        position,
        image: createQuakeDot(size * 0.4, color),
        scale: 1.0,
        eyeOffset: new Cesium.Cartesian3(0, 0, -50),
      });

      // Outer ring (animated — expanding + fading)
      const ringBillboard = bc.add({
        position,
        image: createQuakeRing(size, color),
        scale: 1.0,
        eyeOffset: new Cesium.Cartesian3(0, 0, -49),
      });

      lc.add({
        position,
        text: `M${quake.magnitude.toFixed(1)}`,
        font: "11px monospace",
        fillColor: color,
        outlineColor: Cesium.Color.BLACK,
        outlineWidth: 2,
        style: Cesium.LabelStyle.FILL_AND_OUTLINE,
        pixelOffset: new Cesium.Cartesian2(0, -size - 5),
        eyeOffset: new Cesium.Cartesian3(0, 0, -50),
      });

      pulsesRef.current.push({
        billboard,
        ringBillboard,
        magnitude: quake.magnitude,
        eventTimeMs: new Date(quake.time).getTime(),
        baseSize: size,
        color,
      });
    }
  }, [earthquakes, visible]);

  // Pulse animation loop
  useEffect(() => {
    if (!visible) {
      if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);
      return;
    }

    const animate = () => {
      const now = Date.now();
      const deg = degradationRef.current;

      if (deg < 2) {
        for (const pulse of pulsesRef.current) {
          const ageMs = now - pulse.eventTimeMs;
          const ageSec = ageMs / 1000;
          let ringScale = 1.0;
          let ringAlpha = 0.8;

          if (pulse.magnitude >= 7.0) {
            // Permanent pulse: ring expands + fades cyclically
            const phase = (now * 0.003) % (Math.PI * 2);
            ringScale = 1.0 + 0.5 * Math.sin(phase);
            ringAlpha = 0.8 - 0.4 * Math.sin(phase);
          } else if (pulse.magnitude >= 5.0 && ageSec < 30) {
            // 30-second pulse
            const phase = (now * 0.005) % (Math.PI * 2);
            ringScale = 1.0 + 0.3 * Math.sin(phase);
            ringAlpha = 0.8 - 0.3 * Math.sin(phase);
          } else if (pulse.magnitude < 5.0) {
            // Single ripple: expand + fade out in first 3 seconds, then static
            if (ageSec < 3.0) {
              const t = ageSec / 3.0;
              ringScale = 1.0 + t * 0.5;
              ringAlpha = 0.8 * (1.0 - t);
            } else {
              ringScale = 1.0;
              ringAlpha = 0.0; // ring hidden after ripple
            }
          }

          // Inner dot stays static, outer ring animates
          pulse.ringBillboard.scale = ringScale;
          pulse.ringBillboard.color = pulse.color.withAlpha(ringAlpha);
        }
      }

      animFrameRef.current = requestAnimationFrame(animate);
    };

    animFrameRef.current = requestAnimationFrame(animate);

    return () => {
      if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);
    };
  }, [visible]);

  return null;
}

function createQuakeDot(radius: number, color: Cesium.Color): HTMLCanvasElement {
  const canvasSize = Math.ceil(radius * 4);
  const canvas = document.createElement("canvas");
  canvas.width = canvasSize;
  canvas.height = canvasSize;
  const ctx = canvas.getContext("2d");
  if (!ctx) return canvas;

  const center = canvasSize / 2;
  ctx.beginPath();
  ctx.arc(center, center, radius, 0, Math.PI * 2);
  ctx.fillStyle = `rgba(${color.red * 255}, ${color.green * 255}, ${color.blue * 255}, 0.9)`;
  ctx.fill();

  return canvas;
}

function createQuakeRing(size: number, color: Cesium.Color): HTMLCanvasElement {
  const canvasSize = Math.ceil(size * 4);
  const canvas = document.createElement("canvas");
  canvas.width = canvasSize;
  canvas.height = canvasSize;
  const ctx = canvas.getContext("2d");
  if (!ctx) return canvas;

  const center = canvasSize / 2;

  // Two concentric rings
  ctx.beginPath();
  ctx.arc(center, center, size, 0, Math.PI * 2);
  ctx.strokeStyle = `rgba(${color.red * 255}, ${color.green * 255}, ${color.blue * 255}, 0.8)`;
  ctx.lineWidth = 2;
  ctx.stroke();

  ctx.beginPath();
  ctx.arc(center, center, size * 0.65, 0, Math.PI * 2);
  ctx.strokeStyle = `rgba(${color.red * 255}, ${color.green * 255}, ${color.blue * 255}, 0.4)`;
  ctx.lineWidth = 1.5;
  ctx.stroke();

  return canvas;
}
```

- [ ] **Step 2: Run type-check**

```bash
cd services/frontend && npx tsc --noEmit
```

- [ ] **Step 3: Commit**

```bash
git add services/frontend/src/components/layers/EarthquakeLayer.tsx
git commit -m "feat(frontend): add magnitude-based earthquake pulse animations"
```

---

## Task 9: EventLayer — Severity-Based Pulse

**Files:**
- Modify: `services/frontend/src/components/layers/EventLayer.tsx`

- [ ] **Step 1: Add pulse animation to EventLayer**

Replace the entire contents of `services/frontend/src/components/layers/EventLayer.tsx`:

```typescript
import { useEffect, useRef } from "react";
import * as Cesium from "cesium";
import type { IntelEvent } from "../../types";
import { usePerformance } from "../globe/PerformanceGuard";

interface EventLayerProps {
  viewer: Cesium.Viewer | null;
  events: IntelEvent[];
  visible: boolean;
}

const EVENT_COLORS: Record<string, string> = {
  military: "#ef4444",
  space: "#06b6d4",
  cyber: "#a855f7",
  political: "#f97316",
  economic: "#eab308",
  environmental: "#22c55e",
};

const DEFAULT_COLOR = "#6b7280";

function getCategoryColor(codebook_type: string): string {
  const category = codebook_type.split(".")[0] ?? "";
  return EVENT_COLORS[category] ?? DEFAULT_COLOR;
}

interface EventPulse {
  billboard: Cesium.Billboard;
  severity: string;
}

/**
 * Renders intel events with severity-based pulse animations.
 * - critical: fast pulse (2 Hz)
 * - high: slow pulse (0.5 Hz)
 * - medium/low: static marker
 */
export function EventLayer({ viewer, events, visible }: EventLayerProps) {
  const collectionRef = useRef<Cesium.BillboardCollection | null>(null);
  const labelCollectionRef = useRef<Cesium.LabelCollection | null>(null);
  const pulsesRef = useRef<EventPulse[]>([]);
  const animFrameRef = useRef<number | null>(null);
  const { degradation } = usePerformance();
  const degradationRef = useRef(degradation);
  degradationRef.current = degradation;

  useEffect(() => {
    if (!viewer || viewer.isDestroyed()) return;

    if (!collectionRef.current) {
      collectionRef.current = new Cesium.BillboardCollection({ scene: viewer.scene });
      viewer.scene.primitives.add(collectionRef.current);
    }
    if (!labelCollectionRef.current) {
      labelCollectionRef.current = new Cesium.LabelCollection({ scene: viewer.scene });
      viewer.scene.primitives.add(labelCollectionRef.current);
    }

    return () => {
      if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);
      if (!viewer.isDestroyed()) {
        if (collectionRef.current) viewer.scene.primitives.remove(collectionRef.current);
        if (labelCollectionRef.current) viewer.scene.primitives.remove(labelCollectionRef.current);
      }
      collectionRef.current = null;
      labelCollectionRef.current = null;
      pulsesRef.current = [];
    };
  }, [viewer]);

  useEffect(() => {
    const bc = collectionRef.current;
    const lc = labelCollectionRef.current;
    if (!bc || !lc) return;

    bc.removeAll();
    lc.removeAll();
    pulsesRef.current = [];

    if (!visible) return;

    for (const event of events) {
      if (event.lat == null || event.lon == null) continue;

      const position = Cesium.Cartesian3.fromDegrees(event.lon, event.lat, 0);
      const color = getCategoryColor(event.codebook_type);

      const billboard = bc.add({
        position,
        image: createEventCanvas(color),
        scale: 1.0,
        eyeOffset: new Cesium.Cartesian3(0, 0, -100),
      });

      (billboard as unknown as Record<string, unknown>)._eventData = {
        id: event.id,
        title: event.title,
        codebook_type: event.codebook_type,
        severity: event.severity,
        location_name: event.location_name,
        lat: event.lat,
        lon: event.lon,
      };

      const label = event.title.length > 20 ? event.title.slice(0, 18) + "…" : event.title;
      lc.add({
        position,
        text: label,
        font: "10px monospace",
        fillColor: Cesium.Color.fromCssColorString(color),
        outlineColor: Cesium.Color.BLACK,
        outlineWidth: 2,
        style: Cesium.LabelStyle.FILL_AND_OUTLINE,
        pixelOffset: new Cesium.Cartesian2(0, -18),
        eyeOffset: new Cesium.Cartesian3(0, 0, -100),
      });

      if (event.severity === "critical" || event.severity === "high") {
        pulsesRef.current.push({ billboard, severity: event.severity });
      }
    }
  }, [events, visible]);

  // Pulse animation loop
  useEffect(() => {
    if (!visible) {
      if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);
      return;
    }

    const animate = () => {
      const now = Date.now();
      const deg = degradationRef.current;

      if (deg < 2) {
        for (const pulse of pulsesRef.current) {
          if (pulse.severity === "critical") {
            // 2 Hz fast pulse
            pulse.billboard.scale = 1.0 + 0.3 * Math.sin(now * 0.0126);
          } else if (pulse.severity === "high") {
            // 0.5 Hz slow pulse
            pulse.billboard.scale = 1.0 + 0.15 * Math.sin(now * 0.00314);
          }
        }
      }

      animFrameRef.current = requestAnimationFrame(animate);
    };

    animFrameRef.current = requestAnimationFrame(animate);

    return () => {
      if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);
    };
  }, [visible]);

  return null;
}

function createEventCanvas(color: string): HTMLCanvasElement {
  const size = 24;
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d");
  if (!ctx) return canvas;

  const cx = size / 2;
  const cy = size / 2;
  const r = 8;

  ctx.beginPath();
  ctx.moveTo(cx, cy - r);
  ctx.lineTo(cx + r, cy);
  ctx.lineTo(cx, cy + r);
  ctx.lineTo(cx - r, cy);
  ctx.closePath();
  ctx.fillStyle = color;
  ctx.globalAlpha = 0.85;
  ctx.fill();
  ctx.globalAlpha = 1.0;
  ctx.strokeStyle = color;
  ctx.lineWidth = 1.5;
  ctx.stroke();

  return canvas;
}
```

- [ ] **Step 2: Run type-check**

```bash
cd services/frontend && npx tsc --noEmit
```

- [ ] **Step 3: Commit**

```bash
git add services/frontend/src/components/layers/EventLayer.tsx
git commit -m "feat(frontend): add severity-based event pulse animations (critical=2Hz, high=0.5Hz)"
```

---

## Task 10: Final Verification

- [ ] **Step 1: Run full type-check**

```bash
cd services/frontend && npx tsc --noEmit
```

Expected: No errors.

- [ ] **Step 2: Run lint**

```bash
cd services/frontend && npm run lint
```

Expected: No new errors.

- [ ] **Step 3: Run backend tests**

```bash
cd services/backend && uv run pytest tests/ -v
```

Expected: All pass.

- [ ] **Step 4: Visual verification checklist**

```bash
cd services/frontend && npm run dev
```

- [ ] Aircraft: Fighter (delta), transport (straight wings), helicopter (rotor), civilian (airliner) visually distinct
- [ ] Aircraft: Military = red, civilian = bone, UAV = purple
- [ ] Flight trails: fading polylines behind moving aircraft
- [ ] Flight trails: only military trails when > 500 visible flights
- [ ] Ships: Warship, tanker, cargo, civilian visually distinct
- [ ] Ship course vectors: lines in heading direction proportional to speed
- [ ] Ship course vectors: hidden when zoomed out > 5M meters
- [ ] Satellites: orbit arcs visible when zoomed in < 20M meters
- [ ] Satellites: recon satellites have larger dots (6px vs 3px)
- [ ] Satellites: orbit arcs tinted by country (US=blue, RU=red, CN=yellow)
- [ ] Satellite hover: footprint circle appears on Earth surface
- [ ] Satellite click: shows country, type, footprint radius
- [ ] Earthquakes: M >= 7 permanent pulse, M >= 5 timed pulse, M < 5 static
- [ ] Events: critical = fast pulse, high = slow pulse, medium/low = static
- [ ] Performance: StatusBar shows FPS from PerformanceGuard
- [ ] Performance: FPS stays >= 30 with all layers active
- [ ] Degradation: artificially throttle CPU — animations should degrade gracefully

- [ ] **Step 5: Commit any remaining fixes**

```bash
git status
# Only commit if there are actual fixes needed
```
