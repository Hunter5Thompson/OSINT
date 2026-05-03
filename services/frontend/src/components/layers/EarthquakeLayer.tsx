import { useEffect, useRef } from "react";
import * as Cesium from "cesium";
import type { Earthquake } from "../../types";
import { glyphColor } from "./glyphTokens";
import { usePerformance } from "../globe/PerformanceGuard";

interface EarthquakeLayerProps {
  viewer: Cesium.Viewer | null;
  earthquakes: Earthquake[];
  visible: boolean;
}

function magnitudeToColor(mag: number): Cesium.Color {
  if (mag >= 7.0) return glyphColor.sentinel();
  if (mag >= 6.0) return Cesium.Color.ORANGE;
  if (mag >= 5.0) return Cesium.Color.YELLOW;
  return Cesium.Color.LIME;
}

function magnitudeToSize(mag: number): number {
  return Math.max(6, Math.pow(2, mag - 3));
}

interface QuakePulse {
  billboard: Cesium.Billboard;
  ringBillboard: Cesium.Billboard;
  magnitude: number;
  eventTimeMs: number;
  baseSize: number;
  color: Cesium.Color;
}

/**
 * Renders earthquakes with magnitude-based pulse animations.
 * - M >= 7.0: permanent pulse
 * - M >= 5.0: 30-second pulse after event, then static
 * - M < 5.0: single ripple then static
 */
export function EarthquakeLayer({ viewer, earthquakes, visible }: EarthquakeLayerProps) {
  const collectionRef = useRef<Cesium.BillboardCollection | null>(null);
  const labelCollectionRef = useRef<Cesium.LabelCollection | null>(null);
  const pulsesRef = useRef<QuakePulse[]>([]);
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

  // Render quakes
  useEffect(() => {
    const bc = collectionRef.current;
    const lc = labelCollectionRef.current;
    if (!bc || !lc) return;

    bc.removeAll();
    lc.removeAll();
    pulsesRef.current = [];

    if (!visible) return;

    for (const quake of earthquakes) {
      const position = Cesium.Cartesian3.fromDegrees(quake.longitude, quake.latitude, 0);
      const color = magnitudeToColor(quake.magnitude);
      const size = magnitudeToSize(quake.magnitude);

      // Inner dot (static)
      const billboard = bc.add({
        position,
        image: createQuakeDot(size * 0.4, color),
        scale: 1.0,
        eyeOffset: new Cesium.Cartesian3(0, 0, -50),
      });

      // Outer ring (animated — expanding + fading)
      const ringBillboard = bc.add({
        position,
        image: createQuakeRing(size, color),
        scale: 1.0,
        eyeOffset: new Cesium.Cartesian3(0, 0, -49),
      });

      lc.add({
        position,
        text: `M${quake.magnitude.toFixed(1)}`,
        font: "11px monospace",
        fillColor: color,
        outlineColor: Cesium.Color.BLACK,
        outlineWidth: 2,
        style: Cesium.LabelStyle.FILL_AND_OUTLINE,
        pixelOffset: new Cesium.Cartesian2(0, -size - 5),
        eyeOffset: new Cesium.Cartesian3(0, 0, -50),
      });

      pulsesRef.current.push({
        billboard,
        ringBillboard,
        magnitude: quake.magnitude,
        eventTimeMs: new Date(quake.time).getTime(),
        baseSize: size,
        color,
      });
    }
  }, [earthquakes, visible]);

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
          const ageMs = now - pulse.eventTimeMs;
          const ageSec = ageMs / 1000;
          let ringScale = 1.0;
          let ringAlpha = 0.8;

          if (pulse.magnitude >= 7.0) {
            // Permanent pulse: ring expands + fades cyclically
            const phase = (now * 0.003) % (Math.PI * 2);
            ringScale = 1.0 + 0.5 * Math.sin(phase);
            ringAlpha = 0.8 - 0.4 * Math.sin(phase);
          } else if (pulse.magnitude >= 5.0 && ageSec < 30) {
            // 30-second pulse
            const phase = (now * 0.005) % (Math.PI * 2);
            ringScale = 1.0 + 0.3 * Math.sin(phase);
            ringAlpha = 0.8 - 0.3 * Math.sin(phase);
          } else if (pulse.magnitude < 5.0) {
            // Single ripple: expand + fade out in first 3 seconds, then static
            if (ageSec < 3.0) {
              const t = ageSec / 3.0;
              ringScale = 1.0 + t * 0.5;
              ringAlpha = 0.8 * (1.0 - t);
            } else {
              ringScale = 1.0;
              ringAlpha = 0.0; // ring hidden after ripple
            }
          }

          // Inner dot stays static, outer ring animates
          pulse.ringBillboard.scale = ringScale;
          pulse.ringBillboard.color = pulse.color.withAlpha(ringAlpha);
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

function createQuakeDot(radius: number, color: Cesium.Color): HTMLCanvasElement {
  const canvasSize = Math.ceil(radius * 4);
  const canvas = document.createElement("canvas");
  canvas.width = canvasSize;
  canvas.height = canvasSize;
  const ctx = canvas.getContext("2d");
  if (!ctx) return canvas;

  const center = canvasSize / 2;
  ctx.beginPath();
  ctx.arc(center, center, radius, 0, Math.PI * 2);
  ctx.fillStyle = `rgba(${color.red * 255}, ${color.green * 255}, ${color.blue * 255}, 0.9)`;
  ctx.fill();

  return canvas;
}

function createQuakeRing(size: number, color: Cesium.Color): HTMLCanvasElement {
  const canvasSize = Math.ceil(size * 4);
  const canvas = document.createElement("canvas");
  canvas.width = canvasSize;
  canvas.height = canvasSize;
  const ctx = canvas.getContext("2d");
  if (!ctx) return canvas;

  const center = canvasSize / 2;

  // Two concentric rings
  ctx.beginPath();
  ctx.arc(center, center, size, 0, Math.PI * 2);
  ctx.strokeStyle = `rgba(${color.red * 255}, ${color.green * 255}, ${color.blue * 255}, 0.8)`;
  ctx.lineWidth = 2;
  ctx.stroke();

  ctx.beginPath();
  ctx.arc(center, center, size * 0.65, 0, Math.PI * 2);
  ctx.strokeStyle = `rgba(${color.red * 255}, ${color.green * 255}, ${color.blue * 255}, 0.4)`;
  ctx.lineWidth = 1.5;
  ctx.stroke();

  return canvas;
}
