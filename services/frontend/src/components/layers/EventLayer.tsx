import { useCallback, useEffect, useRef } from "react";
import * as Cesium from "cesium";
import type { IntelEvent } from "../../types";
import { usePerformance } from "../globe/PerformanceGuard";

interface EventLayerProps {
  viewer: Cesium.Viewer | null;
  events: IntelEvent[];
  visible: boolean;
}

export const EVENT_COLORS: Record<string, string> = {
  military: "#ef4444",         // red — direct military action
  conflict: "#dc2626",         // deeper red — kinetic violence (armed, mass_violence)
  posture: "#f59e0b",          // amber — pre-combat positioning, mobilization
  civil: "#a3e635",            // lime — civilian protest, demonstration, unrest
  political: "#f97316",        // orange — elections, summits, treaties
  economic: "#eab308",         // yellow — sanctions, trade, market events
  space: "#06b6d4",            // cyan — launches, orbital activity
  cyber: "#a855f7",            // purple — attacks, breaches, disinfo
  environmental: "#22c55e",    // green — quakes, floods, wildfires
  social: "#ec4899",           // pink — mass protest, labor, ethnic violence
  humanitarian: "#fb7185",     // rose — refugees, famine, casualties
  infrastructure: "#94a3b8",   // slate — built environment failures
  other: "#6b7280",            // gray — unclassified fallback
};

export const DEFAULT_COLOR = "#6b7280";
const LABEL_ALTITUDE_THRESHOLD = 2_500_000;
const EVENT_ALTITUDE_M = 300;
const POSITION_BUCKET_DEG = 0.12;
const STACK_RADIUS_KM = 18;

export function getCategoryColor(codebook_type: string): string {
  const category = codebook_type.split(".")[0] ?? "";
  return EVENT_COLORS[category] ?? DEFAULT_COLOR;
}

interface EventPulse {
  billboard: Cesium.Billboard;
  severity: string;
}

export interface EventPlacement {
  event: IntelEvent;
  renderLat: number;
  renderLon: number;
  stackIndex: number;
  stackSize: number;
}

function bucketKey(lat: number, lon: number): string {
  const latKey = Math.round(lat / POSITION_BUCKET_DEG);
  const lonKey = Math.round(lon / POSITION_BUCKET_DEG);
  return `${latKey}:${lonKey}`;
}

function offsetPosition(lat: number, lon: number, idx: number, count: number): [number, number] {
  if (count <= 1) return [lat, lon];
  const ring = Math.floor(idx / 8);
  const slot = idx % 8;
  const steps = Math.min(8, count - ring * 8);
  const angle = (2 * Math.PI * slot) / steps;
  const radiusKm = STACK_RADIUS_KM * (1 + ring * 0.7);

  const latDegPerKm = 1 / 111;
  const lonDegPerKm = 1 / (111 * Math.max(0.2, Math.cos((lat * Math.PI) / 180)));

  const nextLat = lat + Math.sin(angle) * radiusKm * latDegPerKm;
  const nextLon = lon + Math.cos(angle) * radiusKm * lonDegPerKm;

  return [Math.max(-85, Math.min(85, nextLat)), nextLon];
}

export function buildPlacements(events: IntelEvent[]): EventPlacement[] {
  const byBucket = new Map<string, IntelEvent[]>();
  for (const event of events) {
    if (event.lat == null || event.lon == null) continue;
    const key = bucketKey(event.lat, event.lon);
    const list = byBucket.get(key);
    if (list) {
      list.push(event);
    } else {
      byBucket.set(key, [event]);
    }
  }

  const result: EventPlacement[] = [];
  for (const groupedEvents of byBucket.values()) {
    const stackSize = groupedEvents.length;
    for (let i = 0; i < groupedEvents.length; i += 1) {
      const event = groupedEvents[i]!;
      const [renderLat, renderLon] = offsetPosition(event.lat as number, event.lon as number, i, stackSize);
      result.push({
        event,
        renderLat,
        renderLon,
        stackIndex: i,
        stackSize,
      });
    }
  }

  return result;
}

/**
 * Renders intel events with severity-based pulse animations.
 * - critical: fast pulse (2 Hz)
 * - high: slow pulse (0.5 Hz)
 * - medium/low: static marker
 */
