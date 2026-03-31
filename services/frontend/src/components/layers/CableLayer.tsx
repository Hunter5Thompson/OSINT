import { useEffect, useRef, useCallback } from "react";
import * as Cesium from "cesium";
import type { SubmarineCable, LandingPoint } from "../../types";

interface CableLayerProps {
  viewer: Cesium.Viewer | null;
  cables: SubmarineCable[];
  landingPoints: LandingPoint[];
  visible: boolean;
}

const LABEL_ALTITUDE_THRESHOLD = 5_000_000;

export function CableLayer({ viewer, cables, landingPoints, visible }: CableLayerProps) {
  const polylineCollectionRef = useRef<Cesium.PolylineCollection | null>(null);
  const billboardCollectionRef = useRef<Cesium.BillboardCollection | null>(null);
  const labelCollectionRef = useRef<Cesium.LabelCollection | null>(null);
  const labelsVisibleRef = useRef(false);

  // Setup/teardown collections
  useEffect(() => {
    if (!viewer || viewer.isDestroyed()) return;

    if (!polylineCollectionRef.current) {
      polylineCollectionRef.current = new Cesium.PolylineCollection();
      viewer.scene.primitives.add(polylineCollectionRef.current);
    }
    if (!billboardCollectionRef.current) {
      billboardCollectionRef.current = new Cesium.BillboardCollection({ scene: viewer.scene });
      viewer.scene.primitives.add(billboardCollectionRef.current);
    }
    if (!labelCollectionRef.current) {
      labelCollectionRef.current = new Cesium.LabelCollection({ scene: viewer.scene });
      viewer.scene.primitives.add(labelCollectionRef.current);
    }

    return () => {
      if (polylineCollectionRef.current && !viewer.isDestroyed()) {
        viewer.scene.primitives.remove(polylineCollectionRef.current);
        polylineCollectionRef.current = null;
      }
      if (billboardCollectionRef.current && !viewer.isDestroyed()) {
        viewer.scene.primitives.remove(billboardCollectionRef.current);
        billboardCollectionRef.current = null;
      }
      if (labelCollectionRef.current && !viewer.isDestroyed()) {
        viewer.scene.primitives.remove(labelCollectionRef.current);
        labelCollectionRef.current = null;
      }
    };
  }, [viewer]);

  // Camera-based label visibility (moveEnd, not per-frame)
  const updateLabelVisibility = useCallback(() => {
    const lc = labelCollectionRef.current;
    if (!lc || !viewer || viewer.isDestroyed()) return;

    const carto = viewer.camera.positionCartographic;
    const shouldShow = carto.height < LABEL_ALTITUDE_THRESHOLD;

    if (shouldShow !== labelsVisibleRef.current) {
      labelsVisibleRef.current = shouldShow;
      lc.show = shouldShow && visible;
    }
  }, [viewer, visible]);

  useEffect(() => {
    if (!viewer || viewer.isDestroyed()) return;
    const removeListener = viewer.camera.moveEnd.addEventListener(updateLabelVisibility);
    return () => removeListener();
  }, [viewer, updateLabelVisibility]);

  // Render cables + landing points
  useEffect(() => {
    const pc = polylineCollectionRef.current;
    const bc = billboardCollectionRef.current;
    const lc = labelCollectionRef.current;
    if (!pc || !bc || !lc) return;

    pc.removeAll();
    bc.removeAll();
    lc.removeAll();

    pc.show = visible;
    bc.show = visible;
    // Label visibility managed by camera listener
    lc.show = visible && labelsVisibleRef.current;

    if (!visible) return;

    // Draw cables
    for (const cable of cables) {
      const alpha = cable.is_planned ? 0.3 : 0.8;
      const width = cable.is_planned ? 1.5 : 2.0;
      const cableColor = hexToCesiumColor(cable.color, alpha);

      for (const segment of cable.coordinates) {
        if (segment.length < 2) continue;

        const positions = segment.map(([lon, lat]) =>
          Cesium.Cartesian3.fromDegrees(lon, lat, 0),
        );

        pc.add({
          positions,
          width,
          material: Cesium.Material.fromType("Color", { color: cableColor }),
        });
      }

      // Midpoint billboard for click handling (first segment)
      const firstSeg = cable.coordinates[0];
      if (firstSeg && firstSeg.length >= 2) {
        const midIdx = Math.floor(firstSeg.length / 2);
        const [midLon, midLat] = firstSeg[midIdx];
        const midPos = Cesium.Cartesian3.fromDegrees(midLon, midLat, 0);

        const billboard = bc.add({
          position: midPos,
          image: createCableDotCanvas(cable.color),
          scale: 0.4,
          eyeOffset: new Cesium.Cartesian3(0, 0, -50),
        });
        // Resolve landing point names for click panel
        const lpNames = cable.landing_point_ids
          .map((lpId) => landingPoints.find((lp) => lp.id === lpId)?.name)
          .filter((n): n is string => n != null);

        (billboard as unknown as Record<string, unknown>)._cableData = {
          id: cable.id,
          name: cable.name,
          owners: cable.owners,
          capacity_tbps: cable.capacity_tbps,
          length_km: cable.length_km,
          rfs: cable.rfs,
          is_planned: cable.is_planned,
          url: cable.url,
          landing_points: lpNames,
          lat: midLat,
          lon: midLon,
        };

        // Label at midpoint
        lc.add({
          position: midPos,
          text: cable.name.length > 25 ? cable.name.substring(0, 22) + "..." : cable.name,
          font: "10px monospace",
          fillColor: cableColor,
          outlineColor: Cesium.Color.BLACK,
          outlineWidth: 2,
          style: Cesium.LabelStyle.FILL_AND_OUTLINE,
          pixelOffset: new Cesium.Cartesian2(0, -12),
          eyeOffset: new Cesium.Cartesian3(0, 0, -50),
        });
      }
    }

    // Draw landing points
    for (const lp of landingPoints) {
      bc.add({
        position: Cesium.Cartesian3.fromDegrees(lp.longitude, lp.latitude, 0),
        image: createLandingPointCanvas(),
        scale: 0.3,
        eyeOffset: new Cesium.Cartesian3(0, 0, -30),
      });
    }
  }, [cables, landingPoints, visible]);

  return null;
}

function hexToCesiumColor(hex: string, alpha: number): Cesium.Color {
  try {
    const c = Cesium.Color.fromCssColorString(hex);
    return c.withAlpha(alpha);
  } catch {
    return Cesium.Color.CYAN.withAlpha(alpha);
  }
}

const cableDotCache = new Map<string, string>();

function createCableDotCanvas(color: string): string {
  const cached = cableDotCache.get(color);
  if (cached) return cached;

  const size = 12;
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d");
  if (ctx) {
    ctx.beginPath();
    ctx.arc(size / 2, size / 2, size / 2 - 1, 0, Math.PI * 2);
    ctx.fillStyle = color;
    ctx.fill();
  }
  const dataUrl = canvas.toDataURL();
  cableDotCache.set(color, dataUrl);
  return dataUrl;
}

let landingPointDataUrl: string | null = null;

function createLandingPointCanvas(): string {
  if (landingPointDataUrl) return landingPointDataUrl;

  const size = 10;
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d");
  if (ctx) {
    ctx.beginPath();
    ctx.arc(size / 2, size / 2, size / 2 - 1, 0, Math.PI * 2);
    ctx.fillStyle = "#ffd600";
    ctx.fill();
  }
  landingPointDataUrl = canvas.toDataURL();
  return landingPointDataUrl;
}
