import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  parseCatalogRevision,
  type SpatialQueryRef,
} from "../../spatial/contracts";
import type {
  SpatialBoundaryProvenance,
  SpatialBoundaryProvenanceLoader,
} from "../../spatial/catalog";
import { useSpatialBoundaryProvenance } from "../useSpatialBoundaryProvenance";

function deferred<T>() {
  let resolvePromise: (value: T) => void = () => undefined;
  const promise = new Promise<T>((resolve) => {
    resolvePromise = resolve;
  });
  return { promise, resolve: resolvePromise };
}

function query(revision: string): Pick<SpatialQueryRef, "catalogRevision" | "boundaryPolicy"> {
  return {
    catalogRevision: parseCatalogRevision(revision),
    boundaryPolicy: "odin-reference-v1",
  };
}

function provenance(revision: string): SpatialBoundaryProvenance {
  return {
    boundaryPolicy: "odin-reference-v1",
    catalogRevision: parseCatalogRevision(revision),
    representationNote: `Representation ${revision}`,
    sources: [{
      sourceId: "natural-earth-admin0",
      release: "5.1.2",
      licenseId: "public-domain",
      text: "Natural Earth",
    }],
  };
}

describe("useSpatialBoundaryProvenance", () => {
  it("ignores a late metadata response from a previous committed revision", async () => {
    const first = deferred<SpatialBoundaryProvenance>();
    const second = deferred<SpatialBoundaryProvenance>();
    const loader: SpatialBoundaryProvenanceLoader = {
      loadBoundaryProvenance: vi.fn()
        .mockImplementationOnce(() => first.promise)
        .mockImplementationOnce(() => second.promise),
    };
    const revisionA = "spatial-v1-fe9828dcda05";
    const revisionB = "spatial-v1-001122334455";
    const { result, rerender } = renderHook(
      ({ token }) => useSpatialBoundaryProvenance(loader, token),
      { initialProps: { token: query(revisionA) } },
    );
    await waitFor(() => expect(loader.loadBoundaryProvenance).toHaveBeenCalledTimes(1));

    rerender({ token: query(revisionB) });
    await waitFor(() => expect(loader.loadBoundaryProvenance).toHaveBeenCalledTimes(2));
    const firstSignal = vi.mocked(loader.loadBoundaryProvenance).mock.calls[0]?.[1];
    expect(firstSignal?.aborted).toBe(true);

    await act(async () => first.resolve(provenance(revisionA)));
    expect(result.current.status).toBe("loading");

    await act(async () => second.resolve(provenance(revisionB)));
    await waitFor(() => expect(result.current.status).toBe("ready"));
    expect(result.current.data?.catalogRevision).toBe(revisionB);
  });

  it("does not load metadata without a committed token", () => {
    const loader: SpatialBoundaryProvenanceLoader = {
      loadBoundaryProvenance: vi.fn(),
    };
    const { result } = renderHook(() => useSpatialBoundaryProvenance(loader, null));

    expect(result.current.status).toBe("idle");
    expect(loader.loadBoundaryProvenance).not.toHaveBeenCalled();
  });
});
