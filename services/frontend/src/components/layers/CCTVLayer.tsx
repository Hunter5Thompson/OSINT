import { useEffect, useRef } from "react";
import * as Cesium from "cesium";

interface CCTVLayerProps {
  viewer: Cesium.Viewer | null;
  visible: boolean;
}

/**
 * Placeholder CCTV camera marker layer (v1.1 feature).
 * Shows camera icons on the globe for known public webcam locations.
 */
export function CCTVLayer({ viewer, visible }: CCTVLayerProps) {
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

    // Placeholder webcam locations (to be replaced with Windy API data)
    const cameras = [
      { lat: 48.8566, lon: 2.3522, name: "Paris" },
      { lat: 40.7128, lon: -74.006, name: "New York" },
      { lat: 51.5074, lon: -0.1278, name: "London" },
      { lat: 35.6762, lon: 139.6503, name: "Tokyo" },
      { lat: 55.7558, lon: 37.6173, name: "Moscow" },
    ];

    for (const cam of cameras) {
      bc.add({
        position: Cesium.Cartesian3.fromDegrees(cam.lon, cam.lat, 100),
        image: createCameraCanvas(),
        scale: 0.7,
        eyeOffset: new Cesium.Cartesian3(0, 0, -50),
      });
    }
  }, [visible]);

  return null;
}

function createCameraCanvas(): HTMLCanvasElement {
  const size = 20;
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d");
  if (!ctx) return canvas;

  // Camera icon
  ctx.fillStyle = "rgba(255, 255, 255, 0.8)";
  ctx.fillRect(3, 5, 14, 10);
  ctx.beginPath();
  ctx.moveTo(17, 7);
  ctx.lineTo(20, 5);
  ctx.lineTo(20, 15);
  ctx.lineTo(17, 13);
  ctx.closePath();
  ctx.fill();

  return canvas;
}
