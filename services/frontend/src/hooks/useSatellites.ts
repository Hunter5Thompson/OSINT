import { useState, useEffect, useMemo } from "react";
import type { OrbitSnapshot, OrbitSatellite } from "../types/satelliteOrbit";
import { getSatelliteOrbitSnapshot } from "../services/api";

const EMPTY: OrbitSatellite[] = [];
const POLL_INTERVAL = 3_600_000;

export function useSatellites(enabled: boolean) {
  const [snapshot, setSnapshot] = useState<OrbitSnapshot | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!enabled) {
      setSnapshot(null);
      setLoading(false);
      setError(null);
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
        const data = await getSatelliteOrbitSnapshot(currentController.signal);
        if (!disposed && request === sequence) {
          setSnapshot(data);
          setError(null);
        }
      } catch (failure: unknown) {
        if (!disposed && request === sequence) {
          setError(failure instanceof Error ? failure.message : "Satellite snapshot unavailable");
        }
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

  const lastUpdate = useMemo(() => snapshot ? new Date(snapshot.fetched_at) : null, [snapshot]);
  return { satellites: snapshot?.satellites ?? EMPTY, snapshot, loading, error, lastUpdate };
}
