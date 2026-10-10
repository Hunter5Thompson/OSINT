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
      setLoading(false);
      return;
    }
    let disposed = false;
    let sequence = 0;
    let controller: AbortController | null = null;
    const run = async () => {
      if (typeof document !== "undefined" && document.hidden) return;
      const request = ++sequence;
      controller?.abort();
      const currentController = new AbortController();
      controller = currentController;
      setLoading(true);
      try {
        const data = await getAircraftTracks(sinceHours, currentController.signal);
        if (disposed || request !== sequence) return;
        setTracks(data);
        setLastUpdate(new Date());
      } catch {
        // Keep the last successful data; only the current request owns loading.
      } finally {
        if (!disposed && request === sequence) setLoading(false);
      }
    };
    void run();
    const timer = setInterval(() => { void run(); }, POLL_INTERVAL);
    return () => {
      disposed = true;
      ++sequence;
      controller?.abort();
      clearInterval(timer);
    };
  }, [enabled, sinceHours]);

  return { tracks, loading, lastUpdate };
}
