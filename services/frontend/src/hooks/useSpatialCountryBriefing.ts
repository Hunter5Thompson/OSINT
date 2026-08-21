import { useCallback, useEffect, useRef, useState } from "react";

import { streamSpatialCountryBriefing } from "../services/api";
import type { SpatialQueryRef } from "../spatial/contracts";
import type { IntelAnalysis } from "../types";

interface BriefingState {
  readonly loading: boolean;
  readonly currentAgent: string | null;
  readonly result: IntelAnalysis | null;
  readonly error: string | null;
}

interface TaggedBriefingState extends BriefingState {
  readonly queryIdentity: string | null;
}

const INITIAL: BriefingState = {
  loading: false,
  currentAgent: null,
  result: null,
  error: null,
};

function queryIdentity(query: SpatialQueryRef | null): string | null {
  return query === null ? null : `${query.scopeKey}\u0000${query.catalogRevision}`;
}

export function useSpatialCountryBriefing(query: SpatialQueryRef | null) {
  const identity = queryIdentity(query);
  const activeIdentityRef = useRef(identity);
  activeIdentityRef.current = identity;
  const [state, setState] = useState<TaggedBriefingState>({
    ...INITIAL,
    queryIdentity: null,
  });
  const controllerRef = useRef<AbortController | null>(null);
  const generationRef = useRef(0);

  const reset = useCallback(() => {
    controllerRef.current?.abort();
    controllerRef.current = null;
    generationRef.current += 1;
    setState({ ...INITIAL, queryIdentity: activeIdentityRef.current });
  }, []);

  const run = useCallback(() => {
    if (query === null || identity === null) return () => undefined;
    controllerRef.current?.abort();
    controllerRef.current = null;
    const generation = ++generationRef.current;
    const isCurrent = () => (
      generationRef.current === generation
      && activeIdentityRef.current === identity
      && !controllerRef.current?.signal.aborted
    );
    setState({ ...INITIAL, loading: true, queryIdentity: identity });
    const controller = streamSpatialCountryBriefing(
      query,
      (status) => {
        if (isCurrent()) {
          setState((previous) => ({ ...previous, currentAgent: status.agent }));
        }
      },
      (analysis) => {
        const application = analysis.spatial_application;
        if (
          application?.scope.scope_key !== query.scopeKey
          || application.scope.catalog_revision !== query.catalogRevision
        ) {
          if (isCurrent()) {
            setState((previous) => ({
              ...previous,
              loading: false,
              currentAgent: null,
              result: null,
              error: "briefing scope echo does not match the request",
            }));
          }
        } else if (isCurrent()) {
          setState((previous) => ({ ...previous, result: analysis }));
        }
      },
      (error) => {
        if (isCurrent()) {
          setState((previous) => ({
            ...previous,
            loading: false,
            currentAgent: null,
            error,
          }));
        }
      },
      () => {
        if (isCurrent()) {
          setState((previous) => ({
            ...previous,
            loading: false,
            currentAgent: null,
          }));
        }
      },
    );
    controllerRef.current = controller;
    return () => controller.abort();
  }, [identity, query]);

  useEffect(() => {
    controllerRef.current?.abort();
    controllerRef.current = null;
    generationRef.current += 1;
    setState({ ...INITIAL, queryIdentity: identity });
    return () => {
      controllerRef.current?.abort();
      controllerRef.current = null;
      generationRef.current += 1;
    };
  }, [identity]);

  const visible = state.queryIdentity === identity ? state : {
    ...INITIAL,
    queryIdentity: identity,
  };
  return {
    loading: visible.loading,
    currentAgent: visible.currentAgent,
    result: visible.result,
    error: visible.error,
    run,
    reset,
  };
}
