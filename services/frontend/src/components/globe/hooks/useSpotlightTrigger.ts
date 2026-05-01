import { useEffect, useRef } from "react";
import * as Cesium from "cesium";
import { useSpotlight, type FocusTarget } from "../spotlight/SpotlightContext";

const ZOOM_THRESHOLD_M = 500_000;
const ZOOM_EXIT_M = 1_500_000;

export function useSpotlightTrigger(viewer: Cesium.Viewer | null): void {
  const { focusTarget, dispatch } = useSpotlight();

  // Mirror focusTarget into a ref so the listener (mounted once per viewer)
  // can read fresh state without re-registering on every state change.
  const focusRef = useRef<FocusTarget>(focusTarget);
  focusRef.current = focusTarget;

  useEffect(() => {
    if (!viewer || viewer.isDestroyed()) return;
    const camera = viewer.camera;

    const onMoveEnd = () => {
      const carto = camera.positionCartographic;
      if (!carto) return;
      const altitude = carto.height;
      const lon = Cesium.Math.toDegrees(carto.longitude);
      const lat = Cesium.Math.toDegrees(carto.latitude);

      // Sticky-Pin/Search: do NOT overwrite when a non-zoom trigger is active.
      const ft = focusRef.current;
      const isSticky =
        ft != null &&
        ft.trigger !== "zoom";

      if (altitude <= ZOOM_THRESHOLD_M && !isSticky) {
        dispatch({
          type: "set",
          target: {
            kind: "circle", trigger: "zoom",
            center: { lon, lat }, radius: 1, altitude,
            label: `${lat.toFixed(2)}N · ${lon.toFixed(2)}E`,
          },
        });
      } else if (altitude >= ZOOM_EXIT_M && ft?.trigger === "zoom") {
        dispatch({ type: "reset" });
      }
    };

    // moveEnd fires after the user stops moving the camera, which is the
    // correct edge for "user finished zooming" — `changed` would fire dozens
    // of times mid-gesture and cause primitive churn.
    const remove = camera.moveEnd.addEventListener(onMoveEnd);
    return () => remove();
  }, [viewer, dispatch]);
}
