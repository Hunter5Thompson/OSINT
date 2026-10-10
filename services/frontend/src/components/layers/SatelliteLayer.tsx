import { useEffect, useRef } from "react";
import * as Cesium from "cesium";
import type { SatRec } from "satellite.js";
import { SatelliteRecordCache, propagateSatellite } from "../../lib/satelliteOrbit";
import type { OrbitSatellite } from "../../types/satelliteOrbit";
import { useTime } from "../../state/TimeContext";
import { glyphColor } from "./glyphTokens";
import type { Satellite } from "../../types";
import { usePerformance } from "../globe/PerformanceGuard";
import { GLOBE_ALTITUDE_M, ORBIT_LOD_ALTITUDE_M } from "../../lib/lod";

export function shouldRenderCone(sat: {
  lat: number;
  lon: number;
  footprint_radius_km?: number;
}): boolean {
  if (!Number.isFinite(sat.lat) || !Number.isFinite(sat.lon)) return false;
  if (!sat.footprint_radius_km || sat.footprint_radius_km <= 0) return false;
  return true;
}

interface SatelliteLayerProps {
  viewer: Cesium.Viewer | null;
  satellites: (Satellite | OrbitSatellite)[];
  visible: boolean;
  discontinuityEpoch?: number;
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
  EU: glyphColor.stone().withAlpha(0.6),
};

const ORBIT_ARC_POINTS = 50;
const MAX_ORBIT_ARCS = 64;
const POINT_IMAGE = "data:image/svg+xml," + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><circle cx="5" cy="5" r="5" fill="white"/></svg>');
const ORBIT_LOD_ALTITUDE = ORBIT_LOD_ALTITUDE_M; // keep orbits visible across LEO..GEO globe-scale zoom
const RECON_PREFIXES = ["USA ", "NROL", "COSMOS 25", "YAOGAN"];
const MIN_ELEVATION_DEG = 5;
/** Prioritize high-interest groups within the single bounded orbit budget. */
const ORBIT_ELIGIBLE_CATEGORIES = new Set(["military", "station", "gps", "weather"]);

/**
 * Decide whether orbit arcs should be visible.
 *
 * At most 64 arcs are sampled, with high-interest satellites taking priority.
 * Hide them at the most extreme degradation level and beyond the orbit altitude limit.
 */
export function shouldShowOrbits(degradation: number, cameraAltitudeM: number): boolean {
  return degradation < 4 && cameraAltitudeM < ORBIT_LOD_ALTITUDE;
}

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

export function SatelliteLayerBridge(props: Omit<SatelliteLayerProps, "discontinuityEpoch">) {
  const { discontinuityEpoch } = useTime();
  return <SatelliteLayer {...props} discontinuityEpoch={discontinuityEpoch} />;
}

