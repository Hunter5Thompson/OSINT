import { useEffect, useRef } from "react";
import * as Cesium from "cesium";
import type { Earthquake } from "../../types";

interface EarthquakeLayerProps {
  viewer: Cesium.Viewer | null;
  earthquakes: Earthquake[];
  visible: boolean;
}

function magnitudeToColor(mag: number): Cesium.Color {
  if (mag >= 7.0) return Cesium.Color.RED;
  if (mag >= 6.0) return Cesium.Color.ORANGE;
  if (mag >= 5.0) return Cesium.Color.YELLOW;
  return Cesium.Color.LIME;
}

function magnitudeToSize(mag: number): number {
  return Math.max(6, Math.pow(2, mag - 3));
}

/**
 * Renders earthquakes as pulsing markers with magnitude-proportional size.
 */
export function EarthquakeLayer({ viewer, earthquakes, visible }: EarthquakeLayerProps) {
  const collectionRef = useRef<Cesium.BillboardCollection | null>(null);
  const labelCollectionRef = useRef<Cesium.LabelCollection | null>(null);

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
      if (collectionRef.current && !viewer.isDestroyed()) {
        viewer.scene.primitives.remove(collectionRef.current);
        collectionRef.current = null;
      }
      if (labelCollectionRef.current && !viewer.isDestroyed()) {
        viewer.scene.primitives.remove(labelCollectionRef.current);
        labelCollectionRef.current = null;
      }
    };
  }, [viewer]);

  useEffect(() => {
    const bc = collectionRef.current;
    const lc = labelCollectionRef.current;
    if (!bc || !lc) return;

    bc.removeAll();
    lc.removeAll();

    if (!visible) return;

    for (const quake of earthquakes) {
      const position = Cesium.Cartesian3.fromDegrees(quake.longitude, quake.latitude, 0);
      const color = magnitudeToColor(quake.magnitude);
      const size = magnitudeToSize(quake.magnitude);

      bc.add({
        position,
        image: createQuakeCanvas(size, color),
        scale: 1.0,
        eyeOffset: new Cesium.Cartesian3(0, 0, -50),
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
    }
  }, [earthquakes, visible]);

  return null;
}

function createQuakeCanvas(size: number, color: Cesium.Color): HTMLCanvasElement {
  const canvasSize = Math.ceil(size * 4);
  const canvas = document.createElement("canvas");
  canvas.width = canvasSize;
  canvas.height = canvasSize;
  const ctx = canvas.getContext("2d");
  if (!ctx) return canvas;

  const center = canvasSize / 2;
  const r = size;

  // Outer ring
  ctx.beginPath();
  ctx.arc(center, center, r, 0, Math.PI * 2);
  ctx.strokeStyle = `rgba(${color.red * 255}, ${color.green * 255}, ${color.blue * 255}, 0.8)`;
  ctx.lineWidth = 2;
  ctx.stroke();

  // Inner filled circle
  ctx.beginPath();
  ctx.arc(center, center, r * 0.4, 0, Math.PI * 2);
  ctx.fillStyle = `rgba(${color.red * 255}, ${color.green * 255}, ${color.blue * 255}, 0.9)`;
  ctx.fill();

  return canvas;
}
