import { useEffect, useRef } from "react";
import * as Cesium from "cesium";
import type { IntelEvent } from "../../types";
import { usePerformance } from "../globe/PerformanceGuard";

interface EventLayerProps {
  viewer: Cesium.Viewer | null;
  events: IntelEvent[];
  visible: boolean;
}

const EVENT_COLORS: Record<string, string> = {
  military: "#ef4444",
  space: "#06b6d4",
  cyber: "#a855f7",
  political: "#f97316",
  economic: "#eab308",
  environmental: "#22c55e",
};

const DEFAULT_COLOR = "#6b7280";

function getCategoryColor(codebook_type: string): string {
  const category = codebook_type.split(".")[0] ?? "";
  return EVENT_COLORS[category] ?? DEFAULT_COLOR;
}

interface EventPulse {
  billboard: Cesium.Billboard;
  severity: string;
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

  useEffect(() => {
    const bc = collectionRef.current;
    const lc = labelCollectionRef.current;
    if (!bc || !lc) return;

    bc.removeAll();
    lc.removeAll();
    pulsesRef.current = [];

    if (!visible) return;

    for (const event of events) {
      if (event.lat == null || event.lon == null) continue;

      const position = Cesium.Cartesian3.fromDegrees(event.lon, event.lat, 0);
      const color = getCategoryColor(event.codebook_type);

      const billboard = bc.add({
        position,
        image: createEventCanvas(color),
        scale: 1.0,
        eyeOffset: new Cesium.Cartesian3(0, 0, -100),
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

      const label = event.title.length > 20 ? event.title.slice(0, 18) + "…" : event.title;
      lc.add({
        position,
        text: label,
        font: "10px monospace",
        fillColor: Cesium.Color.fromCssColorString(color),
        outlineColor: Cesium.Color.BLACK,
        outlineWidth: 2,
        style: Cesium.LabelStyle.FILL_AND_OUTLINE,
        pixelOffset: new Cesium.Cartesian2(0, -18),
        eyeOffset: new Cesium.Cartesian3(0, 0, -100),
      });

      if (event.severity === "critical" || event.severity === "high") {
        pulsesRef.current.push({ billboard, severity: event.severity });
      }
    }
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
