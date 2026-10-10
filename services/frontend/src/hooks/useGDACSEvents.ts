import { useState, useEffect } from "react";
import type { GDACSEvent } from "../types";
import { getGDACSEvents } from "../services/api";

const POLL_INTERVAL = 120_000;

export function useGDACSEvents(enabled: boolean, sinceHours = 168) {
  const [events, setEvents] = useState<GDACSEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);

  useEffect(() => {
    if (!enabled) {
      setEvents([]);
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
        const data = await getGDACSEvents(sinceHours, currentController.signal);
        if (disposed || request !== sequence) return;
        setEvents(data);
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

  return { events, loading, lastUpdate };
}
