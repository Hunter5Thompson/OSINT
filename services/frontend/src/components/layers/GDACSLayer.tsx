import { useEffect, useRef } from "react";
import * as Cesium from "cesium";
import type { GDACSEvent } from "../../types";

export const EVENT_TYPE_LABELS: Record<string, string> = {
  EQ: "Earthquake",
  TC: "Tropical Cyclone",
  FL: "Flood",
  VO: "Volcano",
  DR: "Drought",
  WF: "Wildfire",
};

function createGDACSIcon(alertLevel: string, size = 24): HTMLCanvasElement {
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d");
  if (!ctx) return canvas;
  const cx = size / 2;
  const cy = size / 2;

  switch (alertLevel.toLowerCase()) {
    case "red": {
      // Large red radial glow
      const grad = ctx.createRadialGradient(cx, cy, 0, cx, cy, size * 0.48);
      grad.addColorStop(0, "rgba(239, 68, 68, 1.0)");
      grad.addColorStop(0.4, "rgba(239, 68, 68, 0.7)");
      grad.addColorStop(1, "rgba(239, 68, 68, 0.0)");
      ctx.fillStyle = grad;
      ctx.beginPath();
      ctx.arc(cx, cy, size * 0.48, 0, Math.PI * 2);
      ctx.fill();
      // Core
      ctx.fillStyle = "rgba(239, 68, 68, 1.0)";
      ctx.beginPath();
      ctx.arc(cx, cy, size * 0.22, 0, Math.PI * 2);
      ctx.fill();
      break;
    }
    case "orange": {
      // Medium orange radial glow
      const gradO = ctx.createRadialGradient(cx, cy, 0, cx, cy, size * 0.38);
      gradO.addColorStop(0, "rgba(249, 115, 22, 1.0)");
      gradO.addColorStop(0.45, "rgba(249, 115, 22, 0.65)");
      gradO.addColorStop(1, "rgba(249, 115, 22, 0.0)");
      ctx.fillStyle = gradO;
      ctx.beginPath();
      ctx.arc(cx, cy, size * 0.38, 0, Math.PI * 2);
      ctx.fill();
      // Core
      ctx.fillStyle = "rgba(249, 115, 22, 1.0)";
      ctx.beginPath();
      ctx.arc(cx, cy, size * 0.18, 0, Math.PI * 2);
      ctx.fill();
      break;
    }
    case "green": {
      // Small green radial glow
      const gradG = ctx.createRadialGradient(cx, cy, 0, cx, cy, size * 0.28);
      gradG.addColorStop(0, "rgba(34, 197, 94, 1.0)");
      gradG.addColorStop(0.5, "rgba(34, 197, 94, 0.6)");
      gradG.addColorStop(1, "rgba(34, 197, 94, 0.0)");
      ctx.fillStyle = gradG;
      ctx.beginPath();
      ctx.arc(cx, cy, size * 0.28, 0, Math.PI * 2);
      ctx.fill();
      // Core
      ctx.fillStyle = "rgba(34, 197, 94, 1.0)";
      ctx.beginPath();
      ctx.arc(cx, cy, size * 0.14, 0, Math.PI * 2);
      ctx.fill();
      break;
    }
    default: {
      // Gray
      ctx.fillStyle = "rgba(156, 163, 175, 0.8)";
      ctx.beginPath();
      ctx.arc(cx, cy, size * 0.3, 0, Math.PI * 2);
      ctx.fill();
      break;
    }
  }

  return canvas;
}

interface GDACSLayerProps {
  viewer: Cesium.Viewer | null;
  events: GDACSEvent[];
  visible: boolean;
  onSelect?: (e: GDACSEvent) => void;
}

export function GDACSLayer({ viewer, events, visible, onSelect }: GDACSLayerProps) {
  const billboardCollectionRef = useRef<Cesium.BillboardCollection | null>(null);
  const labelCollectionRef = useRef<Cesium.LabelCollection | null>(null);
  const idMapRef = useRef<Map<object, GDACSEvent>>(new Map());
  const handlerRef = useRef<Cesium.ScreenSpaceEventHandler | null>(null);
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;

  useEffect(() => {
    if (!viewer || viewer.isDestroyed()) return;
    if (!billboardCollectionRef.current) {
      billboardCollectionRef.current = new Cesium.BillboardCollection({ scene: viewer.scene });
      viewer.scene.primitives.add(billboardCollectionRef.current);
    }
    if (!labelCollectionRef.current) {
      labelCollectionRef.current = new Cesium.LabelCollection({ scene: viewer.scene });
      viewer.scene.primitives.add(labelCollectionRef.current);
    }
    if (!handlerRef.current) {
      const h = new Cesium.ScreenSpaceEventHandler(viewer.canvas);
      h.setInputAction((movement: Cesium.ScreenSpaceEventHandler.PositionedEvent) => {
        const picked = viewer.scene.pick(movement.position);
        if (!picked) return;
        const event = idMapRef.current.get(picked.primitive as unknown as object);
        if (event && onSelectRef.current) onSelectRef.current(event);
      }, Cesium.ScreenSpaceEventType.LEFT_CLICK);
      handlerRef.current = h;
    }
    return () => {
      if (handlerRef.current) {
        handlerRef.current.destroy();
        handlerRef.current = null;
      }
      if (!viewer.isDestroyed()) {
        if (billboardCollectionRef.current) viewer.scene.primitives.remove(billboardCollectionRef.current);
        if (labelCollectionRef.current) viewer.scene.primitives.remove(labelCollectionRef.current);
      }
      billboardCollectionRef.current = null;
      labelCollectionRef.current = null;
      idMapRef.current.clear();
    };
  }, [viewer]);

  useEffect(() => {
    const bc = billboardCollectionRef.current;
    const lc = labelCollectionRef.current;
    if (!bc || !lc) return;
    bc.removeAll();
    lc.removeAll();
    idMapRef.current.clear();
    if (!visible) return;

    for (const ev of events) {
      const position = Cesium.Cartesian3.fromDegrees(ev.longitude, ev.latitude, 0);
      const icon = createGDACSIcon(ev.alert_level, 24);
      const bb = bc.add({
        position,
        image: icon,
        scale: 0.8,
        eyeOffset: new Cesium.Cartesian3(0, 0, -30),
      });
      idMapRef.current.set(bb as unknown as object, ev);

      const labelText = ev.event_name || (EVENT_TYPE_LABELS[ev.event_type] ?? ev.event_type);
      lc.add({
        position,
        text: labelText,
        font: "11px monospace",
        fillColor: Cesium.Color.fromCssColorString("#ef4444").withAlpha(0.9),
        outlineColor: Cesium.Color.BLACK,
        outlineWidth: 2,
        style: Cesium.LabelStyle.FILL_AND_OUTLINE,
        pixelOffset: new Cesium.Cartesian2(0, -22),
        distanceDisplayCondition: new Cesium.DistanceDisplayCondition(0, 5_000_000),
        scale: 0.9,
      });
    }
  }, [events, visible, viewer]);

  return null;
}
