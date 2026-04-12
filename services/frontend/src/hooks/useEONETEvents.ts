import { useState, useEffect, useCallback } from "react";
import type { EONETEvent } from "../types";
import { getEONETEvents } from "../services/api";

const POLL_INTERVAL = 120_000;

export function useEONETEvents(enabled: boolean, sinceHours = 168) {
  const [events, setEvents] = useState<EONETEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);

  const fetchData = useCallback(async () => {
    if (!enabled) return;
    if (typeof document !== "undefined" && document.hidden) return;
    setLoading(true);
    try {
      const data = await getEONETEvents(sinceHours);
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
