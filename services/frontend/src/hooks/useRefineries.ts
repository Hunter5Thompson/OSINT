import { useState, useEffect, useCallback } from "react";
import type { RefineryGeoJSON } from "../types";

/**
 * Fetches refinery GeoJSON from static file.
 * Data is loaded once and cached — refineries don't change at runtime.
 */
export function useRefineries(enabled: boolean) {
  const [data, setData] = useState<RefineryGeoJSON | null>(null);
  const [loading, setLoading] = useState(false);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);

  const fetchData = useCallback(async () => {
    if (!enabled || data) return; // already loaded
    setLoading(true);
    try {
      const res = await fetch("/data/refineries.geojson");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const geojson = (await res.json()) as RefineryGeoJSON;
      setData(geojson);
      setLastUpdate(new Date());
    } catch {
      // keep null — refineries not available
    } finally {
      setLoading(false);
    }
  }, [enabled, data]);

  useEffect(() => {
    if (!enabled) return;
    void fetchData();
  }, [enabled, fetchData]);

  return { refineries: data, loading, lastUpdate };
}
