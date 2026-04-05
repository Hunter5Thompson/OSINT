import { useEffect, useRef, useCallback } from "react";
import * as Cesium from "cesium";
import * as satellite from "satellite.js";
import type { Satellite } from "../../types";
import { usePerformance } from "../globe/PerformanceGuard";

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

const COUNTRY_TINT: Record<string, Cesium.Color> = {
  US: Cesium.Color.fromCssColorString("#3b82f6").withAlpha(0.6),
  RU: Cesium.Color.fromCssColorString("#ef4444").withAlpha(0.6),
  CN: Cesium.Color.fromCssColorString("#eab308").withAlpha(0.6),
  EU: Cesium.Color.fromCssColorString("#d4cdc0").withAlpha(0.6),
};

const ORBIT_ARC_POINTS = 50;
const ORBIT_LOD_ALTITUDE = 12_000_000; // show orbits only when reasonably zoomed in
const RECON_PREFIXES = ["USA ", "NROL", "COSMOS 25", "YAOGAN"];
const MIN_ELEVATION_DEG = 5;
/** Only render orbit arcs for high-interest categories (not all 15K active sats) */
const ORBIT_ELIGIBLE_CATEGORIES = new Set(["military", "station", "gps", "weather"]);

function isReconSatellite(name: string): boolean {
  const upper = name.toUpperCase();
  return RECON_PREFIXES.some((p) => upper.startsWith(p));
}

function computeFootprintRadiusKm(altitudeKm: number): number {
  const earthR = 6371;
  const elevRad = (MIN_ELEVATION_DEG * Math.PI) / 180;
  const centralAngle = Math.acos(earthR / (earthR + altitudeKm)) - elevRad;
  return Math.max(0, earthR * centralAngle);
}

