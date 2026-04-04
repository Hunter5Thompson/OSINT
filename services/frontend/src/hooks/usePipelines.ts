import { useState, useEffect, useCallback } from "react";
import type { PipelineGeoJSON } from "../types";

/**
 * Fetches pipeline GeoJSON from static file.
 * Data is loaded once and cached — pipelines don't change at runtime.
 */
export function usePipelines(enabled: boolean) {
  const [data, setData] = useState<PipelineGeoJSON | null>(null);
  const [loading, setLoading] = useState(false);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);

  const fetchData = useCallback(async () => {
    if (!enabled || data) return; // already loaded
    setLoading(true);
    try {
      const res = await fetch("/data/pipelines.geojson");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const geojson = (await res.json()) as PipelineGeoJSON;
      setData(geojson);
      setLastUpdate(new Date());
    } catch {
      // keep null — pipelines not available
    } finally {
      setLoading(false);
    }
  }, [enabled, data]);

  useEffect(() => {
    if (!enabled) return;
    void fetchData();
  }, [enabled, fetchData]);

  return { pipelines: data, loading, lastUpdate };
}
