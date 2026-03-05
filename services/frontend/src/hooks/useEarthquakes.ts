import { useState, useEffect, useCallback } from "react";
import type { Earthquake } from "../types";
import { getEarthquakes } from "../services/api";

const POLL_INTERVAL = 300_000; // 5 minutes

export function useEarthquakes(enabled: boolean) {
  const [earthquakes, setEarthquakes] = useState<Earthquake[]>([]);
  const [loading, setLoading] = useState(false);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);

  const fetchData = useCallback(async () => {
    if (!enabled) return;
    setLoading(true);
    try {
      const data = await getEarthquakes();
      setEarthquakes(data);
      setLastUpdate(new Date());
    } catch {
      // keep stale data
    } finally {
      setLoading(false);
    }
  }, [enabled]);

  useEffect(() => {
    if (!enabled) {
      setEarthquakes([]);
      return;
    }
    void fetchData();
    const timer = setInterval(() => void fetchData(), POLL_INTERVAL);
    return () => clearInterval(timer);
  }, [enabled, fetchData]);

  return { earthquakes, loading, lastUpdate };
}
