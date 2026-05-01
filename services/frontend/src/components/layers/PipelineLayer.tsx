import { useEffect, useRef, useCallback } from "react";
import * as Cesium from "cesium";
import type { PipelineGeoJSON, PipelineFeature } from "../../types";
import { PIPELINE_COLORS, PIPELINE_LOD_THRESHOLDS } from "../../types/pipeline";
import { densifyLonLatSegment } from "./geoPath";
import { glyphColor } from "./glyphTokens";

interface PipelineLayerProps {
  viewer: Cesium.Viewer | null;
  pipelines: PipelineGeoJSON | null;
  visible: boolean;
}

interface PipelineBillboard extends Cesium.Billboard {
  _pipelineData?: {
    name: string;
    type: string;
    status: string;
    operator: string | null;
    capacity_bcm: number | null;
    length_km: number | null;
    countries: string[];
    lat: number;
    lon: number;
  };
}

// Pipelines run across elevated terrain; render above surface to avoid clipping.
const PIPELINE_ALTITUDE_M = 5_000;
const LABEL_ALTITUDE_THRESHOLD = 3_000_000;

function getVisibleTier(altitudeMeters: number): Set<string> {
  const tiers = new Set<string>();
  for (const [tier, threshold] of Object.entries(PIPELINE_LOD_THRESHOLDS)) {
    if (altitudeMeters < threshold) {
      tiers.add(tier);
    }
  }
  tiers.add("major");
  return tiers;
}

function getCoordinateSegments(feature: PipelineFeature): number[][][] {
  if (feature.geometry.type === "LineString") {
    return [feature.geometry.coordinates as number[][]];
  }
  return feature.geometry.coordinates as number[][][];
}

function isValidCoord(coord: number[] | undefined): coord is [number, number] {
  if (!coord || coord.length < 2) return false;
  const [lon, lat] = coord;
  return Number.isFinite(lon) && Number.isFinite(lat);
}

function getPipelineMidpoint(segments: number[][][]): [number, number] | null {
  let bestSegment: number[][] | null = null;
  for (const segment of segments) {
    if (segment.length < 2) continue;
    if (!bestSegment || segment.length > bestSegment.length) {
      bestSegment = segment;
    }
  }
  if (!bestSegment) return null;
  const mid = bestSegment[Math.floor(bestSegment.length / 2)];
  if (!isValidCoord(mid)) return null;
  return [mid[0], mid[1]];
}

