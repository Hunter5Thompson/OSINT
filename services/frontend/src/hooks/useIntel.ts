import { useState, useCallback } from "react";
import type { IntelAnalysis, IntelQuery } from "../types";
import { queryIntel } from "../services/api";

interface IntelState {
  loading: boolean;
  currentAgent: string | null;
  result: IntelAnalysis | null;
  error: string | null;
  history: IntelAnalysis[];
}

export function useIntel() {
  const [state, setState] = useState<IntelState>({
    loading: false,
    currentAgent: null,
    result: null,
    error: null,
    history: [],
  });

  const runQuery = useCallback((query: IntelQuery) => {
    setState((s) => ({
      ...s,
      loading: true,
      currentAgent: null,
      result: null,
      error: null,
    }));

    const controller = queryIntel(
      query,
      (status) => {
        setState((s) => ({ ...s, currentAgent: status.agent }));
      },
      (analysis) => {
        setState((s) => ({
          ...s,
          result: analysis,
          history: [analysis, ...s.history].slice(0, 50),
        }));
      },
      (error) => {
        setState((s) => ({ ...s, error, loading: false }));
      },
      () => {
        setState((s) => ({ ...s, loading: false, currentAgent: null }));
      },
    );

    return () => controller.abort();
  }, []);

  return { ...state, runQuery };
}
