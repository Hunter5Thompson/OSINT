import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { SpatialQueryRef } from "../spatial/contracts";
import type { SpatialApplicationV1 } from "../types";

interface ScopeAwareQuery {
  readonly spatialScope?: SpatialQueryRef;
}

interface ScopedTimelineResponse {
  readonly spatial_application: SpatialApplicationV1;
}

interface ScopedDataEnvelope<T> {
  readonly scopeTokenKey: string;
  readonly scopeGeneration: number;
  readonly requestKey: string;
  readonly data: T;
}

interface RequestStatus {
  readonly activeRequestKey: string;
  readonly loading: boolean;
  readonly error: Error | null;
}

export interface ScopedTimelineRequestResult<T> {
  readonly data: T | null;
  readonly loading: boolean;
  readonly error: Error | null;
}

type TimelineFetcher<Q, T> = (query: Q, signal?: AbortSignal) => Promise<T>;

export function timelineScopeTokenKey(spatialScope: SpatialQueryRef | undefined): string {
  return spatialScope === undefined
    ? "legacy-global"
    : JSON.stringify([spatialScope.scopeKey, spatialScope.catalogRevision]);
}

function responseEchoMatches(
  spatialScope: SpatialQueryRef | undefined,
  application: SpatialApplicationV1,
): boolean {
  if (spatialScope === undefined) {
    return application.requested_scope_key === null && application.catalog_revision === null;
  }
  return application.requested_scope_key === spatialScope.scopeKey
    && application.catalog_revision === spatialScope.catalogRevision;
}

function asError(reason: unknown): Error {
  return reason instanceof Error ? reason : new Error(String(reason));
}

function isAbort(reason: unknown): boolean {
  return reason instanceof DOMException
    ? reason.name === "AbortError"
    : reason instanceof Error && reason.name === "AbortError";
}

export function useScopedTimelineRequest<
  Q extends ScopeAwareQuery,
  T extends ScopedTimelineResponse,
>(
  enabled: boolean,
  query: Q,
  fetcher: TimelineFetcher<Q, T>,
  refreshMs: number,
  scopeGeneration: number,
): ScopedTimelineRequestResult<T> {
  const [envelope, setEnvelope] = useState<ScopedDataEnvelope<T> | null>(null);
  const [status, setStatus] = useState<RequestStatus | null>(null);
  const sequenceRef = useRef(0);
  const queryRef = useRef(query);

  const scopeTokenKey = timelineScopeTokenKey(query.spatialScope);
  const requestKey = JSON.stringify(query);
  const activeRequestKey = JSON.stringify([scopeTokenKey, scopeGeneration, requestKey]);
  const activeRequestRef = useRef<string | null>(null);

  // Publish render inputs only after commit. A speculative concurrent render must not
  // revoke a request belonging to the still-committed tree.
  useLayoutEffect(() => {
    queryRef.current = query;
    activeRequestRef.current = enabled ? activeRequestKey : null;
  }, [activeRequestKey, enabled, query]);

  useEffect(() => {
    if (!enabled) {
      sequenceRef.current += 1;
      setEnvelope(null);
      setStatus(null);
      return;
    }

    const controller = new AbortController();
    const requestQuery = queryRef.current;
    const expectedScope = requestQuery.spatialScope;

    const isCurrent = (sequence: number): boolean =>
      !controller.signal.aborted
      && sequence === sequenceRef.current
      && activeRequestRef.current === activeRequestKey;

    const run = async (): Promise<void> => {
      const sequence = ++sequenceRef.current;
      if (typeof document !== "undefined" && document.hidden) {
        if (isCurrent(sequence)) {
          setStatus({ activeRequestKey, loading: false, error: null });
        }
        return;
      }

      setStatus({ activeRequestKey, loading: true, error: null });
      try {
        const response = await fetcher(requestQuery, controller.signal);
        if (!responseEchoMatches(expectedScope, response.spatial_application)) {
          throw new Error("timeline scope echo does not match the request");
        }
        if (!isCurrent(sequence)) return;
        setEnvelope({
          scopeTokenKey,
          scopeGeneration,
          requestKey,
          data: response,
        });
        setStatus({ activeRequestKey, loading: false, error: null });
      } catch (reason: unknown) {
        if (controller.signal.aborted || isAbort(reason) || !isCurrent(sequence)) return;
        setStatus({ activeRequestKey, loading: false, error: asError(reason) });
      }
    };

    void run();
    const timer = refreshMs > 0 ? window.setInterval(() => void run(), refreshMs) : null;
    return () => {
      controller.abort();
      sequenceRef.current += 1;
      if (timer !== null) window.clearInterval(timer);
    };
  }, [activeRequestKey, enabled, fetcher, refreshMs, requestKey, scopeGeneration, scopeTokenKey]);

  if (!enabled) return { data: null, loading: false, error: null };

  const visibleData = envelope?.scopeTokenKey === scopeTokenKey
    && envelope.scopeGeneration === scopeGeneration
    ? envelope.data
    : null;
  const visibleStatus = status?.activeRequestKey === activeRequestKey ? status : null;
  return {
    data: visibleData,
    loading: visibleStatus?.loading ?? true,
    error: visibleStatus?.error ?? null,
  };
}
