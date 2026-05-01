import { useEffect, useRef } from "react";
import * as Cesium from "cesium";
import type { Aircraft } from "../../types";
import { glyphColor } from "./glyphTokens";
import { classifyAircraft, getAircraftTypeIcon } from "./icons/aircraftIcons";
import { usePerformance, type DegradationLevel } from "../globe/PerformanceGuard";

interface FlightLayerProps {
  viewer: Cesium.Viewer | null;
  flights: Aircraft[];
  visible: boolean;
}

interface FlightVisual {
  billboard: Cesium.Billboard;
  latitude: number;
  longitude: number;
  altitudeM: number;
  velocityMs: number;
  headingDeg: number;
  verticalRate: number;
  sampleTimeMs: number;
}

const INTERPOLATION_INTERVAL_MS = 500;
const MAX_EXTRAPOLATION_SECONDS = 30;
const EARTH_RADIUS_M = 6_378_137;
const TRAIL_MAX_POSITIONS = 60; // 60 seconds at 1s intervals
const TRAIL_REDUCED_POSITIONS = 20;
const TRAIL_REBUILD_INTERVAL = 4; // rebuild polylines every Nth interpolation tick

/**
 * Renders aircraft using imperative BillboardCollection for performance.
 * Includes dead-reckoning interpolation so movement stays smooth between API polls.
 */
export function FlightLayer({ viewer, flights, visible }: FlightLayerProps) {
  const collectionRef = useRef<Cesium.BillboardCollection | null>(null);
  const flightMapRef = useRef<Map<string, FlightVisual>>(new Map());
  const interpolationTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const trailCollectionRef = useRef<Cesium.PolylineCollection | null>(null);
  const trailBuffersRef = useRef<Map<string, Cesium.Cartesian3[]>>(new Map());
  const trailTickRef = useRef(0);
  const viewerRef = useRef<Cesium.Viewer | null>(viewer);
  viewerRef.current = viewer;

  const { degradation } = usePerformance();
  const degradationRef = useRef<DegradationLevel>(degradation);
  degradationRef.current = degradation;

  useEffect(() => {
    if (!viewer || viewer.isDestroyed()) return;

    if (!collectionRef.current) {
      collectionRef.current = new Cesium.BillboardCollection({ scene: viewer.scene });
      viewer.scene.primitives.add(collectionRef.current);

      trailCollectionRef.current = new Cesium.PolylineCollection();
      viewer.scene.primitives.add(trailCollectionRef.current);
    }

    return () => {
      if (interpolationTimerRef.current) {
        clearInterval(interpolationTimerRef.current);
        interpolationTimerRef.current = null;
      }

      if (trailCollectionRef.current && !viewer.isDestroyed()) {
        viewer.scene.primitives.remove(trailCollectionRef.current);
      }
      trailCollectionRef.current = null;
      trailBuffersRef.current.clear();

      if (collectionRef.current && !viewer.isDestroyed()) {
        viewer.scene.primitives.remove(collectionRef.current);
      }
      collectionRef.current = null;

      flightMapRef.current.clear();
    };
  }, [viewer]);

  useEffect(() => {
    const bc = collectionRef.current;
    if (!bc) return;

    bc.show = visible;
    if (trailCollectionRef.current) trailCollectionRef.current.show = visible;
    if (!visible) return;

    const now = Date.now();
    const activeIds = new Set<string>();

    for (const flight of flights) {
      const id = flight.icao24?.trim();
      if (!id) continue;

      activeIds.add(id);

      const sampleTimeMs = parseUtcMs(flight.last_contact, now);

      const flightClickData = {
        icao24: flight.icao24,
        callsign: flight.callsign,
        altitude_m: flight.altitude_m,
        velocity_ms: flight.velocity_ms,
        heading: flight.heading,
        vertical_rate: flight.vertical_rate,
        on_ground: flight.on_ground,
        is_military: flight.is_military,
        aircraft_type: flight.aircraft_type,
        lat: flight.latitude,
        lon: flight.longitude,
      };

      const existing = flightMapRef.current.get(id);
      if (existing) {
        existing.latitude = flight.latitude;
        existing.longitude = flight.longitude;
        existing.altitudeM = flight.altitude_m;
        existing.velocityMs = flight.velocity_ms;
        existing.headingDeg = flight.heading;
        existing.verticalRate = flight.vertical_rate;
        existing.sampleTimeMs = sampleTimeMs;

        const iconType = classifyAircraft(flight.callsign, flight.is_military, flight.aircraft_type, flight.altitude_m, flight.velocity_ms);
        existing.billboard.image = getAircraftTypeIcon(iconType, flight.heading);
        existing.billboard.position = projectPosition(existing, now);
        (existing.billboard as unknown as Record<string, unknown>)._flightData = flightClickData;
      } else {
        const billboard = bc.add({
          position: Cesium.Cartesian3.fromDegrees(
            flight.longitude,
            flight.latitude,
            flight.altitude_m,
          ),
          image: getAircraftTypeIcon(
            classifyAircraft(flight.callsign, flight.is_military, flight.aircraft_type, flight.altitude_m, flight.velocity_ms),
            flight.heading,
          ),
          scale: 0.8,
          eyeOffset: new Cesium.Cartesian3(0, 0, -100),
        });
        (billboard as unknown as Record<string, unknown>)._flightData = flightClickData;

        const visualState: FlightVisual = {
          billboard,
          latitude: flight.latitude,
          longitude: flight.longitude,
          altitudeM: flight.altitude_m,
          velocityMs: flight.velocity_ms,
          headingDeg: flight.heading,
          verticalRate: flight.vertical_rate,
          sampleTimeMs,
        };

        visualState.billboard.position = projectPosition(visualState, now);
        flightMapRef.current.set(id, visualState);
      }
    }

    for (const [id, visual] of flightMapRef.current.entries()) {
      if (!activeIds.has(id)) {
        bc.remove(visual.billboard);
        flightMapRef.current.delete(id);
      }
    }

    // Clean stale trail buffers
    for (const id of trailBuffersRef.current.keys()) {
      if (!activeIds.has(id)) {
        trailBuffersRef.current.delete(id);
      }
    }
  }, [flights, visible]);

  useEffect(() => {
    if (interpolationTimerRef.current) {
      clearInterval(interpolationTimerRef.current);
      interpolationTimerRef.current = null;
    }

    if (!visible) return;

    interpolationTimerRef.current = setInterval(() => {
      const now = Date.now();
      const deg = degradationRef.current;
      const tc = trailCollectionRef.current;
      const tick = ++trailTickRef.current;
      const isTrailTick = tick % 2 === 0; // buffer positions every 2nd tick (1s)
      const isRebuildTick = tick % TRAIL_REBUILD_INTERVAL === 0; // rebuild polylines every 4th tick (2s)

      for (const [id, visual] of flightMapRef.current.entries()) {
        const newPos = projectPosition(visual, now);
        visual.billboard.position = newPos;

        // Trail: buffer positions every 2nd tick, skip if degradation >= 3
        if (isTrailTick && deg < 3 && tc) {
          let buffer = trailBuffersRef.current.get(id);
          if (!buffer) {
            buffer = [];
            trailBuffersRef.current.set(id, buffer);
          }

          buffer.push(newPos);

          const maxLen = deg >= 1 ? TRAIL_REDUCED_POSITIONS : TRAIL_MAX_POSITIONS;
          while (buffer.length > maxLen) {
            buffer.shift();
          }
        }
      }

      // Rebuild trail polylines — only on rebuild ticks, only for flights in current view
      if (!isRebuildTick) return;
      if (tc && deg >= 3) {
        tc.removeAll();
        trailBuffersRef.current.clear();
      } else if (tc && deg < 3) {
        tc.removeAll();

        // Get current camera view rectangle for frustum culling
        const v = viewerRef.current;
        const viewRect = v && !v.isDestroyed()
          ? v.camera.computeViewRectangle(v.scene.globe.ellipsoid)
          : null;

        const MAX_TRAIL_POLYLINES = 500;
        let trailCount = 0;

        for (const [id, buffer] of trailBuffersRef.current.entries()) {
          if (trailCount >= MAX_TRAIL_POLYLINES) break;
          if (buffer.length < 2) continue;

          // Frustum cull: only render trails for flights in current view
          const visual = flightMapRef.current.get(id);
          if (visual && viewRect) {
            const latRad = Cesium.Math.toRadians(visual.latitude);
            const lonRad = Cesium.Math.toRadians(visual.longitude);
            if (
              latRad < viewRect.south || latRad > viewRect.north ||
              lonRad < viewRect.west || lonRad > viewRect.east
            ) continue;
          }

          const fd = (visual?.billboard as unknown as Record<string, unknown>)?._flightData as { is_military?: boolean } | undefined;
          const isMil = fd?.is_military ?? false;

          tc.add({
            positions: buffer.slice(),
            width: isMil ? 2.0 : 1.0,
            material: Cesium.Material.fromType("Color", {
              color: isMil
                ? Cesium.Color.RED.withAlpha(0.5)
                : glyphColor.stone().withAlpha(0.4),
            }),
          });
          trailCount++;
        }
      }
    }, INTERPOLATION_INTERVAL_MS);

    return () => {
      if (interpolationTimerRef.current) {
        clearInterval(interpolationTimerRef.current);
        interpolationTimerRef.current = null;
      }
    };
  }, [visible]);

  return null;
}

