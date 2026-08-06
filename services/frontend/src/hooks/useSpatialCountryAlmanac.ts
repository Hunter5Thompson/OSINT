import { useEffect, useRef, useState } from "react";

import { getSpatialCountryAlmanac } from "../services/api";
import type { SpatialQueryRef } from "../spatial/contracts";
import type { CountryAlmanac } from "../types/almanac";

export type SpatialCountryAlmanacState =
  | { readonly status: "idle"; readonly data: null; readonly error: null }
  | { readonly status: "loading"; readonly data: null; readonly error: null }
  | { readonly status: "ready"; readonly data: CountryAlmanac; readonly error: null }
  | { readonly status: "error"; readonly data: null; readonly error: string };

const IDLE: SpatialCountryAlmanacState = {
  status: "idle",
  data: null,
  error: null,
};

export function useSpatialCountryAlmanac(
  query: SpatialQueryRef | null,
): SpatialCountryAlmanacState {
  const [state, setState] = useState<SpatialCountryAlmanacState>(IDLE);
  const generationRef = useRef(0);
  const scopeKey = query?.scopeKey ?? null;
  const catalogRevision = query?.catalogRevision ?? null;

  useEffect(() => {
    const generation = ++generationRef.current;
    if (scopeKey === null || catalogRevision === null) {
      setState(IDLE);
      return;
    }
    const controller = new AbortController();
    setState({ status: "loading", data: null, error: null });
    getSpatialCountryAlmanac({ scopeKey, catalogRevision }, controller.signal)
      .then((data) => {
        if (!controller.signal.aborted && generationRef.current === generation) {
          setState({ status: "ready", data, error: null });
        }
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted && generationRef.current === generation) {
          setState({ status: "error", data: null, error: String(error) });
        }
      });
    return () => controller.abort();
  }, [catalogRevision, scopeKey]);

  return state;
}
