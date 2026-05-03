import { useEffect, useRef } from "react";
import * as Cesium from "cesium";
import { feature as topojsonFeature } from "topojson-client";

interface Props {
  viewer: Cesium.Viewer | null;
  visible: boolean;
}

export function CountryBorders({ viewer, visible }: Props) {
  const collectionRef = useRef<Cesium.PolylineCollection | null>(null);

  useEffect(() => {
    if (!viewer || viewer.isDestroyed() || !visible) return;
    let cancelled = false;

    (async () => {
      const res = await fetch("/countries-110m.json");
      const topo = (await res.json()) as unknown;
      if (cancelled || viewer.isDestroyed()) return;

      const fc = topojsonFeature(
        topo as Parameters<typeof topojsonFeature>[0],
        (topo as { objects: { countries: unknown } }).objects
          .countries as Parameters<typeof topojsonFeature>[1],
      ) as unknown as GeoJSON.FeatureCollection;

      const cssVar = getComputedStyle(document.documentElement)
        .getPropertyValue("--stone")
        .trim();
      const stoneColor = Cesium.Color.fromCssColorString(cssVar || "#958a7a").withAlpha(0.7);
      const material = Cesium.Material.fromType("Color", { color: stoneColor });

      const collection = new Cesium.PolylineCollection();
      for (const f of fc.features) {
        const geom = f.geometry as GeoJSON.Polygon | GeoJSON.MultiPolygon | null;
        if (!geom) continue;

        const polygons = geom.type === "Polygon" ? [geom.coordinates] : geom.coordinates;
        for (const poly of polygons) {
          for (const ring of poly as number[][][]) {
            const positions = ring.map((coord) => {
              const lon = coord[0]!;
              const lat = coord[1]!;
              return Cesium.Cartesian3.fromDegrees(lon, lat);
            });
            collection.add({ positions, width: 0.6, material });
          }
        }
      }

      // Re-check after the synchronous build — under React 19 StrictMode the
      // cleanup can fire while we were building, in which case adding to the
      // viewer would leak a half-built collection.
      if (cancelled || viewer.isDestroyed()) {
        collection.destroy();
        return;
      }
      viewer.scene.primitives.add(collection);
      collectionRef.current = collection;
    })().catch((e) => console.error("CountryBorders load failed:", e));

    return () => {
      cancelled = true;
      const collection = collectionRef.current;
      collectionRef.current = null;
      if (!collection || viewer.isDestroyed()) return;
      try {
        viewer.scene.primitives.remove(collection);
      } catch {
        /* primitive already destroyed via viewer teardown */
      }
    };
  }, [viewer, visible]);

  return null;
}
