import { useState, useEffect, useRef, useCallback } from "react";
import type { SubmarineCable, LandingPoint } from "../types";
import { getCables } from "../services/api";

const POLL_INTERVAL = 3_600_000; // 1 hour — cable data rarely changes

export function useCables(enabled: boolean) {
  const [cables, setCables] = useState<SubmarineCable[]>([]);
  const [landingPoints, setLandingPoints] = useState<LandingPoint[]>([]);
  const [source, setSource] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchData = useCallback(async () => {
    if (!enabled) return;
    setLoading(true);
    try {
      const data = await getCables();
      setCables(data.cables);
      setLandingPoints(data.landing_points);
      setSource(data.source);
      setLastUpdate(new Date());
    } catch {
      // keep stale data on error
    } finally {
      setLoading(false);
    }
  }, [enabled]);

  useEffect(() => {
    if (!enabled) {
      setCables([]);
      setLandingPoints([]);
      setSource(null);
      return;
    }

    void fetchData();
    timerRef.current = setInterval(() => void fetchData(), POLL_INTERVAL);
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [enabled, fetchData]);

  return { cables, landingPoints, source, loading, lastUpdate };
}
