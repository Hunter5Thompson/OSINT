import { useEffect, useRef } from "react";
import * as Cesium from "cesium";
import type { EONETEvent } from "../../types";

const LABEL_ALTITUDE_THRESHOLD = 5_000_000;

function createEONETIcon(category: string, size = 24): HTMLCanvasElement {
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d");
  if (!ctx) return canvas;
  const cx = size / 2;
  const cy = size / 2;

  switch (category.toLowerCase()) {
    case "volcanoes": {
      // Red triangle
      ctx.fillStyle = "rgba(220, 38, 38, 0.9)";
      ctx.strokeStyle = "rgba(255, 80, 80, 0.9)";
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.moveTo(cx, size * 0.1);
      ctx.lineTo(size * 0.9, size * 0.9);
      ctx.lineTo(size * 0.1, size * 0.9);
      ctx.closePath();
      ctx.fill();
      ctx.stroke();
      break;
    }
    case "wildfires": {
      // Orange flame
      ctx.fillStyle = "rgba(249, 115, 22, 0.9)";
      ctx.strokeStyle = "rgba(255, 160, 60, 0.7)";
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(cx, size * 0.1);
      ctx.bezierCurveTo(size * 0.85, size * 0.25, size * 0.9, size * 0.55, cx, size * 0.9);
      ctx.bezierCurveTo(size * 0.1, size * 0.55, size * 0.15, size * 0.25, cx, size * 0.1);
      ctx.fill();
      ctx.stroke();
      break;
    }
    case "severestorms": {
      // Purple spiral
      ctx.strokeStyle = "rgba(168, 85, 247, 0.9)";
      ctx.lineWidth = 2.5;
      ctx.beginPath();
      for (let i = 0; i <= 720; i++) {
        const angle = (i * Math.PI) / 180;
        const r = (i / 720) * (size * 0.42);
        const x = cx + r * Math.cos(angle);
        const y = cy + r * Math.sin(angle);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.stroke();
      break;
    }
    case "floods":
    case "seaLakeIce":
    case "sealakeice": {
      // Blue circle
      ctx.fillStyle = "rgba(59, 130, 246, 0.85)";
      ctx.strokeStyle = "rgba(147, 197, 253, 0.8)";
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.arc(cx, cy, size * 0.4, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
      break;
    }
    default: {
      // Gray circle
      ctx.fillStyle = "rgba(156, 163, 175, 0.8)";
      ctx.strokeStyle = "rgba(209, 213, 219, 0.6)";
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.arc(cx, cy, size * 0.4, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
      break;
    }
  }

  return canvas;
}

interface EONETLayerProps {
  viewer: Cesium.Viewer | null;
  events: EONETEvent[];
  visible: boolean;
  onSelect?: (e: EONETEvent) => void;
}

export function EONETLayer({ viewer, events, visible, onSelect }: EONETLayerProps) {
  const billboardCollectionRef = useRef<Cesium.BillboardCollection | null>(null);
  const labelCollectionRef = useRef<Cesium.LabelCollection | null>(null);
  const idMapRef = useRef<Map<object, EONETEvent>>(new Map());
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
      const icon = createEONETIcon(ev.category, 24);
      const bb = bc.add({
        position,
        image: icon,
        scale: 0.8,
        eyeOffset: new Cesium.Cartesian3(0, 0, -30),
      });
      idMapRef.current.set(bb as unknown as object, ev);

      lc.add({
        position,
        text: ev.title,
        font: "11px monospace",
        fillColor: Cesium.Color.fromCssColorString("#f97316").withAlpha(0.9),
        outlineColor: Cesium.Color.BLACK,
        outlineWidth: 2,
        style: Cesium.LabelStyle.FILL_AND_OUTLINE,
        pixelOffset: new Cesium.Cartesian2(0, -22),
        distanceDisplayCondition: new Cesium.DistanceDisplayCondition(0, LABEL_ALTITUDE_THRESHOLD),
        scale: 0.9,
      });
    }
  }, [events, visible, viewer]);

  return null;
}
