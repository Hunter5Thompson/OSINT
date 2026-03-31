import { useEffect, useRef } from "react";
import * as Cesium from "cesium";
import type { Vessel } from "../../types";

interface ShipLayerProps {
  viewer: Cesium.Viewer | null;
  vessels: Vessel[];
  visible: boolean;
}

/**
 * Renders AIS vessel positions using BillboardCollection.
 */
export function ShipLayer({ viewer, vessels, visible }: ShipLayerProps) {
  const collectionRef = useRef<Cesium.BillboardCollection | null>(null);

  useEffect(() => {
    if (!viewer || viewer.isDestroyed()) return;

    if (!collectionRef.current) {
      collectionRef.current = new Cesium.BillboardCollection({ scene: viewer.scene });
      viewer.scene.primitives.add(collectionRef.current);
    }

    return () => {
      if (collectionRef.current && !viewer.isDestroyed()) {
        viewer.scene.primitives.remove(collectionRef.current);
        collectionRef.current = null;
      }
    };
  }, [viewer]);

  useEffect(() => {
    const bc = collectionRef.current;
    if (!bc) return;

    bc.removeAll();
    if (!visible) return;

    for (const vessel of vessels) {
      const position = Cesium.Cartesian3.fromDegrees(vessel.longitude, vessel.latitude, 0);

      const billboard = bc.add({
        position,
        image: createShipCanvas(vessel.course),
        scale: 0.6,
        color: Cesium.Color.fromCssColorString("#4fc3f7"),
        eyeOffset: new Cesium.Cartesian3(0, 0, -50),
      });
      (billboard as unknown as Record<string, unknown>)._vesselData = {
        mmsi: vessel.mmsi,
        name: vessel.name,
        speed_knots: vessel.speed_knots,
        course: vessel.course,
        ship_type: vessel.ship_type,
        destination: vessel.destination,
        lat: vessel.latitude,
        lon: vessel.longitude,
      };
    }
  }, [vessels, visible]);

  return null;
}

function createShipCanvas(course: number): HTMLCanvasElement {
  const size = 20;
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d");
  if (!ctx) return canvas;

  ctx.translate(size / 2, size / 2);
  ctx.rotate((course * Math.PI) / 180);

  // Ship shape (diamond/arrow)
  ctx.beginPath();
  ctx.moveTo(0, -size / 2 + 2);
  ctx.lineTo(-size / 4, size / 4);
  ctx.lineTo(0, size / 6);
  ctx.lineTo(size / 4, size / 4);
  ctx.closePath();

  ctx.fillStyle = "rgba(79, 195, 247, 0.8)";
  ctx.fill();
  ctx.strokeStyle = "rgba(79, 195, 247, 1)";
  ctx.lineWidth = 1;
  ctx.stroke();

  return canvas;
}
