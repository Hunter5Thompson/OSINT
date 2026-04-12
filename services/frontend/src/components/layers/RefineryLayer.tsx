import { useEffect, useRef } from "react";
import * as Cesium from "cesium";
import type { RefineryGeoJSON, RefineryProperties } from "../../types";

const ICON_COLOR = "#ff8f00";
const LABEL_ALTITUDE_THRESHOLD = 5_000_000;

export function createRefineryIcon(size = 32): HTMLCanvasElement {
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d");
  if (!ctx) return canvas;

  const baseY = size * 0.85;

  const towerW = size * 0.22;
  const towerH = size * 0.55;
  const towerX = size * 0.38;
  const towerY = baseY - towerH;
  const towerR = towerW / 2;
  ctx.fillStyle = "rgba(255, 143, 0, 0.2)";
  ctx.strokeStyle = ICON_COLOR;
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.roundRect(towerX, towerY, towerW, towerH, towerR);
  ctx.fill();
  ctx.stroke();

  const colW = size * 0.16;
  const colH = size * 0.4;
  const colX = size * 0.14;
  const colY = baseY - colH;
  ctx.fillStyle = "rgba(255, 143, 0, 0.15)";
  ctx.lineWidth = 1.2;
  ctx.beginPath();
  ctx.roundRect(colX, colY, colW, colH, colW / 2);
  ctx.fill();
  ctx.stroke();

  const chimW = size * 0.1;
  const chimH = size * 0.45;
  const chimX = size * 0.7;
  const chimY = baseY - chimH;
  ctx.fillStyle = "rgba(255, 143, 0, 0.15)";
  ctx.lineWidth = 1.2;
  ctx.beginPath();
  ctx.roundRect(chimX, chimY, chimW, chimH, 1);
  ctx.fill();
  ctx.stroke();

  const smokeX = chimX + chimW / 2;
  ctx.fillStyle = "rgba(255, 143, 0, 0.12)";
  ctx.strokeStyle = ICON_COLOR;
  ctx.lineWidth = 0.8;
  ctx.beginPath();
  ctx.arc(smokeX, chimY - size * 0.06, size * 0.06, 0, Math.PI * 2);
  ctx.fill();
  ctx.stroke();
  ctx.beginPath();
  ctx.arc(smokeX + size * 0.04, chimY - size * 0.14, size * 0.045, 0, Math.PI * 2);
  ctx.fill();
  ctx.stroke();

  ctx.strokeStyle = ICON_COLOR;
  ctx.lineWidth = 1.2;
  ctx.beginPath();
  ctx.moveTo(colX + colW, colY + colH * 0.4);
  ctx.lineTo(towerX, towerY + towerH * 0.4);
  ctx.stroke();
  ctx.beginPath();
  ctx.moveTo(towerX + towerW, towerY + towerH * 0.5);
  ctx.lineTo(chimX, chimY + chimH * 0.5);
  ctx.stroke();

  ctx.strokeStyle = ICON_COLOR;
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.moveTo(size * 0.06, baseY);
  ctx.lineTo(size * 0.88, baseY);
  ctx.stroke();

  return canvas;
}

interface RefineryLayerProps {
  viewer: Cesium.Viewer | null;
  refineries: RefineryGeoJSON | null;
  visible: boolean;
  onSelect?: (props: RefineryProperties) => void;
}

export function RefineryLayer({ viewer, refineries, visible, onSelect }: RefineryLayerProps) {
  const billboardCollectionRef = useRef<Cesium.BillboardCollection | null>(null);
  const labelCollectionRef = useRef<Cesium.LabelCollection | null>(null);
  const idMapRef = useRef<Map<object, RefineryProperties>>(new Map());
  const handlerRef = useRef<Cesium.ScreenSpaceEventHandler | null>(null);
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;
  const iconRef = useRef<HTMLCanvasElement | null>(null);

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
        const props = idMapRef.current.get(picked.primitive as unknown as object);
        if (props && onSelectRef.current) onSelectRef.current(props);
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
    if (!visible || !refineries) return;

    if (!iconRef.current) {
      iconRef.current = createRefineryIcon(32);
    }

    for (const feature of refineries.features) {
      const [lon, lat] = feature.geometry.coordinates;
      const position = Cesium.Cartesian3.fromDegrees(lon, lat);

      const bb = bc.add({
        position,
        image: iconRef.current,
        scale: 0.8,
        eyeOffset: new Cesium.Cartesian3(0, 0, -20),
      });
      idMapRef.current.set(bb as unknown as object, feature.properties);

      lc.add({
        position,
        text: feature.properties.name,
        font: "11px monospace",
        fillColor: Cesium.Color.fromCssColorString(ICON_COLOR).withAlpha(0.9),
        outlineColor: Cesium.Color.BLACK,
        outlineWidth: 2,
        style: Cesium.LabelStyle.FILL_AND_OUTLINE,
        pixelOffset: new Cesium.Cartesian2(0, -22),
        distanceDisplayCondition: new Cesium.DistanceDisplayCondition(0, LABEL_ALTITUDE_THRESHOLD),
        scale: 0.9,
      });
    }
  }, [refineries, visible, viewer]);

  return null;
}
