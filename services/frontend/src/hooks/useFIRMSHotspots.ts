import { useState, useEffect } from "react";
import type { FIRMSHotspot } from "../types";
import { getFIRMSHotspots } from "../services/api";

const POLL_INTERVAL = 60_000;

export function useFIRMSHotspots(enabled: boolean, sinceHours = 24) {
  const [hotspots, setHotspots] = useState<FIRMSHotspot[]>([]);
  const [loading, setLoading] = useState(false);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);

  useEffect(() => {
    if (!enabled) {
      setHotspots([]);
      return;
    }
    let cancelled = false;
    const run = async () => {
      if (typeof document !== "undefined" && document.hidden) return;
      setLoading(true);
      try {
        const data = await getFIRMSHotspots(sinceHours);
        if (cancelled) return;
        setHotspots(data);
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

  return { hotspots, loading, lastUpdate };
}
