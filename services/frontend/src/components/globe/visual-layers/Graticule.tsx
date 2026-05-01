import { useEffect } from "react";
import * as Cesium from "cesium";

interface Props {
  viewer: Cesium.Viewer | null;
}

export function Graticule({ viewer }: Props) {
  useEffect(() => {
    if (!viewer || viewer.isDestroyed()) return;

    const collection = new Cesium.PolylineCollection();

    // Read the --graticule token at mount time. color-mix() resolves to a
    // valid CSS color string in modern browsers; if not, fall back to a hex
    // approximation of color-mix(--granite 80% --steel 20%).
    const cssVar = getComputedStyle(document.documentElement)
      .getPropertyValue("--graticule")
      .trim();
    const color = Cesium.Color.fromCssColorString(cssVar || "#28302e");
    const material = Cesium.Material.fromType("Color", {
      color: color.withAlpha(0.45),
    });

    // Latitudes every 10°
    for (let lat = -80; lat <= 80; lat += 10) {
      const positions: Cesium.Cartesian3[] = [];
      for (let lon = -180; lon <= 180; lon += 5) {
        positions.push(Cesium.Cartesian3.fromDegrees(lon, lat));
      }
      collection.add({ positions, width: 0.5, material });
    }

    // Longitudes every 10°
    for (let lon = -180; lon < 180; lon += 10) {
      const positions: Cesium.Cartesian3[] = [];
      for (let lat = -85; lat <= 85; lat += 5) {
        positions.push(Cesium.Cartesian3.fromDegrees(lon, lat));
      }
      collection.add({ positions, width: 0.5, material });
    }

    viewer.scene.primitives.add(collection);

    return () => {
      if (viewer.isDestroyed()) return;
      viewer.scene.primitives.remove(collection);
    };
  }, [viewer]);

  return null;
}
