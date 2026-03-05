import { useRef, useCallback } from "react";
import * as Cesium from "cesium";

/**
 * Hook managing a CesiumJS Viewer reference.
 * Does NOT create the viewer — GlobeViewer handles that.
 */
export function useCesium() {
  const viewerRef = useRef<Cesium.Viewer | null>(null);

  const setViewer = useCallback((viewer: Cesium.Viewer) => {
    viewerRef.current = viewer;
  }, []);

  const flyTo = useCallback(
    (lat: number, lon: number, height: number = 1_000_000) => {
      viewerRef.current?.camera.flyTo({
        destination: Cesium.Cartesian3.fromDegrees(lon, lat, height),
        duration: 2.0,
      });
    },
    [],
  );

  return { viewerRef, setViewer, flyTo };
}