export function PipelineLayer({ viewer, pipelines, visible }: PipelineLayerProps) {
  const polylineCollectionRef = useRef<Cesium.PolylineCollection | null>(null);
  const billboardCollectionRef = useRef<Cesium.BillboardCollection | null>(null);
  const labelCollectionRef = useRef<Cesium.LabelCollection | null>(null);
  const currentTiersRef = useRef<Set<string>>(new Set<string>());
  const labelsVisibleRef = useRef(false);

  useEffect(() => {
    if (!viewer || viewer.isDestroyed()) return;

    polylineCollectionRef.current = new Cesium.PolylineCollection();
    billboardCollectionRef.current = new Cesium.BillboardCollection({ scene: viewer.scene });
    labelCollectionRef.current = new Cesium.LabelCollection({ scene: viewer.scene });

    viewer.scene.primitives.add(polylineCollectionRef.current);
    viewer.scene.primitives.add(billboardCollectionRef.current);
    viewer.scene.primitives.add(labelCollectionRef.current);

    return () => {
      if (!viewer.isDestroyed()) {
        if (polylineCollectionRef.current) viewer.scene.primitives.remove(polylineCollectionRef.current);
        if (billboardCollectionRef.current) viewer.scene.primitives.remove(billboardCollectionRef.current);
        if (labelCollectionRef.current) viewer.scene.primitives.remove(labelCollectionRef.current);
      }
      polylineCollectionRef.current = null;
      billboardCollectionRef.current = null;
      labelCollectionRef.current = null;
    };
  }, [viewer]);

  const renderPipelines = useCallback(
    (tiers: Set<string>) => {
      const pc = polylineCollectionRef.current;
      const bc = billboardCollectionRef.current;
      const lc = labelCollectionRef.current;
      if (!pc || !bc || !lc || !pipelines) return;

      pc.removeAll();
      bc.removeAll();
      lc.removeAll();

      for (const feature of pipelines.features) {
        const props = feature.properties;
        if (!tiers.has(props.tier)) continue;

        const segments = getCoordinateSegments(feature);
        const isDashed = props.status !== "active";
        const colorHex = PIPELINE_COLORS[props.type];
        const color = colorHex
          ? Cesium.Color.fromCssColorString(colorHex)
          : (isDashed ? glyphColor.sentinel() : glyphColor.stone());
        const width = props.status === "active" ? 2.0 : 1.5;

        let renderedSegments = 0;
        for (const segment of segments) {
          if (segment.length < 2) continue;
          const flat: number[] = [];
          const densified = densifyLonLatSegment(segment, 80);
          for (const coord of densified) {
            if (!isValidCoord(coord)) continue;
            flat.push(coord[0], coord[1], PIPELINE_ALTITUDE_M);
          }
          if (flat.length < 6) continue;

          const positions = Cesium.Cartesian3.fromDegreesArrayHeights(flat);
          pc.add({
            positions,
            width,
            material: isDashed
              ? Cesium.Material.fromType("PolylineDash", { color, dashLength: 16.0 })
              : Cesium.Material.fromType("Color", { color }),
          });
          renderedSegments += 1;
        }
        if (renderedSegments === 0) continue;

        const midpoint = getPipelineMidpoint(segments);
        if (!midpoint) continue;
        const [midLon, midLat] = midpoint;

        const bb = bc.add({
          position: Cesium.Cartesian3.fromDegrees(midLon, midLat, PIPELINE_ALTITUDE_M),
          image: createPipelineDot(PIPELINE_COLORS[props.type] ?? PIPELINE_COLORS.mixed),
          scale: 1.0,
          translucencyByDistance: new Cesium.NearFarScalar(1e5, 1.0, 1e7, 0.3),
          disableDepthTestDistance: Number.POSITIVE_INFINITY,
        }) as PipelineBillboard;

        bb._pipelineData = {
          name: props.name,
          type: props.type,
          status: props.status,
          operator: props.operator,
          capacity_bcm: props.capacity_bcm,
          length_km: props.length_km,
          countries: props.countries,
          lat: midLat,
          lon: midLon,
        };

        lc.add({
          position: Cesium.Cartesian3.fromDegrees(midLon, midLat, PIPELINE_ALTITUDE_M),
          text: props.name,
          font: "11px monospace",
          fillColor: color.withAlpha(0.8),
          outlineColor: Cesium.Color.BLACK,
          outlineWidth: 2,
          style: Cesium.LabelStyle.FILL_AND_OUTLINE,
          pixelOffset: new Cesium.Cartesian2(0, -12),
          show: labelsVisibleRef.current,
          disableDepthTestDistance: Number.POSITIVE_INFINITY,
          distanceDisplayCondition: new Cesium.DistanceDisplayCondition(0, LABEL_ALTITUDE_THRESHOLD),
        });
      }
    },
    [pipelines],
  );

  useEffect(() => {
    if (!viewer || viewer.isDestroyed() || !pipelines) return;

    const updateLOD = () => {
      if (!viewer || viewer.isDestroyed()) return;

      const altitude = viewer.camera.positionCartographic.height;
      const newTiers = getVisibleTier(altitude);

      const tiersChanged =
        newTiers.size !== currentTiersRef.current.size ||
        [...newTiers].some((t) => !currentTiersRef.current.has(t));

      if (tiersChanged) {
        currentTiersRef.current = newTiers;
        renderPipelines(newTiers);
      }

      const shouldShowLabels = altitude < LABEL_ALTITUDE_THRESHOLD;
      if (shouldShowLabels !== labelsVisibleRef.current) {
        labelsVisibleRef.current = shouldShowLabels;
        const lc = labelCollectionRef.current;
        if (lc) {
          lc.show = shouldShowLabels && visible;
        }
      }
    };

    viewer.camera.moveEnd.addEventListener(updateLOD);
    updateLOD();

    return () => {
      if (!viewer.isDestroyed()) {
        viewer.camera.moveEnd.removeEventListener(updateLOD);
      }
    };
  }, [viewer, pipelines, renderPipelines, visible]);

  useEffect(() => {
    if (polylineCollectionRef.current) polylineCollectionRef.current.show = visible;
    if (billboardCollectionRef.current) billboardCollectionRef.current.show = visible;
    if (labelCollectionRef.current) labelCollectionRef.current.show = visible && labelsVisibleRef.current;
  }, [visible]);

  return null;
}

function createPipelineDot(color: string): string {
  const size = 12;
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d")!;
  ctx.beginPath();
  ctx.arc(size / 2, size / 2, size / 2 - 1, 0, Math.PI * 2);
  ctx.fillStyle = color;
  ctx.globalAlpha = 0.7;
  ctx.fill();
  return canvas.toDataURL();
}
