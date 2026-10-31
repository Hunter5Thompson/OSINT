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
    let disposed = false;
    let sequence = 0;
    let controller: AbortController | null = null;
    const run = async () => {
      const request = ++sequence;
      controller?.abort();
      const currentController = new AbortController();
      controller = currentController;
      setLoading(true);
      try {
        const data = await getEarthquakes(currentController.signal);
        if (disposed || request !== sequence) return;
        setEarthquakes(data);
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
  }, [enabled]);

  return { earthquakes, loading, lastUpdate };
}
