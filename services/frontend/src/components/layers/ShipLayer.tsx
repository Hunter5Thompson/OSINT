import { useEffect, useRef, useCallback } from "react";
import * as Cesium from "cesium";
import type { Vessel } from "../../types";
import { classifyShip, getShipTypeIcon, ICON_COLORS } from "./icons/shipIcons";
import { usePerformance } from "../globe/PerformanceGuard";

interface ShipLayerProps {
  viewer: Cesium.Viewer | null;
  vessels: Vessel[];
  visible: boolean;
}

const COURSE_VECTOR_MINUTES = 5;
const KNOTS_TO_MS = 0.514444;
const EARTH_RADIUS_M = 6_378_137;
const LOD_ALTITUDE_THRESHOLD = 5_000_000;

/**
 * Renders AIS vessel positions with type-specific icons and course vectors.
 */
export function ShipLayer({ viewer, vessels, visible }: ShipLayerProps) {
  const collectionRef = useRef<Cesium.BillboardCollection | null>(null);
  const vectorCollectionRef = useRef<Cesium.PolylineCollection | null>(null);
  const { degradation } = usePerformance();

  useEffect(() => {
    if (!viewer || viewer.isDestroyed()) return;

    if (!collectionRef.current) {
      collectionRef.current = new Cesium.BillboardCollection({ scene: viewer.scene });
      viewer.scene.primitives.add(collectionRef.current);
    }
    if (!vectorCollectionRef.current) {
      vectorCollectionRef.current = new Cesium.PolylineCollection();
      viewer.scene.primitives.add(vectorCollectionRef.current);
    }

    return () => {
      if (!viewer.isDestroyed()) {
        if (collectionRef.current) viewer.scene.primitives.remove(collectionRef.current);
        if (vectorCollectionRef.current) viewer.scene.primitives.remove(vectorCollectionRef.current);
      }
      collectionRef.current = null;
      vectorCollectionRef.current = null;
    };
  }, [viewer]);

  // Render billboards (always) + course vectors (LOD-gated)
  const renderVessels = useCallback((showVectors: boolean) => {
    const bc = collectionRef.current;
    const vc = vectorCollectionRef.current;
    if (!bc || !vc) return;

    bc.removeAll();
    vc.removeAll();
    if (!visible) return;

    for (const vessel of vessels) {
      const position = Cesium.Cartesian3.fromDegrees(vessel.longitude, vessel.latitude, 0);
      const shipType = classifyShip(vessel.ship_type, vessel.name);

      const billboard = bc.add({
        position,
        image: getShipTypeIcon(shipType, vessel.course),
        scale: 0.6,
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

      // Course vector: line in heading direction, length proportional to speed
      if (showVectors && vessel.speed_knots > 0.5) {
        const speedMs = vessel.speed_knots * KNOTS_TO_MS;
        const distanceM = speedMs * COURSE_VECTOR_MINUTES * 60;
        const headingRad = Cesium.Math.toRadians(vessel.course);
        const latRad = Cesium.Math.toRadians(vessel.latitude);
        const lonRad = Cesium.Math.toRadians(vessel.longitude);

        const angDist = distanceM / EARTH_RADIUS_M;
        const endLat = Math.asin(
          Math.sin(latRad) * Math.cos(angDist) +
          Math.cos(latRad) * Math.sin(angDist) * Math.cos(headingRad),
        );
        const endLon = lonRad + Math.atan2(
          Math.sin(headingRad) * Math.sin(angDist) * Math.cos(latRad),
          Math.cos(angDist) - Math.sin(latRad) * Math.sin(endLat),
        );

        const endPosition = Cesium.Cartesian3.fromDegrees(
          Cesium.Math.toDegrees(endLon),
          Cesium.Math.toDegrees(endLat),
          0,
        );

        const vectorColor = Cesium.Color.fromCssColorString(
          ICON_COLORS[shipType] ?? ICON_COLORS.civilian
        ).withAlpha(0.4);

        vc.add({
          positions: [position, endPosition],
          width: 1.0,
          material: Cesium.Material.fromType("Color", { color: vectorColor }),
        });
      }
    }
  }, [vessels, visible]);

  // Re-render on data change
  useEffect(() => {
    if (!viewer || viewer.isDestroyed()) return;
    const cameraAlt = viewer.camera.positionCartographic.height;
    renderVessels(degradation < 3 && cameraAlt < LOD_ALTITUDE_THRESHOLD);
  }, [vessels, visible, viewer, degradation, renderVessels]);

  // Re-render vectors on camera move (LOD reactivity)
  const lastShowVectorsRef = useRef(false);

  useEffect(() => {
    if (!viewer || viewer.isDestroyed()) return;

    const onMoveEnd = () => {
      if (!viewer || viewer.isDestroyed()) return;
      const cameraAlt = viewer.camera.positionCartographic.height;
      const shouldShow = degradation < 3 && cameraAlt < LOD_ALTITUDE_THRESHOLD;

      // Only re-render if LOD state changed (avoids redundant work)
      if (shouldShow !== lastShowVectorsRef.current) {
        lastShowVectorsRef.current = shouldShow;
        renderVessels(shouldShow);
      }
    };

    viewer.camera.moveEnd.addEventListener(onMoveEnd);
    return () => {
      if (!viewer.isDestroyed()) viewer.camera.moveEnd.removeEventListener(onMoveEnd);
    };
  }, [viewer, degradation, renderVessels]);

  return null;
}
