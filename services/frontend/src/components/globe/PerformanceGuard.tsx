import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import type { Viewer } from "cesium";
import { RenderBudget, type RenderSample } from "./renderBudget";
export type { DegradationLevel } from "./renderBudget";

/** 0 full; 1 short trails; 2 static pulses; 3 no arcs/trails; 4 static dots. */
const PerformanceContext = createContext<RenderSample>({ fps: 0, degradation: 0 });
export function usePerformance(): RenderSample { return useContext(PerformanceContext); }

export function PerformanceGuard({ viewer, children }: { viewer: Viewer | null; children: ReactNode }) {
  const [state, setState] = useState<RenderSample>({ fps: 0, degradation: 0 });
  useEffect(() => {
    if (!viewer || viewer.isDestroyed()) return;
    const meter = new RenderBudget(performance.now());
    let moving = false;
    const removeFrame = viewer.scene.postRender.addEventListener(() => meter.frame());
    const removeStart = viewer.camera.moveStart.addEventListener(() => { moving = true; });
    const removeEnd = viewer.camera.moveEnd.addEventListener(() => { moving = false; });
    const sample = () => {
      if (viewer.isDestroyed()) return;
      setState(meter.sample(performance.now(), document.visibilityState === "visible"
        && (!viewer.scene.requestRenderMode || moving)));
    };
    const resetWindow = () => { meter.sample(performance.now(), false); };
    document.addEventListener("visibilitychange", resetWindow);
    const timer = window.setInterval(sample, 1000);
    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", resetWindow);
      removeFrame(); removeStart(); removeEnd();
    };
  }, [viewer]);
  return <PerformanceContext.Provider value={state}>{children}</PerformanceContext.Provider>;
}
