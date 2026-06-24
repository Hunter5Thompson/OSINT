import { useState, useEffect } from "react";
import type { Aircraft } from "../types";
import { getFlights } from "../services/api";

const POLL_INTERVAL = 15_000;

export function useFlights(enabled: boolean) {
  const [flights, setFlights] = useState<Aircraft[]>([]);
  const [loading, setLoading] = useState(false);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);

  useEffect(() => {
    if (!enabled) {
      setFlights([]);
      setLoading(false);
      return;
    }

    let cancelled = false;
    let sequence = 0;

    const fetchData = async () => {
      const requestId = ++sequence;
      setLoading(true);
      try {
        const data = await getFlights();
        if (cancelled || requestId !== sequence) return;
        setFlights(data);
        setLastUpdate(new Date());
      } catch {
        // keep stale data on error
      } finally {
        if (!cancelled && requestId === sequence) setLoading(false);
      }
    };

    void fetchData();
    const timer = setInterval(() => void fetchData(), POLL_INTERVAL);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [enabled]);

  return { flights, loading, lastUpdate };
}
