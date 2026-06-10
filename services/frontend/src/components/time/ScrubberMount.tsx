import { useEffect, useMemo, useState } from "react";
import type { TimelineGeoEvent } from "../../types";
import { useTime } from "../../state/TimeContext";
import { useTimeHistogram } from "../../hooks/useTimeHistogram";
import { ChronikTimeline } from "./ChronikTimeline";

type Preset = "24h" | "7d" | "30d";

const PRESET_SPAN_MS: Record<Preset, number> = {
  "24h": 86_400_000,
  "7d": 7 * 86_400_000,
  "30d": 30 * 86_400_000,
};
const COARSE_ROLL_MS = 60_000; // advance the rolling window every 60s

function rollingWindow(spanMs: number): { tStart: string; tEnd: string } {
  const now = Date.now();
  return { tStart: new Date(now - spanMs).toISOString(), tEnd: new Date(now).toISOString() };
}

interface ScrubberMountProps {
  onSelectEvent: (id: string) => void; // notable-dot click -> opens the callout
  onTimelineData: (d: {
    geoEvents: TimelineGeoEvent[];
    window: { startMs: number; endMs: number } | null; // active fade window for EventLayer (§7)
  }) => void;
}

// useTime() consumer that drives the § CHRONIK density timeline: coarse histogram over a
// rolling preset window, click=pause+seek vs drag=brush, and lifts geo_events + the active
// fade window up to WorldviewPage.
export function ScrubberMount({ onSelectEvent, onTimelineData }: ScrubberMountProps) {
  const { mode, cursorMs, playing, seek, pause, play, setMode, setReplayWindow } = useTime();

  const [preset, setPreset] = useState<Preset>("7d");
  const [coarse, setCoarse] = useState(() => rollingWindow(PRESET_SPAN_MS["7d"]));
  const [brush, setBrush] = useState<{ startMs: number; endMs: number } | null>(null);

  // Roll the coarse window forward (and re-anchor when the preset changes) so newly
  // ingested events keep appearing; preset change resets the span ONLY.
  useEffect(() => {
    setCoarse(rollingWindow(PRESET_SPAN_MS[preset]));
    const id = setInterval(() => setCoarse(rollingWindow(PRESET_SPAN_MS[preset])), COARSE_ROLL_MS);
    return () => clearInterval(id);
  }, [preset]);

  const { data } = useTimeHistogram(
    true,
    { tStart: coarse.tStart, tEnd: coarse.tEnd, buckets: 120 },
    30_000,
  );

  // Active fade window: the static brush in replay, else the coarse bounds in live (so all
  // coarse-range dots stay visible and fade by recency to the live cursor). Using coarse
  // bounds — which change on the 60s roll, NOT every cursor tick — keeps the 4Hz cursor OUT
  // of this lifted state, so WorldviewPage isn't re-rendered every tick.
  const activeWindow = useMemo<{ startMs: number; endMs: number } | null>(
    () =>
      mode === "replay"
        ? brush
        : { startMs: Date.parse(coarse.tStart), endMs: Date.parse(coarse.tEnd) },
    [mode, brush, coarse.tStart, coarse.tEnd],
  );

  useEffect(() => {
    onTimelineData({ geoEvents: data?.geo_events ?? [], window: activeWindow });
  }, [data, activeWindow, onTimelineData]);

  const enterReplay = (startMs: number, endMs: number, cursorTarget: number) => {
    setBrush({ startMs, endMs });
    setReplayWindow(startMs, endMs);
    setMode("replay");
    seek(cursorTarget);
  };

  return (
    <ChronikTimeline
      buckets={data?.buckets ?? []}
      notables={data?.notables ?? []}
      rangeStartMs={Date.parse(coarse.tStart)}
      rangeEndMs={Date.parse(coarse.tEnd)}
      cursorMs={cursorMs}
      mode={mode}
      playing={playing}
      preset={preset}
      geoLocatedCount={data?.geo_located_count ?? 0}
      totalCount={data?.total_count ?? 0}
      onSeek={(ms) => {
        pause(); // HARD §5: pause so the cursor holds in live (SYSTEM_CLOCK would yank it)
        seek(ms);
      }}
      onBrush={(s, e) => enterReplay(s, e, s)}
      onSelectNotable={(id) => onSelectEvent(id)}
      onTogglePlay={() => (playing ? pause() : play())}
      onNow={() => {
        // HARD gate: re-pin to now even from live-paused (setMode is a no-op when already live)
        setBrush(null);
        seek(Date.now());
        setMode("live");
        play();
      }}
      onPreset={setPreset}
    />
  );
}
