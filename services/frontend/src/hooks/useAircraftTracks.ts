import { useState, useEffect, useCallback } from "react";
import type { AircraftTrack } from "../types";
import { getAircraftTracks } from "../services/api";

const POLL_INTERVAL = 30_000;

export function useAircraftTracks(enabled: boolean, sinceHours = 24) {
  const [tracks, setTracks] = useState<AircraftTrack[]>([]);
  const [loading, setLoading] = useState(false);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);

  const fetchData = useCallback(async () => {
    if (!enabled) return;
    if (typeof document !== "undefined" && document.hidden) return;
    setLoading(true);
    try {
      const data = await getAircraftTracks(sinceHours);
      setTracks(data);
      setLastUpdate(new Date());
    } catch {
      // keep stale data
    } finally {
      setLoading(false);
    }
  }, [enabled, sinceHours]);

  useEffect(() => {
    if (!enabled) {
      setTracks([]);
      return;
    }
    void fetchData();
    const timer = setInterval(() => void fetchData(), POLL_INTERVAL);
    return () => clearInterval(timer);
  }, [enabled, fetchData]);

  return { tracks, loading, lastUpdate };
}
