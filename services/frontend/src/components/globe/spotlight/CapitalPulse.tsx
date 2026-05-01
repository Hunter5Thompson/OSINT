import { useEffect, useRef, useState } from "react";
import * as Cesium from "cesium";
import { useSpotlight } from "./SpotlightContext";

interface Props {
  viewer: Cesium.Viewer | null;
}

export function CapitalPulse({ viewer }: Props) {
  const { focusTarget } = useSpotlight();
  const [screenPos, setScreenPos] = useState<{ x: number; y: number } | null>(null);
  const elRef = useRef<HTMLDivElement | null>(null);

  const isActive = focusTarget?.kind === "country" && focusTarget.capital !== null;
  const capital = isActive ? focusTarget.capital! : null;
  const cityName = capital?.name ?? "";

  useEffect(() => {
    if (!viewer || viewer.isDestroyed() || !capital) {
      setScreenPos(null);
      return;
    }
    const cartesian = Cesium.Cartesian3.fromDegrees(capital.coords.lon, capital.coords.lat);
    const update = () => {
      if (viewer.isDestroyed()) return;
      const win = Cesium.SceneTransforms.worldToWindowCoordinates(viewer.scene, cartesian);
      if (win) setScreenPos({ x: win.x, y: win.y });
      else setScreenPos(null);
    };
    update();
    const remove = viewer.scene.preUpdate.addEventListener(update);
    return () => remove();
  }, [viewer, capital]);

  if (!isActive || !screenPos) return null;

  return (
    <div
      ref={elRef}
      className="capital-pulse"
      style={{ left: screenPos.x, top: screenPos.y }}
      aria-hidden="true"
    >
      <span className="capital-pulse-dot" />
      <span className="capital-pulse-ring" />
      <span className="capital-pulse-label">{cityName}</span>
    </div>
  );
}
