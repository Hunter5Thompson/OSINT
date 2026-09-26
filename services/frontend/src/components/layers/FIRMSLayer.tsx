import { useEffect, useRef, useCallback } from "react";
import * as Cesium from "cesium";
import type { FIRMSHotspot } from "../../types";
import {
  getViewBounds,
  selectVisible,
  bulkScaleByDistance,
  bulkTranslucencyByDistance,
} from "../../lib/lod";

const MAX_FIRMS = 400;

export function frpToSize(frp: number): number {
  return Math.min(14, 4 + Math.min(frp / 5, 10));
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

interface FIRMSLayerProps {
  viewer: Cesium.Viewer | null;
  hotspots: FIRMSHotspot[];
  visible: boolean;
  onSelect?: (h: FIRMSHotspot) => void;
}

export function FIRMSLayer({ viewer, hotspots, visible, onSelect }: FIRMSLayerProps) {
  const collectionRef = useRef<Cesium.BillboardCollection | null>(null);
  const idMapRef = useRef<Map<object, FIRMSHotspot>>(new Map());
  const handlerRef = useRef<Cesium.ScreenSpaceEventHandler | null>(null);
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;

  const hotspotsRef = useRef(hotspots);
  hotspotsRef.current = hotspots;
  const visibleRef = useRef(visible);
  visibleRef.current = visible;

  // Setup: create BillboardCollection + ScreenSpaceEventHandler click handler
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
      if (handlerRef.current) {
        handlerRef.current.destroy();
        handlerRef.current = null;
      }
      if (!viewer.isDestroyed() && collectionRef.current) {
        viewer.scene.primitives.remove(collectionRef.current);
      }
      collectionRef.current = null;
      idMapRef.current.clear();
    };
  }, [viewer]);

  const renderVisible = useCallback(() => {
    const bc = collectionRef.current;
    if (!bc || !viewer || viewer.isDestroyed()) return;

    bc.removeAll();
    idMapRef.current.clear();
    if (!visibleRef.current) return;

    const bounds = getViewBounds(viewer);
    const shown = selectVisible(
      hotspotsRef.current,
      (h) => [h.longitude, h.latitude] as const,
      bounds,
      { cap: MAX_FIRMS, rank: (h) => h.frp },
    );

    // Shared immutable NearFarScalar instances, reused across every billboard this pass.
    const scaleByDistance = bulkScaleByDistance();
    const translucencyByDistance = bulkTranslucencyByDistance();

    for (const h of shown) {
      const position = Cesium.Cartesian3.fromDegrees(h.longitude, h.latitude, 0);
      const size = frpToSize(h.frp);
      const color = frpToColor(h.frp);
      const dot = bc.add({
        position,
        image: createFIRMSDot(size, color),
        scale: 0.7,
        eyeOffset: new Cesium.Cartesian3(0, 0, -45),
        scaleByDistance,
        translucencyByDistance,
      });
      idMapRef.current.set(dot as unknown as object, h);
    }
  }, [viewer]);

  // Re-render on data / visibility change
  useEffect(() => {
    renderVisible();
  }, [hotspots, visible, renderVisible]);

  // Re-render on camera move (viewport culling)
  useEffect(() => {
    if (!viewer || viewer.isDestroyed()) return;
    const onMoveEnd = () => renderVisible();
    viewer.camera.moveEnd.addEventListener(onMoveEnd);
    return () => {
      if (!viewer.isDestroyed()) viewer.camera.moveEnd.removeEventListener(onMoveEnd);
    };
  }, [viewer, renderVisible]);

  return null;
}