function parseUtcMs(value: string | null | undefined, fallback: number): number {
  if (!value) return fallback;
  const ms = Date.parse(value);
  return Number.isNaN(ms) ? fallback : ms;
}

function projectPosition(visual: FlightVisual, nowMs: number): Cesium.Cartesian3 {
  const elapsedSeconds = Math.max(
    0,
    Math.min((nowMs - visual.sampleTimeMs) / 1000, MAX_EXTRAPOLATION_SECONDS),
  );

  const distanceM = Math.max(0, visual.velocityMs) * elapsedSeconds;
  const headingRad = Cesium.Math.toRadians(visual.headingDeg || 0);
  const latRad = Cesium.Math.toRadians(visual.latitude);
  const lonRad = Cesium.Math.toRadians(visual.longitude);

  const angularDistance = distanceM / EARTH_RADIUS_M;
  const sinLat = Math.sin(latRad);
  const cosLat = Math.cos(latRad);
  const sinAD = Math.sin(angularDistance);
  const cosAD = Math.cos(angularDistance);

  const projectedLat = Math.asin(
    sinLat * cosAD + cosLat * sinAD * Math.cos(headingRad),
  );

  const projectedLon =
    lonRad +
    Math.atan2(
      Math.sin(headingRad) * sinAD * cosLat,
      cosAD - sinLat * Math.sin(projectedLat),
    );

  const altitudeM = Math.max(0, visual.altitudeM + visual.verticalRate * elapsedSeconds);

  return Cesium.Cartesian3.fromDegrees(
    Cesium.Math.toDegrees(Cesium.Math.negativePiToPi(projectedLon)),
    Cesium.Math.toDegrees(projectedLat),
    altitudeM,
  );
}
