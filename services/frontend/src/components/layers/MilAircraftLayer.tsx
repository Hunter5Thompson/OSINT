import { useEffect, useRef } from "react";
import * as Cesium from "cesium";
import { glyphColor } from "./glyphTokens";
import { positionAtTime, type MilTrackRender } from "./milTrackAdapter";

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
      return branch ? glyphColor.amber() : Cesium.Color.WHITE;
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

interface MilAircraftLayerProps {
  viewer: Cesium.Viewer | null;
  tracks: MilTrackRender[];
  visible: boolean;
  getTimeMs: () => number;
  discontinuityEpoch: number;
  onSelect?: (t: MilTrackRender) => void;
}

export function MilAircraftLayer({
  viewer, tracks, visible, getTimeMs, discontinuityEpoch, onSelect,
}: MilAircraftLayerProps) {
  const polyCollectionRef = useRef<Cesium.PolylineCollection | null>(null);
  const billboardCollectionRef = useRef<Cesium.BillboardCollection | null>(null);
  const idMapRef = useRef<Map<object, MilTrackRender>>(new Map());
  const billboardMapRef = useRef<Map<string, { bb: Cesium.Billboard; track: MilTrackRender }>>(
    new Map(),
  );
  const handlerRef = useRef<Cesium.ScreenSpaceEventHandler | null>(null);
  const tickRemoveRef = useRef<(() => void) | null>(null);
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;

  // Init: collections + pick handler (once per viewer).
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
        if (billboardCollectionRef.current)
          viewer.scene.primitives.remove(billboardCollectionRef.current);
      }
      polyCollectionRef.current = null;
      billboardCollectionRef.current = null;
      idMapRef.current.clear();
      billboardMapRef.current.clear();
    };
  }, [viewer]);

  // Build polylines (full history) + per-track billboards (hidden until positioned).
  // Rebuilds — and resets this layer's render caches — on tracks/visibility change
  // and on every discontinuityEpoch bump (seek/rewind/mode change).
  useEffect(() => {
    const pc = polyCollectionRef.current;
    const bc = billboardCollectionRef.current;
    if (!pc || !bc) return;
    pc.removeAll();
    bc.removeAll();
    idMapRef.current.clear();
    billboardMapRef.current.clear();
    if (!visible) return;

    for (const t of tracks) {
      if (t.points.length === 0) continue;
      const last = t.points[t.points.length - 1];
      if (!last) continue;
      const color = branchColor(t.military_branch);

      if (t.points.length >= 2) {
        const arr: number[] = [];
        for (const p of t.points) arr.push(p.lon, p.lat, p.altitude_m ?? 0);
        const poly = pc.add({
          positions: Cesium.Cartesian3.fromDegreesArrayHeights(arr),
          width: 1.5,
          material: Cesium.Material.fromType("Color", { color: color.withAlpha(0.6) }),
        });
        idMapRef.current.set(poly as unknown as object, t);
      }

      // Rotation from the last known heading preserves live-mode parity (in live
      // the cursor clamps to the last point, so this renders identically to before).
      const bb = bc.add({
        position: Cesium.Cartesian3.fromDegrees(last.lon, last.lat, last.altitude_m ?? 0),
        image: createJetIcon(color, 24),
        scale: 0.8,
        rotation: Cesium.Math.toRadians(-(last.heading ?? 0) + 90),
        alignedAxis: Cesium.Cartesian3.UNIT_Z,
        eyeOffset: new Cesium.Cartesian3(0, 0, -40),
        show: false, // positioned/shown by the tick loop at the clock cursor
      });
      idMapRef.current.set(bb as unknown as object, t);
      billboardMapRef.current.set(t.icao24, { bb, track: t });
    }
  }, [tracks, visible, viewer, discontinuityEpoch]);

  // Move each billboard to the interpolated position at the clock cursor every frame.
  // Hidden before the first point; clamped at the last (no dead reckoning) — §7.3.
  useEffect(() => {
    if (!viewer || viewer.isDestroyed()) return;
    if (tickRemoveRef.current) {
      tickRemoveRef.current();
      tickRemoveRef.current = null;
    }
    const remove = viewer.clock.onTick.addEventListener(() => {
      const t = getTimeMs();
      for (const { bb, track } of billboardMapRef.current.values()) {
        const pos = positionAtTime(track.points, t);
        if (!pos) {
          bb.show = false;
          continue;
        }
        bb.show = true;
        bb.position = Cesium.Cartesian3.fromDegrees(pos.lon, pos.lat, pos.alt);
      }
    });
    tickRemoveRef.current = remove;
    return () => {
      if (tickRemoveRef.current) {
        tickRemoveRef.current();
        tickRemoveRef.current = null;
      }
    };
  }, [viewer, getTimeMs]);

  return null;
}
