import { useState, useEffect } from "react";
import type { AircraftTrack } from "../types";
import { getAircraftTracks } from "../services/api";

const POLL_INTERVAL = 30_000;

export function useAircraftTracks(enabled: boolean, sinceHours = 24) {
  const [tracks, setTracks] = useState<AircraftTrack[]>([]);
  const [loading, setLoading] = useState(false);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);

  useEffect(() => {
    if (!enabled) {
      setTracks([]);
      return;
    }
    let cancelled = false;
    const run = async () => {
      if (typeof document !== "undefined" && document.hidden) return;
      setLoading(true);
      try {
        const data = await getAircraftTracks(sinceHours);
        if (cancelled) return;
        setTracks(data);
        setLastUpdate(new Date());
      } catch {
        // keep stale data
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    void run();
    const timer = setInterval(() => { void run(); }, POLL_INTERVAL);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [enabled, sinceHours]);

  return { tracks, loading, lastUpdate };
}
