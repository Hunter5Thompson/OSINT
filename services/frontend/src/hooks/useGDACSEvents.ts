import { useState, useEffect, useCallback } from "react";
import type { GDACSEvent } from "../types";
import { getGDACSEvents } from "../services/api";

const POLL_INTERVAL = 120_000;

export function useGDACSEvents(enabled: boolean, sinceHours = 168) {
  const [events, setEvents] = useState<GDACSEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);

  const fetchData = useCallback(async () => {
    if (!enabled) return;
    if (typeof document !== "undefined" && document.hidden) return;
    setLoading(true);
    try {
      const data = await getGDACSEvents(sinceHours);
      setEvents(data);
      setLastUpdate(new Date());
    } catch {
      // keep stale data
    } finally {
      setLoading(false);
    }
  }, [enabled, sinceHours]);

  useEffect(() => {
    if (!enabled) {
      setEvents([]);
      return;
    }
    void fetchData();
    const timer = setInterval(() => void fetchData(), POLL_INTERVAL);
    return () => clearInterval(timer);
  }, [enabled, fetchData]);

  return { events, loading, lastUpdate };
}
