import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as api from "../../services/api";
import {
  parseCatalogRevision,
  parseScopeKeyCandidate,
  type SpatialQueryRef,
} from "../../spatial/contracts";
import type { HistogramResponse, SpatialApplicationV1, TimeHistogramQuery } from "../../types";
import { useTimeHistogram } from "../useTimeHistogram";

afterEach(() => vi.restoreAllMocks());

function scope(scopeKey: string): SpatialQueryRef {
  return {
    schemaVersion: 1,
    scopeKey: parseScopeKeyCandidate(scopeKey),
    catalogRevision: parseCatalogRevision("spatial-v1-123456789abc"),
    boundaryPolicy: "natural-earth-admin-v1",
  };
}

const UKRAINE = scope("country:UKR");
const POLAND = scope("country:POL");

function application(spatialScope: SpatialQueryRef): SpatialApplicationV1 {
  return {
    schema_version: 1,
    requested_scope_key: spatialScope.scopeKey,
    catalog_revision: spatialScope.catalogRevision,
    derivation_revision: "spatial-derive-v1-123456789abc",
    boundary_policy: spatialScope.boundaryPolicy,
    relation: "occurs-in",
    mode: "bbox_approximate",
    completeness: "partial",
    included_count: 1,
    excluded_unlocated_count: 0,
    excluded_conflict_count: 0,
    excluded_stale_revision_count: 0,
  };
}

function response(spatialScope: SpatialQueryRef, label: string): HistogramResponse {
  return {
    t_start: "a",
    t_end: "b",
    bucket_ms: 1,
    buckets: [{ ts: label, count: 1, dominant_category: "civil", by_category: {}, by_severity: {} }],
    notables: [],
    geo_events: [],
    total_count: 1,
    geo_located_count: 0,
    geo_truncated: false,
    spatial_application: application(spatialScope),
  };
}

function query(spatialScope: SpatialQueryRef): TimeHistogramQuery {
  return { tStart: "a", tEnd: "b", buckets: 120, spatialScope };
}

function deferred<T>(): { readonly promise: Promise<T>; readonly resolve: (value: T) => void } {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

describe("useTimeHistogram", () => {
  it("fetches an enabled scoped histogram", async () => {
    const spy = vi.spyOn(api, "getTimeHistogram").mockResolvedValue(response(UKRAINE, "ua"));
    const { result } = renderHook(() => useTimeHistogram(true, query(UKRAINE), 0, 8));

    await waitFor(() => expect(result.current.data?.buckets[0]?.ts).toBe("ua"));
    expect(spy).toHaveBeenCalledTimes(1);
  });

  it("hides the previous histogram on the first render of a new scope", async () => {
    const pending = deferred<HistogramResponse>();
    vi.spyOn(api, "getTimeHistogram")
      .mockResolvedValueOnce(response(UKRAINE, "ua"))
      .mockReturnValueOnce(pending.promise);
    const { result, rerender } = renderHook(
      ({ spatialScope, generation }) =>
        useTimeHistogram(true, query(spatialScope), 0, generation),
      { initialProps: { spatialScope: UKRAINE, generation: 1 } },
    );
    await waitFor(() => expect(result.current.data?.buckets[0]?.ts).toBe("ua"));

    rerender({ spatialScope: POLAND, generation: 2 });

    expect(result.current).toMatchObject({ data: null, loading: true, error: null });
  });

  it("uses sequence and token guards against a late prior response", async () => {
    const pendingUkraine = deferred<HistogramResponse>();
    const pendingPoland = deferred<HistogramResponse>();
    vi.spyOn(api, "getTimeHistogram")
      .mockReturnValueOnce(pendingUkraine.promise)
      .mockReturnValueOnce(pendingPoland.promise);
    const { result, rerender } = renderHook(
      ({ spatialScope, generation }) =>
        useTimeHistogram(true, query(spatialScope), 0, generation),
      { initialProps: { spatialScope: UKRAINE, generation: 1 } },
    );

    rerender({ spatialScope: POLAND, generation: 2 });
    await act(async () => pendingPoland.resolve(response(POLAND, "pl")));
    await waitFor(() => expect(result.current.data?.buckets[0]?.ts).toBe("pl"));
    await act(async () => pendingUkraine.resolve(response(UKRAINE, "ua-late")));

    expect(result.current.data?.buckets[0]?.ts).toBe("pl");
  });

  it("reports echo mismatches and backend failures explicitly", async () => {
    const spy = vi.spyOn(api, "getTimeHistogram");
    spy.mockResolvedValueOnce(response(POLAND, "wrong"));
    const first = renderHook(() => useTimeHistogram(true, query(UKRAINE), 0, 1));
    await waitFor(() => expect(first.result.current.error?.message).toMatch(/scope echo/i));
    first.unmount();

    spy.mockRejectedValueOnce(new Error("histogram unavailable"));
    const second = renderHook(() => useTimeHistogram(true, query(UKRAINE), 0, 2));
    await waitFor(() => expect(second.result.current.error?.message).toBe("histogram unavailable"));
    expect(second.result.current.data).toBeNull();
  });

  it("aborts and never falls back to an unscoped request when disabled", () => {
    let signal: AbortSignal | undefined;
    const spy = vi.spyOn(api, "getTimeHistogram").mockImplementation((_query, requestSignal) => {
      signal = requestSignal;
      return new Promise<HistogramResponse>(() => {});
    });
    const { result, rerender } = renderHook(
      ({ enabled }) => useTimeHistogram(enabled, query(UKRAINE), 0, 1),
      { initialProps: { enabled: true } },
    );

    rerender({ enabled: false });

    expect(signal?.aborted).toBe(true);
    expect(result.current).toMatchObject({ data: null, loading: false, error: null });
    expect(spy).toHaveBeenCalledTimes(1);
  });
});
