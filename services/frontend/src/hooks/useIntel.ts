import { useState, useCallback, useEffect, useRef } from "react";
import type { IntelAnalysis, IntelQuery } from "../types";
import { queryIntel } from "../services/api";

interface IntelState {
  reportId: string | null;
  loading: boolean;
  currentAgent: string | null;
  result: IntelAnalysis | null;
  error: string | null;
  history: IntelAnalysis[];
}

export function useIntel() {
  const [state, setState] = useState<IntelState>({
    reportId: null,
    loading: false,
    currentAgent: null,
    result: null,
    error: null,
    history: [],
  });

  const active = useRef<AbortController | null>(null);
  const generation = useRef(0);
  useEffect(() => () => {
    generation.current += 1;
    active.current?.abort();
  }, []);

  const runQuery = useCallback((query: IntelQuery) => {
    active.current?.abort();
    const run = ++generation.current;
    const fresh = () => run === generation.current;
    setState((s) => ({
      ...s,
      reportId: query.report_id ?? null,
      loading: true,
      currentAgent: null,
      result: null,
      error: null,
    }));

    const controller = queryIntel(
      query,
      (status) => {
        if (!fresh()) return;
        setState((s) => ({ ...s, currentAgent: status.agent }));
      },
      (analysis) => {
        if (!fresh()) return;
        setState((s) => ({
          ...s,
          result: analysis,
          history: [analysis, ...s.history].slice(0, 50),
        }));
      },
      (error) => {
        if (!fresh()) return;
        setState((s) => ({ ...s, error, loading: false }));
      },
      () => {
        if (!fresh()) return;
        setState((s) => ({ ...s, loading: false, currentAgent: null }));
      },
    );

    active.current = controller;
    return () => {
      if (!fresh()) return;
      generation.current += 1;
      controller.abort();
      setState((s) => ({ ...s, loading: false, currentAgent: null }));
    };
  }, []);

  return { ...state, runQuery };
}
