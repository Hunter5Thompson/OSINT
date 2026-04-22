import { useState, useEffect } from "react";
import type { Earthquake } from "../types";
import { getEarthquakes } from "../services/api";

const POLL_INTERVAL = 300_000; // 5 minutes

export function useEarthquakes(enabled: boolean) {
  const [earthquakes, setEarthquakes] = useState<Earthquake[]>([]);
  const [loading, setLoading] = useState(false);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);

  useEffect(() => {
    if (!enabled) {
      setEarthquakes([]);
      setLoading(false);
      return;
    }
    let cancelled = false;
    const run = async () => {
      setLoading(true);
      try {
        const data = await getEarthquakes();
        if (cancelled) return;
        setEarthquakes(data);
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
  }, [enabled]);

  return { earthquakes, loading, lastUpdate };
}
