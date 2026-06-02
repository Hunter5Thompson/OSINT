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
  const genRef = useRef(0);

  const run = useCallback(() => {
    controllerRef.current?.abort(); // abort a previous in-flight stream on re-run
    const gen = (genRef.current += 1); // this run's generation
    const fresh = () => gen === genRef.current; // ignore callbacks once superseded/aborted
    setState({ ...initial, loading: true });
    const controller = streamCountryBriefing(
      countryId,
      (s) => {
        if (fresh()) setState((p) => ({ ...p, currentAgent: s.agent }));
      },
      (a) => {
        if (fresh()) setState((p) => ({ ...p, result: a }));
      },
      (e) => {
        if (fresh()) setState((p) => ({ ...p, error: e, loading: false }));
      },
      () => {
        if (fresh()) setState((p) => ({ ...p, loading: false, currentAgent: null }));
      },
    );
    controllerRef.current = controller;
    return () => controller.abort();
  }, [countryId]);

  const reset = useCallback(() => {
    controllerRef.current?.abort(); // stop any in-flight stream...
    genRef.current += 1; // ...and invalidate its pending callbacks
    setState(initial);
  }, []);

  useEffect(
    () => () => {
      // unmount: abort + invalidate
      controllerRef.current?.abort();
      genRef.current += 1;
    },
    [],
  );

  return { ...state, run, reset };
}
