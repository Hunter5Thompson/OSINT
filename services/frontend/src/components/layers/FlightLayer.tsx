import { useEffect, useRef } from "react";
import * as Cesium from "cesium";
import type { Aircraft } from "../../types";

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

/**
 * Renders aircraft using imperative BillboardCollection for performance.
 * Includes dead-reckoning interpolation so movement stays smooth between API polls.
 */
export function FlightLayer({ viewer, flights, visible }: FlightLayerProps) {
  const collectionRef = useRef<Cesium.BillboardCollection | null>(null);
  const flightMapRef = useRef<Map<string, FlightVisual>>(new Map());
  const iconCacheRef = useRef<Map<string, string>>(new Map());
  const interpolationTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (!viewer || viewer.isDestroyed()) return;

    if (!collectionRef.current) {
      collectionRef.current = new Cesium.BillboardCollection({ scene: viewer.scene });
      viewer.scene.primitives.add(collectionRef.current);
    }

    return () => {
      if (interpolationTimerRef.current) {
        clearInterval(interpolationTimerRef.current);
        interpolationTimerRef.current = null;
      }

      if (collectionRef.current && !viewer.isDestroyed()) {
        viewer.scene.primitives.remove(collectionRef.current);
        collectionRef.current = null;
      }

      flightMapRef.current.clear();
      iconCacheRef.current.clear();
    };
  }, [viewer]);

  useEffect(() => {
    const bc = collectionRef.current;
    if (!bc) return;

    bc.show = visible;
    if (!visible) return;

    const now = Date.now();
    const activeIds = new Set<string>();

    for (const flight of flights) {
      const id = flight.icao24?.trim();
      if (!id) continue;

      activeIds.add(id);

      const color = flight.is_military
        ? Cesium.Color.RED
        : flight.on_ground
          ? Cesium.Color.GRAY
          : Cesium.Color.CYAN;

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

        existing.billboard.color = color;
        existing.billboard.image = getAircraftIconCanvas(
          flight.heading,
          color,
          iconCacheRef.current,
        );
        existing.billboard.position = projectPosition(existing, now);
        (existing.billboard as unknown as Record<string, unknown>)._flightData = flightClickData;
      } else {
        const billboard = bc.add({
          position: Cesium.Cartesian3.fromDegrees(
            flight.longitude,
            flight.latitude,
            flight.altitude_m,
          ),
          image: getAircraftIconCanvas(flight.heading, color, iconCacheRef.current),
          scale: 0.5,
          color,
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
  }, [flights, visible]);

  useEffect(() => {
    if (interpolationTimerRef.current) {
      clearInterval(interpolationTimerRef.current);
      interpolationTimerRef.current = null;
    }

    if (!visible) return;

    interpolationTimerRef.current = setInterval(() => {
      const now = Date.now();
      for (const visual of flightMapRef.current.values()) {
        visual.billboard.position = projectPosition(visual, now);
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

function getAircraftIconCanvas(
  heading: number,
  color: Cesium.Color,
  cache: Map<string, string>,
): string {
  const headingBucket = Math.round((heading || 0) / 5) * 5;
  const colorKey = `${Math.round(color.red * 255)}-${Math.round(color.green * 255)}-${Math.round(color.blue * 255)}`;
  const key = `${headingBucket}-${colorKey}`;

  const cachedDataUrl = cache.get(key);
  if (cachedDataUrl) return cachedDataUrl;

  const size = 24;
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;

  const ctx = canvas.getContext("2d");
  if (!ctx) {
    const emptyDataUrl = canvas.toDataURL();
    cache.set(key, emptyDataUrl);
    return emptyDataUrl;
  }

  ctx.translate(size / 2, size / 2);
  ctx.rotate((headingBucket * Math.PI) / 180);

  ctx.beginPath();
  ctx.moveTo(0, -size / 2 + 2);
  ctx.lineTo(-size / 4, size / 2 - 4);
  ctx.lineTo(0, size / 3);
  ctx.lineTo(size / 4, size / 2 - 4);
  ctx.closePath();

  ctx.fillStyle = `rgba(${color.red * 255}, ${color.green * 255}, ${color.blue * 255}, 0.9)`;
  ctx.fill();
  ctx.strokeStyle = `rgba(${color.red * 255}, ${color.green * 255}, ${color.blue * 255}, 1)`;
  ctx.lineWidth = 1;
  ctx.stroke();

  const dataUrl = canvas.toDataURL();
  cache.set(key, dataUrl);
  return dataUrl;
}
