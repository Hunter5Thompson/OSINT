import { useEffect, useRef } from "react";
import * as Cesium from "cesium";
import type { FIRMSHotspot } from "../../types";

export function frpToSize(frp: number): number {
  return Math.min(22, 6 + Math.min(frp / 4, 16));
}

export function frpToColor(frp: number): Cesium.Color {
  const clamped = Math.max(0, Math.min(100, frp));
  const t = clamped / 100;
  if (t < 0.5) {
    const k = t / 0.5;
    return new Cesium.Color(1.0, 1.0 - 0.35 * k, 0.0, 1.0);
  }
  const k = (t - 0.5) / 0.5;
  return new Cesium.Color(1.0, 0.65 * (1 - k), 0.0, 1.0);
}

export function createFIRMSDot(radius: number, color: Cesium.Color): HTMLCanvasElement {
  const canvasSize = Math.ceil(radius * 4);
  const canvas = document.createElement("canvas");
  canvas.width = canvasSize;
  canvas.height = canvasSize;
  const ctx = canvas.getContext("2d");
  if (!ctx) return canvas;
  const center = canvasSize / 2;
  const grad = ctx.createRadialGradient(center, center, radius * 0.2, center, center, radius);
  grad.addColorStop(0, `rgba(${color.red * 255}, ${color.green * 255}, ${color.blue * 255}, 1.0)`);
  grad.addColorStop(1, `rgba(${color.red * 255}, ${color.green * 255}, ${color.blue * 255}, 0.0)`);
  ctx.fillStyle = grad;
  ctx.beginPath();
  ctx.arc(center, center, radius, 0, Math.PI * 2);
  ctx.fill();
  return canvas;
}

export function createFIRMSRing(size: number, color: Cesium.Color): HTMLCanvasElement {
  const canvasSize = Math.ceil(size * 4);
  const canvas = document.createElement("canvas");
  canvas.width = canvasSize;
  canvas.height = canvasSize;
  const ctx = canvas.getContext("2d");
  if (!ctx) return canvas;
  const center = canvasSize / 2;
  ctx.beginPath();
  ctx.arc(center, center, size, 0, Math.PI * 2);
  ctx.strokeStyle = `rgba(${color.red * 255}, ${color.green * 255}, ${color.blue * 255}, 0.8)`;
  ctx.lineWidth = 2;
  ctx.stroke();
  return canvas;
}

interface FIRMSLayerProps {
  viewer: Cesium.Viewer | null;
  hotspots: FIRMSHotspot[];
  visible: boolean;
  onSelect?: (h: FIRMSHotspot) => void;
}

interface FIRMSPulse {
  ring: Cesium.Billboard;
  color: Cesium.Color;
}

export function FIRMSLayer({ viewer, hotspots, visible, onSelect }: FIRMSLayerProps) {
  const collectionRef = useRef<Cesium.BillboardCollection | null>(null);
  const idMapRef = useRef<Map<object, FIRMSHotspot>>(new Map());
  const pulsesRef = useRef<FIRMSPulse[]>([]);
  const animFrameRef = useRef<number | null>(null);
  const handlerRef = useRef<Cesium.ScreenSpaceEventHandler | null>(null);
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;

  useEffect(() => {
    if (!viewer || viewer.isDestroyed()) return;
    if (!collectionRef.current) {
      collectionRef.current = new Cesium.BillboardCollection({ scene: viewer.scene });
      viewer.scene.primitives.add(collectionRef.current);
    }
    if (!handlerRef.current) {
      const h = new Cesium.ScreenSpaceEventHandler(viewer.canvas);
      h.setInputAction((movement: Cesium.ScreenSpaceEventHandler.PositionedEvent) => {
        const picked = viewer.scene.pick(movement.position);
        if (!picked) return;
        const hotspot = idMapRef.current.get(picked.primitive as unknown as object);
        if (hotspot && onSelectRef.current) onSelectRef.current(hotspot);
      }, Cesium.ScreenSpaceEventType.LEFT_CLICK);
      handlerRef.current = h;
    }
    return () => {
      if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);
      if (handlerRef.current) {
        handlerRef.current.destroy();
        handlerRef.current = null;
      }
      if (!viewer.isDestroyed() && collectionRef.current) {
        viewer.scene.primitives.remove(collectionRef.current);
      }
      collectionRef.current = null;
      idMapRef.current.clear();
      pulsesRef.current = [];
    };
  }, [viewer]);

  useEffect(() => {
    const bc = collectionRef.current;
    if (!bc) return;
    bc.removeAll();
    idMapRef.current.clear();
    pulsesRef.current = [];
    if (!visible) return;

    for (const h of hotspots) {
      const position = Cesium.Cartesian3.fromDegrees(h.longitude, h.latitude, 0);
      const size = frpToSize(h.frp);
      const color = frpToColor(h.frp);
      const dot = bc.add({
        position,
        image: createFIRMSDot(size, color),
        scale: 1.0,
        eyeOffset: new Cesium.Cartesian3(0, 0, -45),
      });
      idMapRef.current.set(dot as unknown as object, h);
      if (h.possible_explosion) {
        const ring = bc.add({
          position,
          image: createFIRMSRing(size * 1.5, color),
          scale: 1.0,
          eyeOffset: new Cesium.Cartesian3(0, 0, -44),
        });
        pulsesRef.current.push({ ring, color });
      }
    }
  }, [hotspots, visible]);

  useEffect(() => {
    if (!visible || pulsesRef.current.length === 0) {
      if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);
      return;
    }
    const animate = () => {
      const now = Date.now();
      const phase = (now * 0.003) % (Math.PI * 2);
      const scale = 1.0 + 0.5 * Math.sin(phase);
      const alpha = 0.8 - 0.4 * Math.sin(phase);
      for (const p of pulsesRef.current) {
        p.ring.scale = scale;
        p.ring.color = p.color.withAlpha(alpha);
      }
      animFrameRef.current = requestAnimationFrame(animate);
    };
    animFrameRef.current = requestAnimationFrame(animate);
    return () => {
      if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);
    };
  }, [visible, hotspots]);

  return null;
}
