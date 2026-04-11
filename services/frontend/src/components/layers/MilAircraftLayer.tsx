import { useEffect, useRef } from "react";
import * as Cesium from "cesium";
import type { AircraftPoint, AircraftTrack } from "../../types";

export function branchColor(branch: string | null): Cesium.Color {
  switch ((branch || "").toUpperCase()) {
    case "USAF":
      return Cesium.Color.fromCssColorString("#66e6ff");
    case "USN":
    case "USMC":
      return Cesium.Color.fromCssColorString("#4d9fff");
    case "RUAF":
    case "VKS":
      return Cesium.Color.fromCssColorString("#ff5050");
    default:
      return branch ? Cesium.Color.fromCssColorString("#ffaa33") : Cesium.Color.WHITE;
  }
}

export function createJetIcon(color: Cesium.Color, size = 24): HTMLCanvasElement {
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d");
  if (!ctx) return canvas;
  const cx = size / 2;
  ctx.translate(cx, cx);
  ctx.fillStyle = `rgba(${color.red * 255}, ${color.green * 255}, ${color.blue * 255}, 0.95)`;
  ctx.strokeStyle = "rgba(0,0,0,0.8)";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(0, -size * 0.45);
  ctx.lineTo(size * 0.1, size * 0.1);
  ctx.lineTo(size * 0.45, size * 0.2);
  ctx.lineTo(size * 0.1, size * 0.25);
  ctx.lineTo(size * 0.08, size * 0.4);
  ctx.lineTo(-size * 0.08, size * 0.4);
  ctx.lineTo(-size * 0.1, size * 0.25);
  ctx.lineTo(-size * 0.45, size * 0.2);
  ctx.lineTo(-size * 0.1, size * 0.1);
  ctx.closePath();
  ctx.fill();
  ctx.stroke();
  return canvas;
}

export function trackToPolylinePositions(points: AircraftPoint[]): Cesium.Cartesian3[] {
  const arr: number[] = [];
  for (const p of points) {
    arr.push(p.lon, p.lat, p.altitude_m ?? 0);
  }
  return Cesium.Cartesian3.fromDegreesArrayHeights(arr);
}

interface MilAircraftLayerProps {
  viewer: Cesium.Viewer | null;
  tracks: AircraftTrack[];
  visible: boolean;
  onSelect?: (t: AircraftTrack) => void;
}

export function MilAircraftLayer({ viewer, tracks, visible, onSelect }: MilAircraftLayerProps) {
  const polyCollectionRef = useRef<Cesium.PolylineCollection | null>(null);
  const billboardCollectionRef = useRef<Cesium.BillboardCollection | null>(null);
  const idMapRef = useRef<Map<object, AircraftTrack>>(new Map());
  const handlerRef = useRef<Cesium.ScreenSpaceEventHandler | null>(null);
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;

  useEffect(() => {
    if (!viewer || viewer.isDestroyed()) return;
    if (!polyCollectionRef.current) {
      polyCollectionRef.current = new Cesium.PolylineCollection();
      viewer.scene.primitives.add(polyCollectionRef.current);
    }
    if (!billboardCollectionRef.current) {
      billboardCollectionRef.current = new Cesium.BillboardCollection({ scene: viewer.scene });
      viewer.scene.primitives.add(billboardCollectionRef.current);
    }
    if (!handlerRef.current) {
      const h = new Cesium.ScreenSpaceEventHandler(viewer.canvas);
      h.setInputAction((movement: Cesium.ScreenSpaceEventHandler.PositionedEvent) => {
        const picked = viewer.scene.pick(movement.position);
        if (!picked) return;
        const track = idMapRef.current.get(picked.primitive as unknown as object);
        if (track && onSelectRef.current) onSelectRef.current(track);
      }, Cesium.ScreenSpaceEventType.LEFT_CLICK);
      handlerRef.current = h;
    }
    return () => {
      if (handlerRef.current) {
        handlerRef.current.destroy();
        handlerRef.current = null;
      }
      if (!viewer.isDestroyed()) {
        if (polyCollectionRef.current) viewer.scene.primitives.remove(polyCollectionRef.current);
        if (billboardCollectionRef.current) viewer.scene.primitives.remove(billboardCollectionRef.current);
      }
      polyCollectionRef.current = null;
      billboardCollectionRef.current = null;
      idMapRef.current.clear();
    };
  }, [viewer]);

  useEffect(() => {
    const pc = polyCollectionRef.current;
    const bc = billboardCollectionRef.current;
    if (!pc || !bc) return;
    pc.removeAll();
    bc.removeAll();
    idMapRef.current.clear();
    if (!visible) return;

    for (const t of tracks) {
      if (t.points.length === 0) continue;
      const color = branchColor(t.military_branch);

      if (t.points.length >= 2) {
        const positions = trackToPolylinePositions(t.points);
        const poly = pc.add({
          positions,
          width: 1.5,
          material: Cesium.Material.fromType("Color", { color: color.withAlpha(0.6) }),
        });
        idMapRef.current.set(poly as unknown as object, t);
      }

      const last = t.points[t.points.length - 1];
      const position = Cesium.Cartesian3.fromDegrees(last.lon, last.lat, last.altitude_m ?? 0);
      const rotationRad = Cesium.Math.toRadians(-(last.heading ?? 0) + 90);
      const bb = bc.add({
        position,
        image: createJetIcon(color, 24),
        scale: 0.8,
        rotation: rotationRad,
        alignedAxis: Cesium.Cartesian3.UNIT_Z,
        eyeOffset: new Cesium.Cartesian3(0, 0, -40),
      });
      idMapRef.current.set(bb as unknown as object, t);
    }
  }, [tracks, visible]);

  return null;
}
