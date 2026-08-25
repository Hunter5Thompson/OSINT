/**
 * Adapted from God's Eye View, commit 880a672b5e16ad3e41d318801d3a5203f9201923
 * Copyright (c) 2026 Bilawal Sidhu. MIT License — full text in
 * LICENSES/gods-eye-view-MIT.txt. See THIRD_PARTY_NOTICES.md.
 */

import { LOCAL_ALTITUDE_M } from "./lod";

/** Camera height (m) below which labels use street-scale budget. */
const STREET_ALTITUDE_M = 50_000;
/** Camera height (m) below which labels use city-scale budget. */
const CITY_ALTITUDE_M = 250_000;
/** Camera height (m) below which labels use metro-scale budget (= LOCAL_ALTITUDE_M). */
const METRO_ALTITUDE_M = LOCAL_ALTITUDE_M; // 1_000_000
// Above metro, everything is regional. GLOBE_ALTITUDE_M (8e6) is not a label
// cut: Task 10 Option B deleted the global row (DDC draws nothing above ~5e6).

export type LabelViewScale = "street" | "city" | "metro" | "regional";
export type DensityStop = 0 | 25 | 50 | 75 | 100;
export type DensityProfile = "SPARSE" | "BALANCED" | "DENSE";

export const DENSITY_STOPS: readonly DensityStop[] = Object.freeze([0, 25, 50, 75, 100] as const);

/**
 * Collective label budgets by view scale × density stop.
 *
 * Task 10 Option B (2026-08-25 measurement): the DistanceDisplayCondition on
 * every label layer draws nothing above ~5 000 km. The `global` row (≥8e6 m)
 * governed an empty set and is deleted. Altitudes at/above GLOBE_ALTITUDE_M
 * fold into `regional`. Numbers remain provisional pending visual calibration
 * inside the live envelope (0 – ~5 000 km).
 */
export const VIEW_SCALE_BUDGETS = Object.freeze({
  street: Object.freeze({ 0: 8, 25: 20, 50: 40, 75: 60, 100: 80 }),
  city: Object.freeze({ 0: 6, 25: 16, 50: 32, 75: 48, 100: 64 }),
  metro: Object.freeze({ 0: 5, 25: 12, 50: 24, 75: 36, 100: 48 }),
  regional: Object.freeze({ 0: 4, 25: 10, 50: 20, 75: 30, 100: 40 }),
});

export function labelViewScaleForAltitude(altitudeM: number): LabelViewScale {
  if (!Number.isFinite(altitudeM)) return "regional";
  if (altitudeM < STREET_ALTITUDE_M) return "street";
  if (altitudeM < CITY_ALTITUDE_M) return "city";
  if (altitudeM < METRO_ALTITUDE_M) return "metro";
  return "regional";
}

export function canonicalizeDensity(density: number, fallback = 50): DensityStop {
  if (!Number.isFinite(density)) {
    const fb = Number.isFinite(fallback) ? fallback : 50;
    return canonicalizeDensity(fb, 50);
  }
  const clamped = Math.min(100, Math.max(0, density));
  if (clamped < 12.5) return 0;
  if (clamped <= 25) return 25;
  if (clamped < 75) return 50;
  if (clamped < 87.5) return 75;
  return 100;
}

export function profileForDensity(stop: DensityStop): DensityProfile {
  if (stop <= 25) return "SPARSE";
  if (stop >= 75) return "DENSE";
  return "BALANCED";
}

export function defaultDensityForProfile(profile: DensityProfile): DensityStop {
  if (profile === "SPARSE") return 25;
  if (profile === "DENSE") return 75;
  return 50;
}

export function labelBudgetFor(altitudeM: number, density: number): number {
  const scale = labelViewScaleForAltitude(altitudeM);
  const stop = canonicalizeDensity(density);
  return VIEW_SCALE_BUDGETS[scale][stop];
}
