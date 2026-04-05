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
const VECTOR_ALT_THRESHOLD = 3_000_000;
const MAX_RENDERED_VESSELS = 3000;
const MAX_COURSE_VECTORS = 200;

/**
 * Renders AIS vessel positions with type-specific icons and course vectors.
 * Only vessels in the current camera viewport are rendered (frustum culling).
 */
export function ShipLayer({ viewer, vessels, visible }: ShipLayerProps) {
  const collectionRef = useRef<Cesium.BillboardCollection | null>(null);
  const vectorCollectionRef = useRef<Cesium.PolylineCollection | null>(null);
  const { degradation } = usePerformance();
  const vesselsRef = useRef(vessels);
  vesselsRef.current = vessels;
  const visibleRef = useRef(visible);
  visibleRef.current = visible;
  const degradationRef = useRef(degradation);
  degradationRef.current = degradation;

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

  const renderVisible = useCallback(() => {
    const bc = collectionRef.current;
    const vc = vectorCollectionRef.current;
    if (!bc || !vc || !viewer || viewer.isDestroyed()) return;

    bc.removeAll();
    vc.removeAll();
    if (!visibleRef.current) return;

    const cameraAlt = viewer.camera.positionCartographic.height;
    const showVectors = degradationRef.current < 3 && cameraAlt < VECTOR_ALT_THRESHOLD;

    // Get viewport bounds for frustum culling
    const viewRect = viewer.camera.computeViewRectangle(viewer.scene.globe.ellipsoid);
    const south = viewRect ? Cesium.Math.toDegrees(viewRect.south) : -90;
    const north = viewRect ? Cesium.Math.toDegrees(viewRect.north) : 90;
    const west = viewRect ? Cesium.Math.toDegrees(viewRect.west) : -180;
    const east = viewRect ? Cesium.Math.toDegrees(viewRect.east) : 180;

    let vesselCount = 0;
    let vectorCount = 0;

    for (const vessel of vesselsRef.current) {
      // Viewport culling
      if (vessel.latitude < south || vessel.latitude > north) continue;
      // Handle date-line wrapping
      if (west < east) {
        if (vessel.longitude < west || vessel.longitude > east) continue;
      } else {
        if (vessel.longitude < west && vessel.longitude > east) continue;
      }

      if (vesselCount >= MAX_RENDERED_VESSELS) break;

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
      vesselCount++;

      if (showVectors && vectorCount < MAX_COURSE_VECTORS && vessel.speed_knots > 0.5) {
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
        vectorCount++;
      }
    }
  }, [viewer]);

  // Re-render on data change
  useEffect(() => {
    renderVisible();
  }, [vessels, visible, degradation, renderVisible]);

  // Re-render on camera move (viewport changes)
  useEffect(() => {
    if (!viewer || viewer.isDestroyed()) return;

    const onMoveEnd = () => renderVisible();

    viewer.camera.moveEnd.addEventListener(onMoveEnd);
    return () => {
      if (!viewer.isDestroyed()) viewer.camera.moveEnd.removeEventListener(onMoveEnd);
    };
  }, [viewer, renderVisible]);

  return null;
}
