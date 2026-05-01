import { useEffect } from "react";
import * as Cesium from "cesium";
import { feature as topojsonFeature } from "topojson-client";

interface Props {
  viewer: Cesium.Viewer | null;
  visible: boolean;
}

export function CountryBorders({ viewer, visible }: Props) {
  useEffect(() => {
    if (!viewer || viewer.isDestroyed() || !visible) return;
    let cancelled = false;
    let collection: Cesium.PolylineCollection | null = null;

    (async () => {
      const res = await fetch("/countries-110m.json");
      const topo = (await res.json()) as unknown;
      if (cancelled || viewer.isDestroyed()) return;

      const fc = topojsonFeature(topo as Parameters<typeof topojsonFeature>[0], (topo as { objects: { countries: unknown } }).objects.countries as Parameters<typeof topojsonFeature>[1]) as unknown as GeoJSON.FeatureCollection;

      const cssVar = getComputedStyle(document.documentElement).getPropertyValue("--stone").trim();
      const stoneColor = Cesium.Color.fromCssColorString(cssVar || "#958a7a").withAlpha(0.7);
      const material = Cesium.Material.fromType("Color", { color: stoneColor });

      collection = new Cesium.PolylineCollection();

      // Type assertion for the feature collection
      const features = (fc as GeoJSON.FeatureCollection).features;
      for (const f of features) {
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
      viewer.scene.primitives.add(collection);
    })().catch((e) => console.error("CountryBorders load failed:", e));

    return () => {
      cancelled = true;
      if (viewer.isDestroyed() || !collection) return;
      viewer.scene.primitives.remove(collection);
    };
  }, [viewer, visible]);

  return null;
}
