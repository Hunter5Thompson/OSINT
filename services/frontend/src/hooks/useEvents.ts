import { useState, useEffect, useCallback } from "react";
import type { IntelEvent } from "../types";
import { getGeoEvents } from "../services/api";

const POLL_INTERVAL = 60_000; // 60 seconds

export function useEvents(enabled: boolean) {
  const [events, setEvents] = useState<IntelEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);

  const fetchData = useCallback(async () => {
    if (!enabled) return;
    setLoading(true);
    try {
      const data = await getGeoEvents(100);
      // Only keep events with coordinates for globe rendering
      setEvents(data.filter((e) => e.lat != null && e.lon != null));
      setLastUpdate(new Date());
    } catch {
      // keep stale data
    } finally {
      setLoading(false);
    }
  }, [enabled]);

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
