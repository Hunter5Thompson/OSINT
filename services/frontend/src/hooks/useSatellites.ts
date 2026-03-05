import { useState, useEffect, useCallback } from "react";
import type { Satellite } from "../types";
import { getSatellites } from "../services/api";

export function useSatellites(enabled: boolean) {
  const [satellites, setSatellites] = useState<Satellite[]>([]);
  const [loading, setLoading] = useState(false);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);

  const fetchData = useCallback(async () => {
    if (!enabled) return;
    setLoading(true);
    try {
      const data = await getSatellites();
      setSatellites(data);
      setLastUpdate(new Date());
    } catch {
      // keep stale data
    } finally {
      setLoading(false);
    }
  }, [enabled]);

  useEffect(() => {
    if (!enabled) {
      setSatellites([]);
      return;
    }
    void fetchData();
    // TLE data refreshes hourly
    const timer = setInterval(() => void fetchData(), 3_600_000);
    return () => clearInterval(timer);
  }, [enabled, fetchData]);

  return { satellites, loading, lastUpdate };
}
