import { useEffect, useRef } from "react";
import * as Cesium from "cesium";
import * as satellite from "satellite.js";
import type { Satellite } from "../../types";

interface SatelliteLayerProps {
  viewer: Cesium.Viewer | null;
  satellites: Satellite[];
  visible: boolean;
}

const CATEGORY_COLORS: Record<string, Cesium.Color> = {
  military: Cesium.Color.RED.withAlpha(0.8),
  weather: Cesium.Color.CYAN.withAlpha(0.8),
  gps: Cesium.Color.YELLOW.withAlpha(0.8),
  station: Cesium.Color.WHITE,
  geo: Cesium.Color.ORANGE.withAlpha(0.6),
  active: Cesium.Color.LIME.withAlpha(0.5),
};

/**
 * Renders satellites using PointPrimitiveCollection + SGP4 propagation.
 */
export function SatelliteLayer({ viewer, satellites, visible }: SatelliteLayerProps) {
  const pointsRef = useRef<Cesium.PointPrimitiveCollection | null>(null);
  const animationRef = useRef<number | null>(null);

  useEffect(() => {
    if (!viewer || viewer.isDestroyed()) return;

    if (!pointsRef.current) {
      pointsRef.current = new Cesium.PointPrimitiveCollection();
      viewer.scene.primitives.add(pointsRef.current);
    }

    return () => {
      if (pointsRef.current && !viewer.isDestroyed()) {
        viewer.scene.primitives.remove(pointsRef.current);
        pointsRef.current = null;
      }
      if (animationRef.current) {
        cancelAnimationFrame(animationRef.current);
      }
    };
  }, [viewer]);

  useEffect(() => {
    const pc = pointsRef.current;
    if (!pc || !viewer || viewer.isDestroyed()) return;

    pc.removeAll();
    if (!visible || satellites.length === 0) return;

    // Parse TLE records
    const satRecords = satellites
      .map((sat) => {
        try {
          const satrec = satellite.twoline2satrec(sat.tle_line1, sat.tle_line2);
          return { sat, satrec };
        } catch {
          return null;
        }
      })
      .filter((s): s is NonNullable<typeof s> => s !== null);

    // Propagate and render
    const now = new Date();

    for (const { sat, satrec } of satRecords) {
      const posVel = satellite.propagate(satrec, now);
      if (typeof posVel.position === "boolean" || !posVel.position) continue;

      const gmst = satellite.gstime(now);
      const geo = satellite.eciToGeodetic(posVel.position, gmst);

      const lon = satellite.degreesLong(geo.longitude);
      const lat = satellite.degreesLat(geo.latitude);
      const alt = geo.height * 1000; // km to meters

      const color = CATEGORY_COLORS[sat.category] ?? CATEGORY_COLORS["active"]!;

      const point = pc.add({
        position: Cesium.Cartesian3.fromDegrees(lon, lat, alt),
        pixelSize: sat.category === "station" ? 8 : 3,
        color,
      });
      (point as unknown as Record<string, unknown>)._satelliteData = {
        norad_id: sat.norad_id,
        name: sat.name,
        category: sat.category,
        inclination_deg: sat.inclination_deg,
        period_min: sat.period_min,
        altitude_km: geo.height,
        lat,
        lon,
      };
    }
  }, [satellites, visible, viewer]);

  return null;
}
