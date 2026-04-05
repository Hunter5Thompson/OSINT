import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";

/**
 * Degradation levels (higher = more features disabled):
 * 0 = full animations
 * 1 = shortened trails (10 positions instead of 30)
 * 2 = no pulse animations (static rings only)
 * 3 = no orbit arcs, no trails
 * 4 = static dots only (all animations off)
 */
export type DegradationLevel = 0 | 1 | 2 | 3 | 4;

interface PerformanceState {
  fps: number;
  degradation: DegradationLevel;
}

const PerformanceContext = createContext<PerformanceState>({ fps: 60, degradation: 0 });

export function usePerformance(): PerformanceState {
  return useContext(PerformanceContext);
}

const FPS_THRESHOLD = 30;
const SUSTAINED_LOW_FPS_MS = 2000;
const RECOVERY_MS = 5000;

export function PerformanceGuard({ children }: { children: ReactNode }) {
  const [state, setState] = useState<PerformanceState>({ fps: 60, degradation: 0 });
  const frameCountRef = useRef(0);
  const lastTimeRef = useRef(performance.now());
  const lowFpsSinceRef = useRef<number | null>(null);
  const highFpsSinceRef = useRef<number | null>(null);

  useEffect(() => {
    let animId: number;

    const measure = () => {
      frameCountRef.current++;
      const now = performance.now();

      if (now - lastTimeRef.current >= 1000) {
        const currentFps = frameCountRef.current;
        frameCountRef.current = 0;
        lastTimeRef.current = now;

        setState((prev) => {
          let nextDeg = prev.degradation;

          if (currentFps < FPS_THRESHOLD) {
            highFpsSinceRef.current = null;
            if (lowFpsSinceRef.current === null) {
              lowFpsSinceRef.current = now;
            } else if (now - lowFpsSinceRef.current >= SUSTAINED_LOW_FPS_MS && nextDeg < 4) {
              nextDeg = Math.min(4, nextDeg + 1) as DegradationLevel;
              lowFpsSinceRef.current = now;
            }
          } else {
            lowFpsSinceRef.current = null;
            if (highFpsSinceRef.current === null) {
              highFpsSinceRef.current = now;
            } else if (now - highFpsSinceRef.current >= RECOVERY_MS && nextDeg > 0) {
              nextDeg = Math.max(0, nextDeg - 1) as DegradationLevel;
              highFpsSinceRef.current = now;
            }
          }

          return { fps: currentFps, degradation: nextDeg };
        });
      }

      animId = requestAnimationFrame(measure);
    };

    animId = requestAnimationFrame(measure);
    return () => cancelAnimationFrame(animId);
  }, []);

  return (
    <PerformanceContext.Provider value={state}>
      {children}
    </PerformanceContext.Provider>
  );
}
