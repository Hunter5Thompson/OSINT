import { useState, useEffect, useCallback } from "react";
import type { DatacenterGeoJSON } from "../types";

/**
 * Fetches datacenter GeoJSON from static file.
 * Data is loaded once and cached — datacenters don't change at runtime.
 */
export function useDatacenters(enabled: boolean) {
  const [data, setData] = useState<DatacenterGeoJSON | null>(null);
  const [loading, setLoading] = useState(false);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);

  const fetchData = useCallback(async () => {
    if (!enabled || data) return; // already loaded
    setLoading(true);
    try {
      const res = await fetch("/data/datacenters.geojson");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const geojson = (await res.json()) as DatacenterGeoJSON;
      setData(geojson);
      setLastUpdate(new Date());
    } catch {
      // keep null — datacenters not available
    } finally {
      setLoading(false);
    }
  }, [enabled, data]);

  useEffect(() => {
    if (!enabled) return;
    void fetchData();
  }, [enabled, fetchData]);

  return { datacenters: data, loading, lastUpdate };
}
