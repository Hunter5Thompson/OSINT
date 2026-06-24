import { useState, useEffect } from "react";
import type { Vessel } from "../types";
import { getVessels } from "../services/api";

const POLL_INTERVAL = 60_000; // 60 seconds — vessel data cached for 60s

export function useVessels(enabled: boolean) {
  const [vessels, setVessels] = useState<Vessel[]>([]);
  const [loading, setLoading] = useState(false);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);

  useEffect(() => {
    if (!enabled) {
      setVessels([]);
      setLoading(false);
      return;
    }

    let cancelled = false;
    let sequence = 0;

    const fetchData = async () => {
      const requestId = ++sequence;
      setLoading(true);
      try {
        const data = await getVessels();
        if (cancelled || requestId !== sequence) return;
        setVessels(data);
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

  return { vessels, loading, lastUpdate };
}
