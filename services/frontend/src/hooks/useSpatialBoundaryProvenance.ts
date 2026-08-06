import { useEffect, useRef, useState } from "react";

import type {
  SpatialBoundaryProvenance,
  SpatialBoundaryProvenanceLoader,
} from "../spatial/catalog";
import type { SpatialQueryRef } from "../spatial/contracts";

export type SpatialBoundaryProvenanceState =
  | { readonly status: "idle"; readonly data: null; readonly error: null }
  | { readonly status: "loading"; readonly data: null; readonly error: null }
  | {
      readonly status: "ready";
      readonly data: SpatialBoundaryProvenance;
      readonly error: null;
    }
  | { readonly status: "error"; readonly data: null; readonly error: string };

const IDLE: SpatialBoundaryProvenanceState = {
  status: "idle",
  data: null,
  error: null,
};

export function useSpatialBoundaryProvenance(
  loader: SpatialBoundaryProvenanceLoader | null,
  query: Pick<SpatialQueryRef, "catalogRevision" | "boundaryPolicy"> | null,
): SpatialBoundaryProvenanceState {
  const [state, setState] = useState<SpatialBoundaryProvenanceState>(IDLE);
  const generationRef = useRef(0);
  const catalogRevision = query?.catalogRevision ?? null;
  const boundaryPolicy = query?.boundaryPolicy ?? null;

  useEffect(() => {
    const generation = ++generationRef.current;
    if (loader === null || catalogRevision === null || boundaryPolicy === null) {
      setState(IDLE);
      return;
    }
    const controller = new AbortController();
    setState({ status: "loading", data: null, error: null });
    loader.loadBoundaryProvenance(
      { catalogRevision, boundaryPolicy },
      controller.signal,
    ).then((data) => {
      if (!controller.signal.aborted && generationRef.current === generation) {
        setState({ status: "ready", data, error: null });
      }
    }).catch((error: unknown) => {
      if (!controller.signal.aborted && generationRef.current === generation) {
        setState({ status: "error", data: null, error: String(error) });
      }
    });
    return () => controller.abort();
  }, [boundaryPolicy, catalogRevision, loader]);

  return state;
}
