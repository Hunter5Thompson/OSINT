import { useState, useEffect } from "react";
import type { SubmarineCable, LandingPoint } from "../types";
import { getCables } from "../services/api";

const POLL_INTERVAL = 3_600_000; // 1 hour — cable data rarely changes

export function useCables(enabled: boolean) {
  const [cables, setCables] = useState<SubmarineCable[]>([]);
  const [landingPoints, setLandingPoints] = useState<LandingPoint[]>([]);
  const [source, setSource] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);
  useEffect(() => {
    if (!enabled) {
      setCables([]);
      setLandingPoints([]);
      setSource(null);
      setLoading(false);
      return;
    }
    let disposed = false;
    let sequence = 0;
    let controller: AbortController | null = null;
    const fetchData = async () => {
      const request = ++sequence;
      controller?.abort();
      const currentController = new AbortController();
      controller = currentController;
      setLoading(true);
      try {
        const data = await getCables(currentController.signal);
        if (disposed || request !== sequence) return;
        setCables(data.cables);
        setLandingPoints(data.landing_points);
        setSource(data.source);
        setLastUpdate(new Date());
      } catch {
        // Keep the last successful dataset on error.
      } finally {
        if (!disposed && request === sequence) setLoading(false);
      }
    };
    void fetchData();
    const timer = setInterval(() => void fetchData(), POLL_INTERVAL);
    return () => {
      disposed = true;
      ++sequence;
      controller?.abort();
      clearInterval(timer);
    };
  }, [enabled]);

  return { cables, landingPoints, source, loading, lastUpdate };
}
