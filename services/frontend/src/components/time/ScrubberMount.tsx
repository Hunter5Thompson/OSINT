import { useEffect, useState } from "react";
import type { WindowEventSample } from "../../types";
import { useTime } from "../../state/TimeContext";
import { useTimeWindow } from "../../hooks/useTimeWindow";
import { TwoTierScrubber } from "./TwoTierScrubber";

const COARSE_SPAN_MS = 7 * 86_400_000; // last 7 days of event ticks
const COARSE_ROLL_MS = 60_000; // advance the rolling window every 60s
const EVENT_REPLAY_SPAN_MS = 3 * 3600_000; // event click -> ±3h replay window
const TOGGLE_REPLAY_SPAN_MS = 6 * 3600_000; // toggle -> replay the last 6h

function rollingCoarseWindow(): { tStart: string; tEnd: string } {
  const now = Date.now();
  return {
    tStart: new Date(now - COARSE_SPAN_MS).toISOString(),
    tEnd: new Date(now).toISOString(),
  };
}

// useTime() consumer that drives the two-tier scrubber: coarse graph events over a
// ROLLING recent window (so events ingested after page-open still appear), a mode
// toggle that establishes the replay clamp bounds, and event-click scoping.
export function ScrubberMount({
  onSelectWindow,
}: {
  onSelectWindow: (w: { tStart: string; tEnd: string }) => void;
}) {
  const { mode, cursorMs, seek, setMode, setReplayWindow } = useTime();

  // Roll the coarse window forward so newly-ingested events keep appearing.
  const [coarse, setCoarse] = useState(rollingCoarseWindow);
  useEffect(() => {
    const id = setInterval(() => setCoarse(rollingCoarseWindow()), COARSE_ROLL_MS);
    return () => clearInterval(id);
  }, []);

  const { data } = useTimeWindow(
    true,
    {
      tStart: coarse.tStart,
      tEnd: coarse.tEnd,
      domain: "events",
      tier: "coarse",
      limit: 200,
    },
    30_000,
  );
  const events = (data?.samples ?? []).filter(
    (s): s is WindowEventSample => s.kind === "event",
  );

  // Entering replay (via toggle OR event click) must establish CLAMP bounds on the
  // Cesium clock AND drop the cursor into the window — otherwise the clock runs
  // unbounded at live time while replay data is loaded for the window.
  const enterReplay = (startMs: number, endMs: number, cursorTarget: number) => {
    onSelectWindow({
      tStart: new Date(startMs).toISOString(),
      tEnd: new Date(endMs).toISOString(),
    });
    setReplayWindow(startMs, endMs);
    setMode("replay");
    seek(cursorTarget);
  };

  return (
    <TwoTierScrubber
      events={events}
      mode={mode}
      cursorMs={cursorMs}
      onSelectEvent={(e) => {
        const t = Date.parse(e.time);
        if (!Number.isNaN(t)) {
          enterReplay(t - EVENT_REPLAY_SPAN_MS, t + EVENT_REPLAY_SPAN_MS, t);
        }
      }}
      onSeek={seek}
      onToggleMode={() => {
        if (mode === "live") {
          const end = Date.now();
          enterReplay(end - TOGGLE_REPLAY_SPAN_MS, end, end - TOGGLE_REPLAY_SPAN_MS);
        } else {
          setMode("live");
        }
      }}
    />
  );
}
