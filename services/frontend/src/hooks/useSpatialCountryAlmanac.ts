import { useEffect, useRef, useState } from "react";

import { getSpatialCountryAlmanac } from "../services/api";
import type { SpatialQueryRef } from "../spatial/contracts";
import type { SpatialCountryAlmanac } from "../types/almanac";

export type SpatialCountryAlmanacState =
  | { readonly status: "idle"; readonly data: null; readonly error: null }
  | { readonly status: "loading"; readonly data: null; readonly error: null }
  | { readonly status: "ready"; readonly data: SpatialCountryAlmanac; readonly error: null }
  | { readonly status: "error"; readonly data: null; readonly error: string };

const IDLE: SpatialCountryAlmanacState = {
  status: "idle",
  data: null,
  error: null,
};

const LOADING: SpatialCountryAlmanacState = {
  status: "loading",
  data: null,
  error: null,
};

interface TaggedState {
  readonly queryIdentity: string | null;
  readonly value: SpatialCountryAlmanacState;
}

export function useSpatialCountryAlmanac(
  query: SpatialQueryRef | null,
): SpatialCountryAlmanacState {
  const scopeKey = query?.scopeKey ?? null;
  const catalogRevision = query?.catalogRevision ?? null;
  const identity = scopeKey === null || catalogRevision === null
    ? null
    : `${scopeKey}\u0000${catalogRevision}`;
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
    getSpatialCountryAlmanac({ scopeKey, catalogRevision }, controller.signal)
      .then((data) => {
        if (data.scope_key !== scopeKey || data.catalog_revision !== catalogRevision) {
          throw new Error("almanac scope echo does not match the request");
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
