import * as Cesium from "cesium";

function record(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null ? value as Record<string, unknown> : null;
}

/** Compatibility seam for pinned Cesium 1.142.0, not a renderer replacement.
 * EllipsoidTerrainProvider creates 16x16 heightmaps. Cesium globally caches
 * their index arrays, then stores GPU buffers by context ID on those arrays.
 * Destroying the buffer leaves that entry holding _gl -> canvas indefinitely.
 * Capture before destroy; release only entries of the destroyed owner.
 * Remove/requalify this workaround when upgrading Cesium. Remote terrain of
 * other dimensions is deliberately outside its contract.
 */
export function captureTerrainCacheRelease(viewer: Cesium.Viewer): () => void {
  const scene = record(viewer.scene);
  const context = record(scene?.context);
  const contextId = context?.id;
  const gridFunction: unknown = Reflect.get(Cesium.TerrainProvider, "getRegularGridAndSkirtIndicesAndEdgeIndices");
  if (Reflect.get(Cesium, "VERSION") !== "1.142.0" || typeof contextId !== "string" || typeof gridFunction !== "function") {
    throw new Error("Cesium terrain cache contract changed; requalify lifecycle cleanup");
  }
  const grid: unknown = gridFunction(16, 16);
  const indices = record(record(grid)?.indices);
  const plain = record(Cesium.TerrainProvider.getRegularGridIndices(16, 16));
  if (!indices || !plain) throw new Error("Cesium terrain index arrays are unavailable");
  return () => {
    if (!viewer.isDestroyed()) return;
    for (const array of [plain, indices]) {
      const buffers = record(array.indexBuffers);
      const buffer = record(buffers?.[contextId]);
      if (buffers && buffer && typeof buffer.isDestroyed === "function") {
        // Cesium's terrain reference count can still be nonzero even after
        // the complete owner was destroyed. No live tile can use this context.
        if (!buffer.isDestroyed()) {
          if (typeof buffer.destroy !== "function") throw new Error("Cesium buffer disposal changed");
          buffer.destroy();
        }
        delete buffers[contextId];
      }
    }
  };
}
