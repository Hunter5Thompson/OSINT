import { useEffect, useRef } from "react";
import * as Cesium from "cesium";
import { feature as topojsonFeature } from "topojson-client";

/** Wider than the old 0.6 (screen-space px) so the line reads over photoreal terrain. */
export const BORDER_WIDTH = 2.0;

/** Pure: a GeoJSON ring of [lon,lat] pairs -> Cartesian3 positions. */
export function ringToPositions(ring: number[][]): Cesium.Cartesian3[] {
  return ring.map((coord) => Cesium.Cartesian3.fromDegrees(coord[0]!, coord[1]!));
}

interface Props {
  viewer: Cesium.Viewer | null;
  visible: boolean;
}

export function CountryBorders({ viewer, visible }: Props) {
  const primitiveRef = useRef<Cesium.GroundPolylinePrimitive | null>(null);

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
        .getPropertyValue("--bone")
        .trim();
      // Bright neutral (bone), not an accent colour — an accent would read like a
      // data layer. Higher alpha than the old stone@0.7 for legibility.
      const lineColor = Cesium.Color.fromCssColorString(cssVar || "#d4cdc0").withAlpha(0.9);

      const instances: Cesium.GeometryInstance[] = [];
      for (const f of fc.features) {
        const geom = f.geometry as GeoJSON.Polygon | GeoJSON.MultiPolygon | null;
        if (!geom) continue;
        const polygons = geom.type === "Polygon" ? [geom.coordinates] : geom.coordinates;
        for (const poly of polygons) {
          for (const ring of poly as number[][][]) {
            const positions = ringToPositions(ring);
            if (positions.length < 2) continue; // GroundPolylineGeometry needs >= 2
            instances.push(
              new Cesium.GeometryInstance({
                geometry: new Cesium.GroundPolylineGeometry({ positions, width: BORDER_WIDTH }),
              }),
            );
          }
        }
      }

      // Re-check after the synchronous build (React 19 StrictMode cleanup race).
      if (cancelled || viewer.isDestroyed()) return;

      const primitive = new Cesium.GroundPolylinePrimitive({
        geometryInstances: instances,
        appearance: new Cesium.PolylineMaterialAppearance({
          material: Cesium.Material.fromType("Color", { color: lineColor }),
        }),
        // Drape over BOTH world terrain and the Google photoreal 3D tiles, so the
        // border is never occluded by the surface in front of it (the P2 bug).
        classificationType: Cesium.ClassificationType.BOTH,
      });
      viewer.scene.primitives.add(primitive);
      primitiveRef.current = primitive;
    })().catch((e) => console.error("CountryBorders load failed:", e));

    return () => {
      cancelled = true;
      const primitive = primitiveRef.current;
      primitiveRef.current = null;
      if (!primitive || viewer.isDestroyed()) return;
      try {
        viewer.scene.primitives.remove(primitive);
      } catch {
        /* primitive already destroyed via viewer teardown */
      }
    };
  }, [viewer, visible]);

  return null;
}