export function SatelliteLayer({ viewer, satellites, visible, discontinuityEpoch = 0 }: SatelliteLayerProps) {
  const pointsRef = useRef<Cesium.BillboardCollection | null>(null);
  const orbitCollectionRef = useRef<Cesium.PolylineCollection | null>(null);
  const footprintEntityRef = useRef<Cesium.Entity | null>(null);
  const coneCollectionRef = useRef<Cesium.PolylineCollection | null>(null);
  const { degradation } = usePerformance();
  const recordsRef = useRef(new SatelliteRecordCache());
  const refreshRef = useRef<(() => void) | null>(null);
  const epochRef = useRef(discontinuityEpoch);

  useEffect(() => {
    if (!viewer || viewer.isDestroyed()) return;

    if (!pointsRef.current) {
      pointsRef.current = new Cesium.BillboardCollection();
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

  useEffect(() => {
    const pc = pointsRef.current;
    const oc = orbitCollectionRef.current;
    if (!pc || !oc || !viewer || viewer.isDestroyed()) return;
    pc.removeAll();
    oc.removeAll();
    recordsRef.current.retain(satellites);
    if (!visible || satellites.length === 0) return;

    let disposed = false;
    const entries: { sat: Satellite | OrbitSatellite; record: SatRec; point: Cesium.Billboard }[] = [];
    const cameraAlt = viewer.camera.positionCartographic.height;
    for (const sat of satellites) {
      if (cameraAlt >= GLOBE_ALTITUDE_M && sat.category === "active" &&
          /^(STARLINK|ONEWEB)/i.test(sat.name)) continue;
      const record = recordsRef.current.get(sat);
      if (!record) continue;
      const color = CATEGORY_COLORS[sat.category] ?? CATEGORY_COLORS["active"]!;
      const recon = isReconSatellite(sat.name);
      const size = recon ? 10 : sat.category === "station" ? 8 : 3;
      const point = pc.add({
        position: Cesium.Cartesian3.ZERO, image: POINT_IMAGE, width: size, height: size,
        color: recon ? Cesium.Color.RED : color, show: false,
      });
      entries.push({ sat, record, point });
    }

    let lastTime: number | null = null;
    let lastWall = -Infinity;
    let orbitWall = -Infinity;
    let lastMultiplier = viewer.clock.multiplier;
    const update = (force = false) => {
      if (disposed || viewer.isDestroyed()) return;
      const date = Cesium.JulianDate.toDate(viewer.clock.currentTime);
      const time = date.getTime();
      const wall = performance.now();
      const delta = lastTime === null ? Infinity : time - lastTime;
      const discontinuity = lastTime === null ||
        (delta < 0 && viewer.clock.multiplier >= 0) || viewer.clock.multiplier !== lastMultiplier ||
        (!viewer.clock.shouldAnimate && delta !== 0) ||
        Math.abs(delta - (wall - lastWall) * viewer.clock.multiplier) > 1000;
      if (!force && (delta === 0 || (!discontinuity && wall - lastWall < 1000))) return;
      lastMultiplier = viewer.clock.multiplier;
      lastTime = time;
      lastWall = wall;
      for (const { sat, record, point } of entries) {
        const position = propagateSatellite(record, date);
        point.show = position !== null;
        if (!position) continue;
        point.position = Cesium.Cartesian3.fromDegrees(position.longitude_deg, position.latitude_deg, position.altitude_m);
        (point as unknown as Record<string, unknown>)._satelliteData = {
          norad_id: sat.norad_id, name: sat.name, category: sat.category,
          inclination_deg: sat.inclination_deg, period_min: sat.period_min,
          altitude_km: position.altitude_m / 1000,
          operator_country: sat.operator_country, satellite_type: sat.satellite_type,
          footprint_radius_km: Math.round(computeFootprintRadiusKm(position.altitude_m / 1000)),
          lat: position.latitude_deg, lon: position.longitude_deg,
        };
      }
      const showOrbits = shouldShowOrbits(degradation, viewer.camera.positionCartographic.height);
      oc.show = showOrbits;
      if (showOrbits && (force || discontinuity || wall - orbitWall >= 30_000)) {
        orbitWall = wall;
        oc.removeAll();
        const candidates = [
          ...entries.filter(entry => ORBIT_ELIGIBLE_CATEGORIES.has(entry.sat.category)),
          ...entries.filter(entry => !ORBIT_ELIGIBLE_CATEGORIES.has(entry.sat.category)),
        ];
        for (const { sat, record, point } of candidates) {
          if (!point.show) continue;
          if (oc.length >= MAX_ORBIT_ARCS) break;
          const positions: Cesium.Cartesian3[] = [];
          for (let i = 0; i <= ORBIT_ARC_POINTS; i++) {
            const position = propagateSatellite(record, new Date(time + i * 60_000));
            if (position) positions.push(Cesium.Cartesian3.fromDegrees(
              position.longitude_deg, position.latitude_deg, position.altitude_m,
            ));
          }
          if (positions.length < 2) continue;
          const color = CATEGORY_COLORS[sat.category] ?? CATEGORY_COLORS["active"]!;
          const orbitColor = sat.operator_country
            ? (COUNTRY_TINT[sat.operator_country] ?? color.withAlpha(0.3)) : color.withAlpha(0.3);
          oc.add({ positions, width: 1.0, material: Cesium.Material.fromType("Color", { color: orbitColor }) });
        }
      }
      viewer.scene.requestRender();
    };
    refreshRef.current = () => update(true);
    update(true);
    const onTick = () => update();
    const onMoveEnd = () => update(true);
    const removeTick = viewer.clock.onTick.addEventListener(onTick);
    const removeMove = viewer.camera.moveEnd.addEventListener(onMoveEnd);
    return () => {
      disposed = true;
      refreshRef.current = null;
      removeTick();
      removeMove();
    };
  }, [satellites, visible, viewer, degradation]);

  useEffect(() => {
    if (epochRef.current !== discontinuityEpoch) refreshRef.current?.();
    epochRef.current = discontinuityEpoch;
  }, [discontinuityEpoch]);

  // 3D observation cone on hover
  useEffect(() => {
    if (!viewer || viewer.isDestroyed() || !visible) return;
    let disposed = false;

    const handler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas);
    const CONE_SEGMENTS = 24;

    const clearCone = () => {
      if (coneCollectionRef.current && !coneCollectionRef.current.isDestroyed()) coneCollectionRef.current.removeAll();
      if (footprintEntityRef.current) {
        if (!viewer.isDestroyed()) viewer.entities.remove(footprintEntityRef.current);
        footprintEntityRef.current = null;
      }
    };

    handler.setInputAction((movement: Cesium.ScreenSpaceEventHandler.MotionEvent) => {
      if (disposed || viewer.isDestroyed()) return;
      const picked = viewer.scene.pick(movement.endPosition);
      const satData = (picked?.primitive as Record<string, unknown>)?._satelliteData as
        | { footprint_radius_km?: number; altitude_km?: number; lat: number; lon: number; category?: string }
        | undefined;

      clearCone();

      if (!satData || !shouldRenderCone(satData)) return;

      const color = CATEGORY_COLORS[satData.category ?? "active"] ?? CATEGORY_COLORS["active"]!;
      const radiusM = satData.footprint_radius_km! * 1000;
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
      disposed = true;
      clearCone();
      if (!handler.isDestroyed()) handler.destroy();
    };
  }, [viewer, visible]);

  return null;
}
