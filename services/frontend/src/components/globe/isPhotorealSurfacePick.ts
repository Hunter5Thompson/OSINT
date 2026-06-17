// services/frontend/src/components/globe/isPhotorealSurfacePick.ts
import type * as Cesium from "cesium";

/**
 * True when a Cesium pick result is THE photorealistic globe surface — the
 * Google 3D Tiles tileset (or its OSM-buildings fallback) created by
 * GlobeViewer — rather than a real UI / data-layer primitive.
 *
 * Used by EntityClickHandler so a click that lands on the 3D surface still
 * falls through to the country hit-test (almanac), instead of being swallowed
 * by the tileset (the "almanac only works on the political/flat map" bug).
 *
 * Contract: classification requires POSITIVE identification of OUR tileset —
 * either reference-equality against the passed `photorealTileset`, OR the
 * `_odinPhotoreal` marker that GlobeViewer stamps on the tileset at creation
 * (the marker is reachable from a picked tile feature via `.tileset` /
 * `.content.tileset`, so it works even before the reference has propagated).
 * We deliberately do NOT treat an arbitrary 3D tileset/feature as photoreal —
 * an unmarked, unreferenced tileset returns false. (No `instanceof` checks: the
 * marker + reference are stronger and keep this helper Cesium-runtime-free and
 * trivially testable.)
 */
export function isPhotorealSurfacePick(
  picked: unknown,
  photorealTileset: Cesium.Cesium3DTileset | null,
): boolean {
  if (!picked) return false;

  const p = picked as {
    primitive?: unknown;
    tileset?: unknown;
    content?: { tileset?: unknown };
  };

  // A picked tile feature exposes its owning tileset via .tileset / .content;
  // a non-feature surface pick exposes it via .primitive.
  const candidates = [p.primitive, p.tileset, p.content?.tileset];
  for (const c of candidates) {
    if (!c) continue;
    if (photorealTileset && c === photorealTileset) return true;
    if ((c as { _odinPhotoreal?: boolean })._odinPhotoreal === true) return true;
  }
  return false;
}
