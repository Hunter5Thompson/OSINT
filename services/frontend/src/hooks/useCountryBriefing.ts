// services/frontend/src/hooks/useCountryBriefing.ts
import { useCallback, useEffect, useRef, useState } from "react";
import type { IntelAnalysis } from "../types";
import { streamCountryBriefing } from "../services/api";

interface State {
  loading: boolean;
  currentAgent: string | null;
  result: IntelAnalysis | null;
  error: string | null;
}

const initial: State = { loading: false, currentAgent: null, result: null, error: null };

export function useCountryBriefing(countryId: string) {
  const [state, setState] = useState<State>(initial);
  const controllerRef = useRef<AbortController | null>(null);

  const run = useCallback(() => {
    controllerRef.current?.abort(); // abort a previous in-flight stream on re-run
    setState({ ...initial, loading: true });
    const controller = streamCountryBriefing(
      countryId,
      (s) => setState((p) => ({ ...p, currentAgent: s.agent })),
      (a) => setState((p) => ({ ...p, result: a })),
      (e) => setState((p) => ({ ...p, error: e, loading: false })),
      () => setState((p) => ({ ...p, loading: false, currentAgent: null })),
    );
    controllerRef.current = controller;
    return () => controller.abort();
  }, [countryId]);

  const reset = useCallback(() => setState(initial), []);

  useEffect(() => () => controllerRef.current?.abort(), []); // abort on unmount

  return { ...state, run, reset };
}
