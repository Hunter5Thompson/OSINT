import { useEffect, useRef, useState } from "react";
import * as Cesium from "cesium";
import { useSpotlight } from "./SpotlightContext";

interface Props {
  viewer: Cesium.Viewer | null;
}

export function CapitalPulse({ viewer }: Props) {
  const { focusTarget } = useSpotlight();
  const [projected, setProjected] = useState(false);
  const elRef = useRef<HTMLDivElement | null>(null);
  const projectedRef = useRef(false);

  const isActive = focusTarget?.kind === "country" && focusTarget.capital !== null;
  const capital = isActive ? focusTarget.capital! : null;
  const cityName = capital?.name ?? "";

  useEffect(() => {
    if (!viewer || viewer.isDestroyed() || !capital) {
      if (projectedRef.current) {
        projectedRef.current = false;
        setProjected(false);
      }
      return;
    }
    const cartesian = Cesium.Cartesian3.fromDegrees(capital.coords.lon, capital.coords.lat);
    const setProjectedVisible = (next: boolean) => {
      if (projectedRef.current === next) return;
      projectedRef.current = next;
      setProjected(next);
    };
    const update = () => {
      if (viewer.isDestroyed()) return;
      const win = Cesium.SceneTransforms.worldToWindowCoordinates(viewer.scene, cartesian);
      const el = elRef.current;
      if (!win || !el) {
        setProjectedVisible(false);
        return;
      }
      el.style.transform = `translate3d(${win.x}px, ${win.y}px, 0) translate(-50%, -50%)`;
      setProjectedVisible(true);
    };
    update();
    const remove = viewer.scene.preUpdate.addEventListener(update);
    return () => remove();
  }, [viewer, capital]);

  if (!isActive) return null;

  return (
    <div
      ref={elRef}
      className="capital-pulse"
      style={{
        left: 0,
        top: 0,
        transform: "translate3d(0, 0, 0) translate(-50%, -50%)",
        visibility: projected ? "visible" : "hidden",
      }}
      aria-hidden="true"
    >
      <span className="capital-pulse-dot" />
      <span className="capital-pulse-ring" />
      <span className="capital-pulse-label">{cityName}</span>
    </div>
  );
}
