import { useState, useEffect, useRef, useCallback } from "react";
import type { Aircraft } from "../types";
import { getFlights } from "../services/api";

const POLL_INTERVAL = 10_000;

export function useFlights(enabled: boolean) {
  const [flights, setFlights] = useState<Aircraft[]>([]);
  const [loading, setLoading] = useState(false);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchData = useCallback(async () => {
    if (!enabled) return;
    setLoading(true);
    try {
      const data = await getFlights();
      setFlights(data);
      setLastUpdate(new Date());
    } catch {
      // keep stale data on error
    } finally {
      setLoading(false);
    }
  }, [enabled]);

  useEffect(() => {
    if (!enabled) {
      setFlights([]);
      return;
    }

    void fetchData();
    timerRef.current = setInterval(() => void fetchData(), POLL_INTERVAL);
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [enabled, fetchData]);

  return { flights, loading, lastUpdate };
}
