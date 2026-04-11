import { useState, useEffect, useCallback } from "react";
import type { FIRMSHotspot } from "../types";
import { getFIRMSHotspots } from "../services/api";

const POLL_INTERVAL = 60_000;

export function useFIRMSHotspots(enabled: boolean, sinceHours = 24) {
  const [hotspots, setHotspots] = useState<FIRMSHotspot[]>([]);
  const [loading, setLoading] = useState(false);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);

  const fetchData = useCallback(async () => {
    if (!enabled) return;
    if (typeof document !== "undefined" && document.hidden) return;
    setLoading(true);
    try {
      const data = await getFIRMSHotspots(sinceHours);
      setHotspots(data);
      setLastUpdate(new Date());
    } catch {
      // keep stale data
    } finally {
      setLoading(false);
    }
  }, [enabled, sinceHours]);

  useEffect(() => {
    if (!enabled) {
      setHotspots([]);
      return;
    }
    void fetchData();
    const timer = setInterval(() => void fetchData(), POLL_INTERVAL);
    return () => clearInterval(timer);
  }, [enabled, fetchData]);

  return { hotspots, loading, lastUpdate };
}