export function EventLayer({ viewer, events, visible }: EventLayerProps) {
  const collectionRef = useRef<Cesium.BillboardCollection | null>(null);
  const labelCollectionRef = useRef<Cesium.LabelCollection | null>(null);
  const pulsesRef = useRef<EventPulse[]>([]);
  const animFrameRef = useRef<number | null>(null);
  const labelsVisibleRef = useRef(false);
  const { degradation } = usePerformance();
  const degradationRef = useRef(degradation);
  degradationRef.current = degradation;

  useEffect(() => {
    if (!viewer || viewer.isDestroyed()) return;

    if (!collectionRef.current) {
      collectionRef.current = new Cesium.BillboardCollection({ scene: viewer.scene });
      viewer.scene.primitives.add(collectionRef.current);
    }
    if (!labelCollectionRef.current) {
      labelCollectionRef.current = new Cesium.LabelCollection({ scene: viewer.scene });
      viewer.scene.primitives.add(labelCollectionRef.current);
    }

    return () => {
      if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);
      if (!viewer.isDestroyed()) {
        if (collectionRef.current) viewer.scene.primitives.remove(collectionRef.current);
        if (labelCollectionRef.current) viewer.scene.primitives.remove(labelCollectionRef.current);
      }
      collectionRef.current = null;
      labelCollectionRef.current = null;
      pulsesRef.current = [];
    };
  }, [viewer]);

  const updateLabelVisibility = useCallback(() => {
    if (!viewer || viewer.isDestroyed()) return;
    const lc = labelCollectionRef.current;
    if (!lc) return;

    const shouldShow = viewer.camera.positionCartographic.height < LABEL_ALTITUDE_THRESHOLD;
    if (shouldShow !== labelsVisibleRef.current) {
      labelsVisibleRef.current = shouldShow;
      lc.show = shouldShow && visible;
    }
  }, [viewer, visible]);

  useEffect(() => {
    if (!viewer || viewer.isDestroyed()) return;
    const removeListener = viewer.camera.moveEnd.addEventListener(updateLabelVisibility);
    updateLabelVisibility();
    return () => removeListener();
  }, [viewer, updateLabelVisibility]);

  useEffect(() => {
    const bc = collectionRef.current;
    const lc = labelCollectionRef.current;
    if (!bc || !lc) return;

    bc.removeAll();
    lc.removeAll();
    pulsesRef.current = [];

    if (!visible) return;

    const placements = buildPlacements(events);

    for (const placement of placements) {
      const event = placement.event;
      const position = Cesium.Cartesian3.fromDegrees(placement.renderLon, placement.renderLat, EVENT_ALTITUDE_M);
      const color = getCategoryColor(event.codebook_type);

      const billboard = bc.add({
        position,
        image: createEventCanvas(color),
        scale: placement.stackSize > 1 ? 0.9 : 1.0,
        eyeOffset: new Cesium.Cartesian3(0, 0, -100),
        disableDepthTestDistance: Number.POSITIVE_INFINITY,
        scaleByDistance: new Cesium.NearFarScalar(100_000, 1.0, 12_000_000, 0.45),
        translucencyByDistance: new Cesium.NearFarScalar(100_000, 1.0, 14_000_000, 0.35),
      });

      (billboard as unknown as Record<string, unknown>)._eventData = {
        id: event.id,
        title: event.title,
        codebook_type: event.codebook_type,
        severity: event.severity,
        location_name: event.location_name,
        lat: event.lat,
        lon: event.lon,
      };

      const shouldLabel = placement.stackIndex === 0;
      if (shouldLabel) {
        const baseLabel = event.title.length > 20 ? event.title.slice(0, 18) + "…" : event.title;
        const labelText = placement.stackSize > 1 ? `${baseLabel} (+${placement.stackSize - 1})` : baseLabel;

        lc.add({
          position,
          text: labelText,
          font: "10px monospace",
          fillColor: Cesium.Color.fromCssColorString(color),
          outlineColor: Cesium.Color.BLACK,
          outlineWidth: 2,
          style: Cesium.LabelStyle.FILL_AND_OUTLINE,
          pixelOffset: new Cesium.Cartesian2(0, -18),
          eyeOffset: new Cesium.Cartesian3(0, 0, -100),
          disableDepthTestDistance: Number.POSITIVE_INFINITY,
          distanceDisplayCondition: new Cesium.DistanceDisplayCondition(0, LABEL_ALTITUDE_THRESHOLD),
          show: labelsVisibleRef.current,
        });
      }

      if (event.severity === "critical" || event.severity === "high") {
        pulsesRef.current.push({ billboard, severity: event.severity });
      }
    }

    bc.show = visible;
    lc.show = visible && labelsVisibleRef.current;
  }, [events, visible]);

  // Pulse animation loop
  useEffect(() => {
    if (!visible) {
      if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);
      return;
    }

    const animate = () => {
      const now = Date.now();
      const deg = degradationRef.current;

      if (deg < 2) {
        for (const pulse of pulsesRef.current) {
          if (pulse.severity === "critical") {
            // 2 Hz fast pulse
            pulse.billboard.scale = 1.0 + 0.3 * Math.sin(now * 0.0126);
          } else if (pulse.severity === "high") {
            // 0.5 Hz slow pulse
            pulse.billboard.scale = 1.0 + 0.15 * Math.sin(now * 0.00314);
          }
        }
      } else {
        // Reset scales when animations are degraded
        for (const pulse of pulsesRef.current) {
          pulse.billboard.scale = 1.0;
        }
      }

      animFrameRef.current = requestAnimationFrame(animate);
    };

    animFrameRef.current = requestAnimationFrame(animate);

    return () => {
      if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);
    };
  }, [visible]);

  return null;
}

function createEventCanvas(color: string): HTMLCanvasElement {
  const size = 24;
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d");
  if (!ctx) return canvas;

  const cx = size / 2;
  const cy = size / 2;
  const r = 8;

  ctx.beginPath();
  ctx.moveTo(cx, cy - r);
  ctx.lineTo(cx + r, cy);
  ctx.lineTo(cx, cy + r);
  ctx.lineTo(cx - r, cy);
  ctx.closePath();
  ctx.fillStyle = color;
  ctx.globalAlpha = 0.85;
  ctx.fill();
  ctx.globalAlpha = 1.0;
  ctx.strokeStyle = color;
  ctx.lineWidth = 1.5;
  ctx.stroke();

  return canvas;
}
