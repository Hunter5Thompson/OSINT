import {
  createContext, useCallback, useContext, useEffect, useMemo, useRef, useState,
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
  setReplayWindow: (startMs: number, endMs: number) => void;
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
  const windowRef = useRef<{ start: number; end: number } | null>(null);
  const [cursorMs, setCursorMs] = useState<number>(timeRef.current);
  const [mode, setModeState] = useState<TimeMode>("live");
  const [playing, setPlaying] = useState(true);
  const [speed, setSpeedState] = useState(1);
  const [discontinuityEpoch, setEpoch] = useState(0);

  // Refs mirror play/speed so the mode-config effect can read them without
  // re-running (and re-configuring the clock) on every play/pause/speed change.
  const playingRef = useRef(playing);
  playingRef.current = playing;
  const speedRef = useRef(speed);
  speedRef.current = speed;

  const getTimeMs = useCallback(() => timeRef.current, []);
  const bumpEpoch = useCallback(() => setEpoch((e) => e + 1), []);

  // Real clock driver: subscribe to onTick ONCE per viewer (no mode/playing dep,
  // so toggles don't churn the subscription). Throttle the UI cursor to ~4 Hz.
  useEffect(() => {
    if (!viewer || viewer.isDestroyed()) return undefined;
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
  }, [viewer]);

  // Fallback wall-clock tick when there is no viewer (tests / pre-init).
  useEffect(() => {
    if (viewer && !viewer.isDestroyed()) return undefined;
    const id = setInterval(() => {
      if (mode === "live" && playing) {
        timeRef.current = Date.now();
        setCursorMs(timeRef.current);
      }
    }, UI_THROTTLE_MS);
    return () => clearInterval(id);
  }, [viewer, mode, playing]);

  // Configure the Cesium clock for the current mode on viewer attach + mode change.
  // Without this the Viewer mounts with shouldAnimate=false, freezing live time;
  // replay clamps to the window bounds; shouldAnimate tracks the play state.
  useEffect(() => {
    if (!viewer || viewer.isDestroyed()) return;
    const clock = viewer.clock;
    if (mode === "live") {
      clock.clockStep = Cesium.ClockStep.SYSTEM_CLOCK;
      clock.clockRange = Cesium.ClockRange.UNBOUNDED;
      clock.currentTime = Cesium.JulianDate.now();
      timeRef.current = Date.now();
    } else {
      clock.clockStep = Cesium.ClockStep.SYSTEM_CLOCK_MULTIPLIER;
      clock.multiplier = speedRef.current;
      const w = windowRef.current;
      if (w) {
        clock.startTime = Cesium.JulianDate.fromDate(new Date(w.start));
        clock.stopTime = Cesium.JulianDate.fromDate(new Date(w.end));
        clock.clockRange = Cesium.ClockRange.CLAMPED;
      } else {
        clock.clockRange = Cesium.ClockRange.UNBOUNDED;
      }
    }
    clock.shouldAnimate = playingRef.current;
  }, [viewer, mode]);

  const seek = useCallback(
    (ms: number) => {
      if (!Number.isFinite(ms)) return; // defensive: never seek to NaN
      timeRef.current = ms;
      setCursorMs(ms);
      if (viewer && !viewer.isDestroyed()) {
        viewer.clock.currentTime = Cesium.JulianDate.fromDate(new Date(ms));
      }
      bumpEpoch(); // every explicit seek, including forward
    },
    [viewer, bumpEpoch],
  );

  // Just flip the mode state + signal a discontinuity; the clock-config effect
  // reacts to the mode change.
  const setMode = useCallback(
    (m: TimeMode) => {
      setModeState(m);
      bumpEpoch();
    },
    [bumpEpoch],
  );

  const setReplayWindow = useCallback(
    (startMs: number, endMs: number) => {
      if (!Number.isFinite(startMs) || !Number.isFinite(endMs)) return;
      windowRef.current = { start: startMs, end: endMs };
      if (viewer && !viewer.isDestroyed() && mode === "replay") {
        const clock = viewer.clock;
        clock.startTime = Cesium.JulianDate.fromDate(new Date(startMs));
        clock.stopTime = Cesium.JulianDate.fromDate(new Date(endMs));
        clock.clockRange = Cesium.ClockRange.CLAMPED;
      }
    },
    [viewer, mode],
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

  // Memoized so getTimeMs-only consumers don't re-render on the ~4 Hz cursor tick
  // (spec §7.2 hot/UI split).
  const value = useMemo<TimeContextValue>(
    () => ({
      mode, playing, speed, cursorMs, discontinuityEpoch,
      getTimeMs, seek, setMode, setReplayWindow, play, pause, setSpeed,
    }),
    [
      mode, playing, speed, cursorMs, discontinuityEpoch,
      getTimeMs, seek, setMode, setReplayWindow, play, pause, setSpeed,
    ],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useTime(): TimeContextValue {
  const v = useContext(Ctx);
  if (!v) throw new Error("useTime must be used within TimeProvider");
  return v;
}
