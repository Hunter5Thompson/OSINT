import { useEffect, useRef } from "react";
import * as Cesium from "cesium";
import type { ReconScene } from "../../lib/recon/types";

const PIN_RADIUS = 14;
const PIN_COLOR = new Cesium.Color(0.92, 0.65, 0.20, 1.0); // amber per Hlidskjalf

function createReconPin(): HTMLCanvasElement {
  const size = PIN_RADIUS * 4;
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d");
  if (!ctx) return canvas;
  const c = size / 2;
  // Outer ring
  ctx.strokeStyle = `rgba(235, 165, 50, 0.9)`;
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.arc(c, c, PIN_RADIUS, 0, Math.PI * 2);
  ctx.stroke();
  // Inner dot
  ctx.fillStyle = `rgba(235, 165, 50, 1.0)`;
  ctx.beginPath();
  ctx.arc(c, c, PIN_RADIUS * 0.45, 0, Math.PI * 2);
  ctx.fill();
  return canvas;
}

interface ReconLayerProps {
  viewer: Cesium.Viewer | null;
  scenes: ReconScene[];
  visible: boolean;
  onSelect?: (scene: ReconScene) => void;
}

export function ReconLayer({ viewer, scenes, visible, onSelect }: ReconLayerProps) {
  const collectionRef = useRef<Cesium.BillboardCollection | null>(null);
  const idMapRef = useRef<Map<object, ReconScene>>(new Map());
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
        if (viewer.isDestroyed()) return;
        const picked = viewer.scene.pick(movement.position);
        if (!picked) return;
        const scene = idMapRef.current.get(picked.primitive as unknown as object);
        if (scene && onSelectRef.current) onSelectRef.current(scene);
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

  useEffect(() => {
    const bc = collectionRef.current;
    if (!bc) return;
    bc.removeAll();
    idMapRef.current.clear();
    if (!visible) return;

    const pinImage = createReconPin();
    for (const scene of scenes) {
      const position = Cesium.Cartesian3.fromDegrees(
        scene.bounds.center_lon,
        scene.bounds.center_lat,
        0
      );
      const billboard = bc.add({
        position,
        image: pinImage,
        color: PIN_COLOR,
        scaleByDistance: new Cesium.NearFarScalar(1e3, 1.5, 8e6, 0.5),
      });
      idMapRef.current.set(billboard as unknown as object, scene);
    }
  }, [scenes, visible]);

  return null;
}
