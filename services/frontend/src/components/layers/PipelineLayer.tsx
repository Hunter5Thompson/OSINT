import { useEffect, useRef, useCallback } from "react";
import * as Cesium from "cesium";
import type { PipelineGeoJSON, PipelineFeature } from "../../types";
import { PIPELINE_COLORS, PIPELINE_LOD_THRESHOLDS } from "../../types/pipeline";

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

function getCoordinatesFlat(feature: PipelineFeature): number[][] {
  if (feature.geometry.type === "LineString") {
    return feature.geometry.coordinates as number[][];
  }
  return (feature.geometry.coordinates as number[][][])[0] ?? [];
}

export function PipelineLayer({ viewer, pipelines, visible }: PipelineLayerProps) {
  const polylineCollectionRef = useRef<Cesium.PolylineCollection | null>(null);
  const billboardCollectionRef = useRef<Cesium.BillboardCollection | null>(null);
  const labelCollectionRef = useRef<Cesium.LabelCollection | null>(null);
  const currentTiersRef = useRef<Set<string>>(new Set<string>());
  const labelsVisibleRef = useRef(false);

  const LABEL_ALTITUDE_THRESHOLD = 5_000_000;

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

        const coords = getCoordinatesFlat(feature);
        if (coords.length < 2) continue;

        const positions = Cesium.Cartesian3.fromDegreesArray(
          coords.flatMap(([lon, lat]) => [lon, lat]),
        );

        const color = Cesium.Color.fromCssColorString(
          PIPELINE_COLORS[props.type] ?? PIPELINE_COLORS.mixed,
        );

        const isDashed = props.status !== "active";
        const width = props.status === "active" ? 2.0 : 1.5;

        pc.add({
          positions,
          width,
          material: isDashed
            ? Cesium.Material.fromType("PolylineDash", { color, dashLength: 16.0 })
            : Cesium.Material.fromType("Color", { color }),
        });

        const midIdx = Math.floor(coords.length / 2);
        const midCoord = coords[midIdx];
        const bb = bc.add({
          position: Cesium.Cartesian3.fromDegrees(midCoord[0], midCoord[1]),
          image: createPipelineDot(PIPELINE_COLORS[props.type] ?? PIPELINE_COLORS.mixed),
          scale: 1.0,
          translucencyByDistance: new Cesium.NearFarScalar(1e5, 1.0, 1e7, 0.3),
        }) as PipelineBillboard;

        bb._pipelineData = {
          name: props.name,
          type: props.type,
          status: props.status,
          operator: props.operator,
          capacity_bcm: props.capacity_bcm,
          length_km: props.length_km,
          countries: props.countries,
          lat: midCoord[1],
          lon: midCoord[0],
        };

        lc.add({
          position: Cesium.Cartesian3.fromDegrees(midCoord[0], midCoord[1]),
          text: props.name,
          font: "11px monospace",
          fillColor: color.withAlpha(0.8),
          outlineColor: Cesium.Color.BLACK,
          outlineWidth: 2,
          style: Cesium.LabelStyle.FILL_AND_OUTLINE,
          pixelOffset: new Cesium.Cartesian2(0, -12),
          show: labelsVisibleRef.current,
          disableDepthTestDistance: Number.POSITIVE_INFINITY,
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
          for (let i = 0; i < lc.length; i++) {
            lc.get(i).show = shouldShowLabels;
          }
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
  }, [viewer, pipelines, renderPipelines]);

  useEffect(() => {
    if (polylineCollectionRef.current) polylineCollectionRef.current.show = visible;
    if (billboardCollectionRef.current) billboardCollectionRef.current.show = visible;
    if (labelCollectionRef.current) labelCollectionRef.current.show = visible;
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
