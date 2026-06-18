import type * as Cesium from "cesium";

/**
 * Stage-1 photoreal-tiles performance tuning — the ONLY two values that differ
 * from the Cesium 1.139.1 defaults. See
 * docs/superpowers/specs/2026-06-18-photoreal-tiles-loading-perf-design.md.
 *
 * - maximumScreenSpaceError: 8 (Cesium default 16; the old code used 2, which
 *   demanded ~8x finer tiles everywhere → constant loading sluggishness).
 * - cacheBytes: 1 GiB (Cesium default 512 MiB; reduces re-downloads when
 *   panning back to a previously visited area).
 */
export const PHOTOREAL_TUNING = {
  maximumScreenSpaceError: 8,
  cacheBytes: 1024 * 1024 * 1024, // 1 GiB
} as const;

/**
 * Apply the Stage-1 tuning to a 3D tileset. Tileset-type-neutral: used for both
 * the Google photoreal tileset and the OSM-buildings fallback.
 */
export function applyTilesetPerformanceConfig(tileset: Cesium.Cesium3DTileset): void {
  tileset.maximumScreenSpaceError = PHOTOREAL_TUNING.maximumScreenSpaceError;
  tileset.cacheBytes = PHOTOREAL_TUNING.cacheBytes;
}
