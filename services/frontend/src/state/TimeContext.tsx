import {
  createContext, useCallback, useContext, useEffect, useRef, useState,
  type ReactNode,
} from "react";
import * as Cesium from "cesium";

export type TimeMode = "live" | "replay";

interface TimeContextValue {
  mode: TimeMode;
  playing: boolean;
  speed: number;
  cursorMs: number; // throttled (~4 Hz) display value — do NOT use in hot loops
  discontinuityEpoch: number;
  getTimeMs: () => number; // hot path: ref-based, safe in per-frame loops
  seek: (ms: number) => void;
  setMode: (m: TimeMode) => void;
  play: () => void;
  pause: () => void;
  setSpeed: (s: number) => void;
}

const Ctx = createContext<TimeContextValue | null>(null);

const UI_THROTTLE_MS = 250; // ~4 Hz

export function TimeProvider({
  viewer,
  children,
}: {
  viewer: Cesium.Viewer | null;
  children: ReactNode;
}) {
  const timeRef = useRef<number>(Date.now());
  const lastUiRef = useRef<number>(0);
  const [cursorMs, setCursorMs] = useState<number>(timeRef.current);
  const [mode, setModeState] = useState<TimeMode>("live");
  const [playing, setPlaying] = useState(true);
  const [speed, setSpeedState] = useState(1);
  const [discontinuityEpoch, setEpoch] = useState(0);

  const getTimeMs = useCallback(() => timeRef.current, []);

  // Drive timeRef from the Cesium clock when a viewer exists; otherwise simulate.
  useEffect(() => {
    if (viewer && !viewer.isDestroyed()) {
      const clock = viewer.clock;
      const remove = clock.onTick.addEventListener((c) => {
        const ms = Cesium.JulianDate.toDate(c.currentTime).getTime();
        timeRef.current = ms;
        const t = performance.now();
        if (t - lastUiRef.current >= UI_THROTTLE_MS) {
          lastUiRef.current = t;
          setCursorMs(ms);
        }
      });
      return () => remove();
    }
    // Fallback (tests / no viewer): tick from wall clock when live+playing.
    const id = setInterval(() => {
      if (mode === "live" && playing) {
        timeRef.current = Date.now();
        setCursorMs(timeRef.current);
      }
    }, UI_THROTTLE_MS);
    return () => clearInterval(id);
  }, [viewer, mode, playing]);

  const bumpEpoch = useCallback(() => setEpoch((e) => e + 1), []);

  const seek = useCallback(
    (ms: number) => {
      timeRef.current = ms;
      setCursorMs(ms);
      if (viewer && !viewer.isDestroyed()) {
        viewer.clock.currentTime = Cesium.JulianDate.fromDate(new Date(ms));
      }
      bumpEpoch(); // every explicit seek, including forward
    },
    [viewer, bumpEpoch],
  );

  const setMode = useCallback(
    (m: TimeMode) => {
      setModeState(m);
      if (viewer && !viewer.isDestroyed()) {
        const clock = viewer.clock;
        if (m === "live") {
          clock.clockRange = Cesium.ClockRange.UNBOUNDED;
          clock.clockStep = Cesium.ClockStep.SYSTEM_CLOCK;
          clock.shouldAnimate = true;
          timeRef.current = Date.now();
          clock.currentTime = Cesium.JulianDate.now();
        } else {
          clock.clockRange = Cesium.ClockRange.CLAMPED;
          clock.clockStep = Cesium.ClockStep.SYSTEM_CLOCK_MULTIPLIER;
        }
      }
      bumpEpoch();
    },
    [viewer, bumpEpoch],
  );

  const play = useCallback(() => {
    setPlaying(true);
    if (viewer && !viewer.isDestroyed()) viewer.clock.shouldAnimate = true;
  }, [viewer]);

  const pause = useCallback(() => {
    setPlaying(false);
    if (viewer && !viewer.isDestroyed()) viewer.clock.shouldAnimate = false;
  }, [viewer]);

  const setSpeed = useCallback(
    (s: number) => {
      setSpeedState(s);
      if (viewer && !viewer.isDestroyed()) viewer.clock.multiplier = s;
    },
    [viewer],
  );

  const value: TimeContextValue = {
    mode, playing, speed, cursorMs, discontinuityEpoch,
    getTimeMs, seek, setMode, play, pause, setSpeed,
  };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useTime(): TimeContextValue {
  const v = useContext(Ctx);
  if (!v) throw new Error("useTime must be used within TimeProvider");
  return v;
}