export function SatelliteLayer({ viewer, satellites, visible }: SatelliteLayerProps) {
  const pointsRef = useRef<Cesium.PointPrimitiveCollection | null>(null);
  const orbitCollectionRef = useRef<Cesium.PolylineCollection | null>(null);
  const footprintEntityRef = useRef<Cesium.Entity | null>(null);
  const coneCollectionRef = useRef<Cesium.PolylineCollection | null>(null);
  const { degradation } = usePerformance();
  const lastShowOrbitsRef = useRef(false);

  useEffect(() => {
    if (!viewer || viewer.isDestroyed()) return;

    if (!pointsRef.current) {
      pointsRef.current = new Cesium.PointPrimitiveCollection();
      viewer.scene.primitives.add(pointsRef.current);
    }
    if (!orbitCollectionRef.current) {
      orbitCollectionRef.current = new Cesium.PolylineCollection();
      viewer.scene.primitives.add(orbitCollectionRef.current);
    }
    if (!coneCollectionRef.current) {
      coneCollectionRef.current = new Cesium.PolylineCollection();
      viewer.scene.primitives.add(coneCollectionRef.current);
    }

    return () => {
      if (!viewer.isDestroyed()) {
        if (pointsRef.current) viewer.scene.primitives.remove(pointsRef.current);
        if (orbitCollectionRef.current) viewer.scene.primitives.remove(orbitCollectionRef.current);
        if (coneCollectionRef.current) viewer.scene.primitives.remove(coneCollectionRef.current);
        if (footprintEntityRef.current) viewer.entities.remove(footprintEntityRef.current);
      }
      pointsRef.current = null;
      orbitCollectionRef.current = null;
      coneCollectionRef.current = null;
      footprintEntityRef.current = null;
    };
  }, [viewer]);

  const propagateOrbitArc = useCallback((satrec: satellite.SatRec, startDate: Date): Cesium.Cartesian3[] => {
    const positions: Cesium.Cartesian3[] = [];
    for (let i = 0; i <= ORBIT_ARC_POINTS; i++) {
      const futureDate = new Date(startDate.getTime() + i * 60_000);
      const posVel = satellite.propagate(satrec, futureDate);
      if (typeof posVel.position === "boolean" || !posVel.position) continue;
      const gmst = satellite.gstime(futureDate);
      const geo = satellite.eciToGeodetic(posVel.position, gmst);
      positions.push(
        Cesium.Cartesian3.fromDegrees(
          satellite.degreesLong(geo.longitude),
          satellite.degreesLat(geo.latitude),
          geo.height * 1000,
        ),
      );
    }
    return positions;
  }, []);

  useEffect(() => {
    const pc = pointsRef.current;
    const oc = orbitCollectionRef.current;
    if (!pc || !oc || !viewer || viewer.isDestroyed()) return;

    pc.removeAll();
    oc.removeAll();
    if (!visible || satellites.length === 0) return;

    const now = new Date();
    const cameraAlt = viewer.camera.positionCartographic.height;
    const showOrbits = degradation < 3 && cameraAlt < ORBIT_LOD_ALTITUDE;
    lastShowOrbitsRef.current = showOrbits;

    // LOD: at global zoom only show high-interest sats (~215)
    // At medium zoom show everything except Starlink (~1600)
    // At close zoom show all (~11700)
    const showAll = cameraAlt < 5_000_000;
    const showNonMega = cameraAlt < 10_000_000;

    for (const sat of satellites) {
      if (!showAll) {
        const upper = sat.name.toUpperCase();
        if (upper.startsWith("STARLINK") || upper.startsWith("ONEWEB")) {
          if (!showNonMega) continue; // skip at global zoom
          continue; // skip at medium zoom too — they're 10K+ points
        }
        if (!showNonMega && sat.category === "active") continue;
      }
      let satrec: satellite.SatRec;
      try {
        satrec = satellite.twoline2satrec(sat.tle_line1, sat.tle_line2);
      } catch {
        continue;
      }

      const posVel = satellite.propagate(satrec, now);
      if (typeof posVel.position === "boolean" || !posVel.position) continue;

      const gmst = satellite.gstime(now);
      const geo = satellite.eciToGeodetic(posVel.position, gmst);
      const lon = satellite.degreesLong(geo.longitude);
      const lat = satellite.degreesLat(geo.latitude);
      const alt = geo.height * 1000;

      const color = CATEGORY_COLORS[sat.category] ?? CATEGORY_COLORS["active"]!;
      const isRecon = isReconSatellite(sat.name);

      const point = pc.add({
        position: Cesium.Cartesian3.fromDegrees(lon, lat, alt),
        pixelSize: isRecon ? 10 : sat.category === "station" ? 8 : 3,
        color: isRecon ? Cesium.Color.RED : color,
      });

      (point as unknown as Record<string, unknown>)._satelliteData = {
        norad_id: sat.norad_id,
        name: sat.name,
        category: sat.category,
        inclination_deg: sat.inclination_deg,
        period_min: sat.period_min,
        altitude_km: geo.height,
        operator_country: sat.operator_country,
        satellite_type: sat.satellite_type,
        footprint_radius_km: Math.round(computeFootprintRadiusKm(geo.height)),
        lat,
        lon,
      };

      if (showOrbits && ORBIT_ELIGIBLE_CATEGORIES.has(sat.category)) {
        const orbitPositions = propagateOrbitArc(satrec, now);
        if (orbitPositions.length >= 2) {
          const orbitColor = sat.operator_country
            ? (COUNTRY_TINT[sat.operator_country] ?? color.withAlpha(0.3))
            : color.withAlpha(0.3);

          oc.add({
            positions: orbitPositions,
            width: 1.0,
            material: Cesium.Material.fromType("Color", { color: orbitColor }),
          });
        }
      }
    }
  }, [satellites, visible, viewer, degradation, propagateOrbitArc]);

  useEffect(() => {
    if (!viewer || viewer.isDestroyed()) return;

    const onMoveEnd = () => {
      if (!viewer || viewer.isDestroyed() || !visible) return;
      const cameraAlt = viewer.camera.positionCartographic.height;
      const shouldShow = degradation < 3 && cameraAlt < ORBIT_LOD_ALTITUDE;

      if (shouldShow !== lastShowOrbitsRef.current) {
        lastShowOrbitsRef.current = shouldShow;
        const oc = orbitCollectionRef.current;
        if (!oc) return;

        if (shouldShow && oc.length === 0) {
          const now = new Date();
          for (const sat of satellites) {
            if (!ORBIT_ELIGIBLE_CATEGORIES.has(sat.category)) continue;
            let satrec: satellite.SatRec;
            try { satrec = satellite.twoline2satrec(sat.tle_line1, sat.tle_line2); } catch { continue; }
            const orbitPositions = propagateOrbitArc(satrec, now);
            if (orbitPositions.length < 2) continue;
            const color = CATEGORY_COLORS[sat.category] ?? CATEGORY_COLORS["active"]!;
            const orbitColor = sat.operator_country
              ? (COUNTRY_TINT[sat.operator_country] ?? color.withAlpha(0.3))
              : color.withAlpha(0.3);
            oc.add({
              positions: orbitPositions,
              width: 1.0,
              material: Cesium.Material.fromType("Color", { color: orbitColor }),
            });
          }
        }
        oc.show = shouldShow;
      }
    };

    viewer.camera.moveEnd.addEventListener(onMoveEnd);
    return () => {
      if (!viewer.isDestroyed()) viewer.camera.moveEnd.removeEventListener(onMoveEnd);
    };
  }, [viewer, visible, degradation, satellites, propagateOrbitArc]);

  // 3D observation cone on hover
  useEffect(() => {
    if (!viewer || viewer.isDestroyed()) return;

    const handler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas);
    const CONE_SEGMENTS = 24;

    const clearCone = () => {
      if (coneCollectionRef.current) coneCollectionRef.current.removeAll();
      if (footprintEntityRef.current) {
        viewer.entities.remove(footprintEntityRef.current);
        footprintEntityRef.current = null;
      }
    };

    handler.setInputAction((movement: Cesium.ScreenSpaceEventHandler.MotionEvent) => {
      const picked = viewer.scene.pick(movement.endPosition);
      const satData = (picked?.primitive as Record<string, unknown>)?._satelliteData as
        | { footprint_radius_km?: number; altitude_km?: number; lat: number; lon: number; category?: string }
        | undefined;

      clearCone();

      if (!satData || !satData.footprint_radius_km || satData.footprint_radius_km <= 0) return;

      const color = CATEGORY_COLORS[satData.category ?? "active"] ?? CATEGORY_COLORS["active"]!;
      const radiusM = satData.footprint_radius_km * 1000;
      const altM = (satData.altitude_km ?? 400) * 1000;
      const satPosition = Cesium.Cartesian3.fromDegrees(satData.lon, satData.lat, altM);
      const cc = coneCollectionRef.current;

      if (cc) {
        // Compute footprint edge points
        const edgePoints: Cesium.Cartesian3[] = [];
        for (let i = 0; i < CONE_SEGMENTS; i++) {
          const angle = (i / CONE_SEGMENTS) * Math.PI * 2;
          const dLat = (radiusM * Math.cos(angle)) / 6_371_000;
          const dLon = (radiusM * Math.sin(angle)) / (6_371_000 * Math.cos(Cesium.Math.toRadians(satData.lat)));
          edgePoints.push(
            Cesium.Cartesian3.fromDegrees(
              satData.lon + Cesium.Math.toDegrees(dLon),
              satData.lat + Cesium.Math.toDegrees(dLat),
              0,
            ),
          );
        }

        // Cone wireframe lines: satellite → edge points
        for (let i = 0; i < CONE_SEGMENTS; i += 2) {
          cc.add({
            positions: [satPosition, edgePoints[i]],
            width: 1.0,
            material: Cesium.Material.fromType("Color", {
              color: color.withAlpha(0.25),
            }),
          });
        }

        // Footprint edge ring on ground
        const ringPositions = [...edgePoints, edgePoints[0]];
        cc.add({
          positions: ringPositions,
          width: 1.5,
          material: Cesium.Material.fromType("Color", {
            color: color.withAlpha(0.5),
          }),
        });
      }

      // Semi-transparent ground ellipse fill
      footprintEntityRef.current = viewer.entities.add({
        position: Cesium.Cartesian3.fromDegrees(satData.lon, satData.lat, 0),
        // @ts-expect-error — allowPicking not in type defs
        allowPicking: false,
        ellipse: {
          semiMajorAxis: radiusM,
          semiMinorAxis: radiusM,
          material: color.withAlpha(0.08),
          outline: false,
        },
      });
    }, Cesium.ScreenSpaceEventType.MOUSE_MOVE);

    return () => {
      clearCone();
      handler.destroy();
    };
  }, [viewer]);

  return null;
}
