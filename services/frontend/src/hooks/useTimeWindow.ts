import { useEffect, useRef, useState } from "react";
import type { TimeWindowQuery, WindowResponse } from "../types";
import { getTimeWindow } from "../services/api";

// Param-driven (refetch on query change), following the reliability pattern:
// AbortController + sequence guard + skip-when-hidden. Optional refreshMs for live.
export function useTimeWindow(
  enabled: boolean,
  query: TimeWindowQuery,
  refreshMs = 0,
) {
  const [data, setData] = useState<WindowResponse | null>(null);
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
        const res = await getTimeWindow(query, ctrl.signal);
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
