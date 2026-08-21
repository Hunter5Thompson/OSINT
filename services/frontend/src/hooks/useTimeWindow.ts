import type { TimeWindowQuery, WindowResponse } from "../types";
import { getTimeWindow } from "../services/api";
import { useScopedTimelineRequest } from "./useScopedTimelineRequest";

// Param-driven (refetch on query change), following the reliability pattern:
// AbortController + sequence guard + skip-when-hidden. Optional refreshMs for live.
export function useTimeWindow(
  enabled: boolean,
  query: TimeWindowQuery,
  refreshMs = 0,
  scopeGeneration = 0,
): { readonly data: WindowResponse | null; readonly loading: boolean; readonly error: Error | null } {
  return useScopedTimelineRequest(
    enabled,
    query,
    getTimeWindow,
    refreshMs,
    scopeGeneration,
  );
}
