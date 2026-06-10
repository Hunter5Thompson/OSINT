import { useEffect, useRef, useState } from "react";
import type { HistogramResponse } from "../types";
import { getTimeHistogram } from "../services/api";

interface HistogramQuery {
  tStart: string;
  tEnd: string;
  buckets?: number;
  bbox?: [number, number, number, number];
}

// Param-driven (refetch on query change): AbortController + sequence guard +
// skip-when-hidden, mirroring useTimeWindow. Optional refreshMs for the rolling window.
export function useTimeHistogram(
  enabled: boolean,
  query: HistogramQuery,
  refreshMs = 0,
) {
  const [data, setData] = useState<HistogramResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const seqRef = useRef(0);
  const key = JSON.stringify(query);

  useEffect(() => {
    if (!enabled) {
      setData(null);
      setLoading(false);
      return;
    }
    const seq = ++seqRef.current;
    const ctrl = new AbortController();
    const run = async () => {
      if (typeof document !== "undefined" && document.hidden) return;
      setLoading(true);
      try {
        const res = await getTimeHistogram(query, ctrl.signal);
        if (seq === seqRef.current) setData(res);
      } catch {
        // keep stale data; aborts are expected on param change/unmount
      } finally {
        if (seq === seqRef.current) setLoading(false);
      }
    };
    void run();
    const timer = refreshMs > 0 ? setInterval(() => void run(), refreshMs) : null;
    return () => {
      ctrl.abort();
      if (timer) clearInterval(timer);
    };
    // deps intentionally use `key` (stringified query) instead of `query`
  }, [enabled, key, refreshMs]);

  return { data, loading };
}
