import * as Cesium from "cesium";

/** Camera-altitude bands shared by all globe layers (single source of truth). */
export type AltitudeBand = "GLOBE" | "REGIONAL" | "LOCAL";

/** At/above this camera height (m) we are at globe scale (mega-constellations hidden, aggregates only). */
export const GLOBE_ALTITUDE_M = 8_000_000;
/** Below this camera height (m) we are at local scale (labels + fine detail). */
export const LOCAL_ALTITUDE_M = 1_000_000;
/** Orbit arcs / space polylines stay visible up to this camera height (LEO..GEO). */
export const ORBIT_LOD_ALTITUDE_M = 45_000_000;

export function bandForHeight(height: number): AltitudeBand {
  if (height >= GLOBE_ALTITUDE_M) return "GLOBE";
  if (height < LOCAL_ALTITUDE_M) return "LOCAL";
  return "REGIONAL";
}

export interface ViewBounds {
  south: number;
  north: number;
  west: number;
  east: number;
}

/** Current viewport bounds in degrees, or null if the globe fills the view (→ no culling). */
export function getViewBounds(viewer: Cesium.Viewer): ViewBounds | null {
  const rect = viewer.camera.computeViewRectangle(viewer.scene.globe.ellipsoid);
  if (!rect) return null;
  return {
    south: Cesium.Math.toDegrees(rect.south),
    north: Cesium.Math.toDegrees(rect.north),
    west: Cesium.Math.toDegrees(rect.west),
    east: Cesium.Math.toDegrees(rect.east),
  };
}

/** True if (lon,lat) lies within bounds. Handles anti-meridian wrap (west > east). */
export function inViewBounds(lon: number, lat: number, bounds: ViewBounds | null): boolean {
  if (!bounds) return true;
  if (lat < bounds.south || lat > bounds.north) return false;
  if (bounds.west <= bounds.east) {
    return lon >= bounds.west && lon <= bounds.east;
  }
  return lon >= bounds.west || lon <= bounds.east;
}

export interface SelectOptions<T> {
  cap: number;
  /** Higher rank = kept first when the cap bites. Omit to keep input order. */
  rank?: (item: T) => number;
}

/**
 * Cull items to the viewport, then cap the count keeping the highest-ranked.
 * Pure (no Cesium) → fully unit-testable. Layers call this once per render.
 */
export function selectVisible<T>(
  items: readonly T[],
  getLonLat: (item: T) => readonly [number, number] | null,
  bounds: ViewBounds | null,
  opts: SelectOptions<T>,
): T[] {
  const inView: T[] = [];
  for (const item of items) {
    const ll = getLonLat(item);
    if (!ll) continue;
    if (inViewBounds(ll[0], ll[1], bounds)) inView.push(item);
  }
  if (opts.rank) {
    const rank = opts.rank;
    inView.sort((a, b) => rank(b) - rank(a));
  }
  return inView.length > opts.cap ? inView.slice(0, opts.cap) : inView;
}

/** Shared distance attenuation for bulk billboards — full size/opacity near, faded far. */
export function bulkScaleByDistance(): Cesium.NearFarScalar {
  return new Cesium.NearFarScalar(100_000, 1.0, 12_000_000, 0.45);
}
export function bulkTranslucencyByDistance(): Cesium.NearFarScalar {
  return new Cesium.NearFarScalar(100_000, 1.0, 14_000_000, 0.35);
}
