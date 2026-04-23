import { useEffect, useRef, useCallback } from "react";
import * as Cesium from "cesium";
import type { SubmarineCable, LandingPoint } from "../../types";
import { densifyLonLatSegment } from "./geoPath";

interface CableLayerProps {
  viewer: Cesium.Viewer | null;
  cables: SubmarineCable[];
  landingPoints: LandingPoint[];
  visible: boolean;
}

const LABEL_ALTITUDE_THRESHOLD = 5_000_000;
// Keep cables above terrain to avoid depth fighting / terrain occlusion artifacts.
const CABLE_ALTITUDE_M = 3_000;
const LANDING_POINT_ALTITUDE_M = 3_500;

function isValidCoord(coord: number[] | undefined): coord is [number, number] {
  if (!coord || coord.length < 2) return false;
  const [lon, lat] = coord;
  return Number.isFinite(lon) && Number.isFinite(lat);
}

function getCableMidpoint(segments: number[][][]): [number, number] | null {
  let bestSegment: number[][] | null = null;
  for (const segment of segments) {
    if (segment.length < 2) continue;
    if (!bestSegment || segment.length > bestSegment.length) bestSegment = segment;
  }
  if (!bestSegment) return null;
  const mid = bestSegment[Math.floor(bestSegment.length / 2)];
  if (!isValidCoord(mid)) return null;
  return [mid[0], mid[1]];
}

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
    // Sync initial state so labels are correct before first camera move
    updateLabelVisibility();
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

    // Pre-build landing point name lookup (O(n) instead of O(n*m))
    const lpNameMap = new Map(landingPoints.map((lp) => [lp.id, lp.name]));

    // Draw cables
    const usedLabelCells = new Set<string>();
    for (const cable of cables) {
      const alpha = cable.is_planned ? 0.3 : 0.8;
      const width = cable.is_planned ? 1.5 : 2.0;
      const cableColor = hexToCesiumColor(cable.color, alpha);

      for (const segment of cable.coordinates) {
        if (segment.length < 2) continue;

        const flat: number[] = [];
        const densified = densifyLonLatSegment(segment as number[][], 80);
        for (const coord of densified) {
          if (!isValidCoord(coord)) continue;
          flat.push(coord[0], coord[1], CABLE_ALTITUDE_M);
        }
        if (flat.length < 6) continue;

        const positions = Cesium.Cartesian3.fromDegreesArrayHeights(flat);

        pc.add({
          positions,
          width,
          material: Cesium.Material.fromType("Color", { color: cableColor }),
        });
      }

      const midpoint = getCableMidpoint(cable.coordinates);
      if (midpoint) {
        const [midLon, midLat] = midpoint;
        const midPos = Cesium.Cartesian3.fromDegrees(midLon, midLat, CABLE_ALTITUDE_M);

        const billboard = bc.add({
          position: midPos,
          image: createCableDotCanvas(cable.color),
          scale: 0.4,
          eyeOffset: new Cesium.Cartesian3(0, 0, -50),
          disableDepthTestDistance: Number.POSITIVE_INFINITY,
          translucencyByDistance: new Cesium.NearFarScalar(100_000, 1.0, 10_000_000, 0.3),
        });
        // Resolve landing point names for click panel
        const lpNames = cable.landing_point_ids
          .map((lpId) => lpNameMap.get(lpId))
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

        const labelCell = `${Math.round(midLat * 2) / 2}:${Math.round(midLon * 2) / 2}`;
        if (!usedLabelCells.has(labelCell)) {
          usedLabelCells.add(labelCell);
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
            disableDepthTestDistance: Number.POSITIVE_INFINITY,
            distanceDisplayCondition: new Cesium.DistanceDisplayCondition(0, LABEL_ALTITUDE_THRESHOLD),
          });
        }
      }
    }

    // Draw landing points
    for (const lp of landingPoints) {
      bc.add({
        position: Cesium.Cartesian3.fromDegrees(lp.longitude, lp.latitude, LANDING_POINT_ALTITUDE_M),
        image: createLandingPointCanvas(),
        scale: 0.3,
        eyeOffset: new Cesium.Cartesian3(0, 0, -30),
        disableDepthTestDistance: Number.POSITIVE_INFINITY,
        translucencyByDistance: new Cesium.NearFarScalar(100_000, 1.0, 8_000_000, 0.2),
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
