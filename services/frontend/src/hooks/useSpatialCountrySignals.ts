import { useEffect, useRef, useState } from "react";

import { getSpatialCountryAlmanacSignals } from "../services/api";
import type { SpatialQueryRef } from "../spatial/contracts";
import type { SpatialAlmanacSignalResponse } from "../types/almanac";

export type SpatialCountrySignalsState =
  | { readonly status: "idle"; readonly data: null; readonly error: null }
  | { readonly status: "loading"; readonly data: null; readonly error: null }
  | { readonly status: "ready"; readonly data: SpatialAlmanacSignalResponse; readonly error: null }
  | { readonly status: "error"; readonly data: null; readonly error: string };

const IDLE: SpatialCountrySignalsState = { status: "idle", data: null, error: null };
const LOADING: SpatialCountrySignalsState = {
  status: "loading",
  data: null,
  error: null,
};

interface TaggedState {
  readonly queryIdentity: string | null;
  readonly value: SpatialCountrySignalsState;
}

function queryIdentity(query: SpatialQueryRef | null): string | null {
  return query === null ? null : `${query.scopeKey}\u0000${query.catalogRevision}`;
}

export function useSpatialCountrySignals(
  query: SpatialQueryRef | null,
): SpatialCountrySignalsState {
  const scopeKey = query?.scopeKey ?? null;
  const catalogRevision = query?.catalogRevision ?? null;
  const identity = queryIdentity(query);
  const activeIdentityRef = useRef(identity);
  activeIdentityRef.current = identity;
  const [tagged, setTagged] = useState<TaggedState>({
    queryIdentity: null,
    value: IDLE,
  });
  const generationRef = useRef(0);

  useEffect(() => {
    const generation = ++generationRef.current;
    if (scopeKey === null || catalogRevision === null || identity === null) {
      setTagged({ queryIdentity: null, value: IDLE });
      return;
    }
    const controller = new AbortController();
    setTagged({ queryIdentity: identity, value: LOADING });
    getSpatialCountryAlmanacSignals(
      { scopeKey, catalogRevision },
      5,
      controller.signal,
    )
      .then((data) => {
        if (data.scope_key !== scopeKey || data.catalog_revision !== catalogRevision) {
          throw new Error("signals scope echo does not match the request");
        }
        if (
          !controller.signal.aborted
          && generationRef.current === generation
          && activeIdentityRef.current === identity
        ) {
          setTagged({
            queryIdentity: identity,
            value: { status: "ready", data, error: null },
          });
        }
      })
      .catch((error: unknown) => {
        if (
          !controller.signal.aborted
          && generationRef.current === generation
          && activeIdentityRef.current === identity
        ) {
          setTagged({
            queryIdentity: identity,
            value: { status: "error", data: null, error: String(error) },
          });
        }
      });
    return () => controller.abort();
  }, [catalogRevision, identity, scopeKey]);

  if (tagged.queryIdentity === identity) return tagged.value;
  return identity === null ? IDLE : LOADING;
}
