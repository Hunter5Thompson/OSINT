import { useEffect } from "react";
import * as Cesium from "cesium";

interface Props {
  viewer: Cesium.Viewer | null;
}

export function Graticule({ viewer }: Props) {
  useEffect(() => {
    if (!viewer || viewer.isDestroyed()) return;

    const collection = new Cesium.PolylineCollection();

    // --graticule is defined via color-mix(); getComputedStyle returns custom
    // properties verbatim, so we resolve it through a probe element to get a
    // parseable rgb(...) string. Hex fallback covers parser failures.
    const probe = document.createElement("span");
    probe.style.color = "var(--graticule)";
    probe.style.display = "none";
    document.body.appendChild(probe);
    const resolved = getComputedStyle(probe).color;
    document.body.removeChild(probe);
    const color =
      Cesium.Color.fromCssColorString(resolved || "") ??
      Cesium.Color.fromCssColorString("#28302e");
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
      // The viewer can tear primitives down before this cleanup runs (React 19
      // StrictMode double-fire + GlobeViewer viewer recreation). Swallow the
      // resulting "already destroyed" throws so the unmount path stays clean.
      try {
        viewer.scene.primitives.remove(collection);
      } catch {
        /* primitive already destroyed by viewer teardown */
      }
    };
  }, [viewer]);

  return null;
}
