import { useState, useEffect, useRef, useCallback } from "react";
import type { Vessel } from "../types";
import { getVessels } from "../services/api";

const POLL_INTERVAL = 60_000; // 60 seconds — vessel data cached for 60s

export function useVessels(enabled: boolean) {
  const [vessels, setVessels] = useState<Vessel[]>([]);
  const [loading, setLoading] = useState(false);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchData = useCallback(async () => {
    if (!enabled) return;
    setLoading(true);
    try {
      const data = await getVessels();
      setVessels(data);
      setLastUpdate(new Date());
    } catch {
      // keep stale data on error
    } finally {
      setLoading(false);
    }
  }, [enabled]);

  useEffect(() => {
    if (!enabled) {
      setVessels([]);
      return;
    }

    void fetchData();
    timerRef.current = setInterval(() => void fetchData(), POLL_INTERVAL);
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [enabled, fetchData]);

  return { vessels, loading, lastUpdate };
}
