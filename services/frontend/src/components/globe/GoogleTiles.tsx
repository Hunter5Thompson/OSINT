import { useEffect } from "react";
import * as Cesium from "cesium";

interface GoogleTilesProps {
  viewer: Cesium.Viewer | null;
}

/**
 * Loads Google Photorealistic 3D Tiles into the viewer.
 * Separated for lazy-loading scenarios.
 */
export function GoogleTiles({ viewer }: GoogleTilesProps) {
  useEffect(() => {
    if (!viewer || viewer.isDestroyed()) return;

    let tileset: Cesium.Cesium3DTileset | null = null;

    void Cesium.createGooglePhotorealistic3DTileset().then((ts) => {
      if (!viewer.isDestroyed()) {
        tileset = ts;
        viewer.scene.primitives.add(tileset);
      }
    });

    return () => {
      if (tileset && viewer && !viewer.isDestroyed()) {
        viewer.scene.primitives.remove(tileset);
      }
    };
  }, [viewer]);

  return null;
}
