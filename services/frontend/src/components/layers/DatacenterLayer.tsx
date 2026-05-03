import { useEffect, useRef } from "react";
import * as Cesium from "cesium";
import type { DatacenterGeoJSON, DatacenterProperties } from "../../types";
import { glyphColor } from "./glyphTokens";

const ICON_COLOR = "#00e5ff";
const LABEL_ALTITUDE_THRESHOLD = 5_000_000;

export function createDatacenterIcon(size = 32): HTMLCanvasElement {
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d");
  if (!ctx) return canvas;

  const pad = size * 0.15;
  const w = size - pad * 2;
  const h = size - pad * 2;
  const x = pad;
  const y = pad;

  // Building outline
  ctx.fillStyle = "rgba(0, 229, 255, 0.15)";
  ctx.strokeStyle = ICON_COLOR;
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.roundRect(x, y, w, h, 3);
  ctx.fill();
  ctx.stroke();

  // Server rows (3 shelves)
  const rowH = h * 0.18;
  const rowW = w * 0.7;
  const rowX = x + (w - rowW) / 2;
  for (let i = 0; i < 3; i++) {
    const rowY = y + h * 0.15 + i * (rowH + h * 0.08);
    ctx.fillStyle = "rgba(0, 229, 255, 0.25)";
    ctx.beginPath();
    ctx.roundRect(rowX, rowY, rowW, rowH, 1.5);
    ctx.fill();

    // Status LED
    const ledR = size * 0.04;
    const ledX = rowX + rowW - ledR * 3;
    const ledY = rowY + rowH / 2;
    ctx.fillStyle = i === 1 ? "#00ff88" : ICON_COLOR;
    ctx.beginPath();
    ctx.arc(ledX, ledY, ledR, 0, Math.PI * 2);
    ctx.fill();
  }

  // Network symbol at top
  ctx.strokeStyle = ICON_COLOR;
  ctx.lineWidth = 1.2;
  const topCx = size / 2;
  const topCy = y - size * 0.02;
  ctx.beginPath();
  ctx.arc(topCx, topCy, size * 0.07, 0, Math.PI * 2);
  ctx.stroke();
  ctx.beginPath();
  ctx.moveTo(topCx, topCy + size * 0.07);
  ctx.lineTo(topCx, y);
  ctx.stroke();

  return canvas;
}

interface DatacenterLayerProps {
  viewer: Cesium.Viewer | null;
  datacenters: DatacenterGeoJSON | null;
  visible: boolean;
  onSelect?: (props: DatacenterProperties) => void;
}

export function DatacenterLayer({ viewer, datacenters, visible, onSelect }: DatacenterLayerProps) {
  const billboardCollectionRef = useRef<Cesium.BillboardCollection | null>(null);
  const labelCollectionRef = useRef<Cesium.LabelCollection | null>(null);
  const idMapRef = useRef<Map<object, DatacenterProperties>>(new Map());
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
    if (!visible || !datacenters) return;

    if (!iconRef.current) {
      iconRef.current = createDatacenterIcon(32);
    }

    for (const feature of datacenters.features) {
      const [lon, lat] = feature.geometry.coordinates;
      const position = Cesium.Cartesian3.fromDegrees(lon, lat);

      const bb = bc.add({
        position,
        image: iconRef.current,
        scale: 0.8,
        eyeOffset: new Cesium.Cartesian3(0, 0, -20),
      });
      idMapRef.current.set(bb as unknown as object, {
        ...feature.properties,
        longitude: lon,
        latitude: lat,
      });

      lc.add({
        position,
        text: feature.properties.name,
        font: "11px monospace",
        fillColor: glyphColor.stone().withAlpha(0.9),
        outlineColor: Cesium.Color.BLACK,
        outlineWidth: 2,
        style: Cesium.LabelStyle.FILL_AND_OUTLINE,
        pixelOffset: new Cesium.Cartesian2(0, -22),
        distanceDisplayCondition: new Cesium.DistanceDisplayCondition(0, LABEL_ALTITUDE_THRESHOLD),
        scale: 0.9,
      });
    }
  }, [datacenters, visible, viewer]);

  return null;
}
