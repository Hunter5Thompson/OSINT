import type { HistogramResponse, TimeHistogramQuery } from "../types";
import { getTimeHistogram } from "../services/api";
import { useScopedTimelineRequest } from "./useScopedTimelineRequest";

// Param-driven (refetch on query change): AbortController + sequence guard +
// skip-when-hidden, mirroring useTimeWindow. Optional refreshMs for the rolling window.
export function useTimeHistogram(
  enabled: boolean,
  query: TimeHistogramQuery,
  refreshMs = 0,
  scopeGeneration = 0,
): { readonly data: HistogramResponse | null; readonly loading: boolean; readonly error: Error | null } {
  return useScopedTimelineRequest(
    enabled,
    query,
    getTimeHistogram,
    refreshMs,
    scopeGeneration,
  );
}
