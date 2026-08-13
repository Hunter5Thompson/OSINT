import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as api from "../../services/api";
import {
  parseCatalogRevision,
  parseScopeKeyCandidate,
  type SpatialQueryRef,
} from "../../spatial/contracts";
import type { SpatialApplicationV1, TimeWindowQuery, WindowResponse } from "../../types";
import { useTimeWindow } from "../useTimeWindow";

afterEach(() => vi.restoreAllMocks());

const REVISION = "spatial-v1-123456789abc";

function scope(scopeKey: string): SpatialQueryRef {
  return {
    schemaVersion: 1,
    scopeKey: parseScopeKeyCandidate(scopeKey),
    catalogRevision: parseCatalogRevision(REVISION),
    boundaryPolicy: "natural-earth-admin-v1",
  };
}

const UKRAINE = scope("country:UKR");
const POLAND = scope("country:POL");

function application(
  spatialScope: SpatialQueryRef | undefined,
  relation: SpatialApplicationV1["relation"] = "intersects",
): SpatialApplicationV1 {
  return {
    schema_version: 1,
    requested_scope_key: spatialScope?.scopeKey ?? null,
    catalog_revision: spatialScope?.catalogRevision ?? null,
    derivation_revision: spatialScope ? "spatial-derive-v1-123456789abc" : null,
    boundary_policy: spatialScope?.boundaryPolicy ?? null,
    relation,
    mode: spatialScope ? "bbox_approximate" : "global",
    completeness: spatialScope ? "partial" : "complete",
    included_count: 1,
    excluded_unlocated_count: 0,
    excluded_outside_count: 0,
    excluded_conflict_count: 0,
    excluded_stale_revision_count: 0,
    excluded_unsupported_count: 0,
  };
}

function response(spatialScope: SpatialQueryRef | undefined, id: string): WindowResponse {
  return {
    domain: "movements",
    tier: "fine",
    t_start: "a",
    t_end: "b",
    bbox: null,
    samples: [{ kind: "track", id, icao24: id, points: [] }],
    total_count: 1,
    truncated: false,
    spatial_application: application(spatialScope),
  };
}

function deferred<T>(): {
  readonly promise: Promise<T>;
  readonly resolve: (value: T) => void;
  readonly reject: (reason: unknown) => void;
} {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function query(spatialScope: SpatialQueryRef, tEnd = "b"): TimeWindowQuery {
  return {
    tStart: "a",
    tEnd,
    domain: "movements",
    tier: "fine",
    movementKind: "mil_aircraft",
    spatialScope,
  };
}

describe("useTimeWindow", () => {
  it("fetches an enabled scoped request", async () => {
    const spy = vi.spyOn(api, "getTimeWindow").mockResolvedValue(response(UKRAINE, "ua"));
    const { result } = renderHook(() => useTimeWindow(true, query(UKRAINE), 0, 7));

    await waitFor(() => expect(result.current.data?.samples[0]?.id).toBe("ua"));
    expect(result.current.error).toBeNull();
    expect(spy).toHaveBeenCalledWith(query(UKRAINE), expect.any(AbortSignal));
  });

  it("does not fetch when disabled", () => {
    const spy = vi.spyOn(api, "getTimeWindow").mockResolvedValue(response(undefined, "global"));
    const { result } = renderHook(() => useTimeWindow(false, { tStart: "a", tEnd: "b" }));

    expect(spy).not.toHaveBeenCalled();
    expect(result.current).toMatchObject({ data: null, loading: false, error: null });
  });

  it("defers while hidden and retries immediately when the tab becomes visible", async () => {
    const hidden = vi.spyOn(document, "hidden", "get").mockReturnValue(true);
    const spy = vi.spyOn(api, "getTimeWindow").mockResolvedValue(response(UKRAINE, "ua"));
    const { result } = renderHook(() => useTimeWindow(true, query(UKRAINE), 0, 7));

    expect(spy).not.toHaveBeenCalled();
    expect(result.current).toMatchObject({ data: null, loading: true, error: null });

    hidden.mockReturnValue(false);
    act(() => document.dispatchEvent(new Event("visibilitychange")));

    await waitFor(() => expect(result.current.data?.samples[0]?.id).toBe("ua"));
    expect(spy).toHaveBeenCalledTimes(1);
  });

  it("aborts the in-flight request on unmount", () => {
    let signal: AbortSignal | undefined;
    vi.spyOn(api, "getTimeWindow").mockImplementation((_query, requestSignal) => {
      signal = requestSignal;
      return new Promise<WindowResponse>(() => {});
    });
    const { unmount } = renderHook(() => useTimeWindow(true, query(UKRAINE), 0, 1));

    expect(signal?.aborted).toBe(false);
    unmount();
    expect(signal?.aborted).toBe(true);
  });

  it("hides A synchronously on the first B render and exposes a loading state", async () => {
    const pendingPoland = deferred<WindowResponse>();
    vi.spyOn(api, "getTimeWindow")
      .mockResolvedValueOnce(response(UKRAINE, "ua"))
      .mockReturnValueOnce(pendingPoland.promise);
    const { result, rerender } = renderHook(
      ({ spatialScope, generation }) =>
        useTimeWindow(true, query(spatialScope), 0, generation),
      { initialProps: { spatialScope: UKRAINE, generation: 11 } },
    );
    await waitFor(() => expect(result.current.data?.samples[0]?.id).toBe("ua"));

    rerender({ spatialScope: POLAND, generation: 12 });

    expect(result.current).toMatchObject({ data: null, loading: true, error: null });
  });

  it("keeps same-scope data visible while a new time range refreshes", async () => {
    const refresh = deferred<WindowResponse>();
    vi.spyOn(api, "getTimeWindow")
      .mockResolvedValueOnce(response(UKRAINE, "old-range"))
      .mockReturnValueOnce(refresh.promise);
    const { result, rerender } = renderHook(
      ({ tEnd }) => useTimeWindow(true, query(UKRAINE, tEnd), 0, 4),
      { initialProps: { tEnd: "b" } },
    );
    await waitFor(() => expect(result.current.data?.samples[0]?.id).toBe("old-range"));

    rerender({ tEnd: "c" });

    expect(result.current.data?.samples[0]?.id).toBe("old-range");
    expect(result.current.loading).toBe(true);
  });

  it("ignores a late A response after B has committed", async () => {
    const pendingUkraine = deferred<WindowResponse>();
    const pendingPoland = deferred<WindowResponse>();
    vi.spyOn(api, "getTimeWindow")
      .mockReturnValueOnce(pendingUkraine.promise)
      .mockReturnValueOnce(pendingPoland.promise);
    const { result, rerender } = renderHook(
      ({ spatialScope, generation }) =>
        useTimeWindow(true, query(spatialScope), 0, generation),
      { initialProps: { spatialScope: UKRAINE, generation: 1 } },
    );

    rerender({ spatialScope: POLAND, generation: 2 });
    await act(async () => pendingPoland.resolve(response(POLAND, "pl")));
    await waitFor(() => expect(result.current.data?.samples[0]?.id).toBe("pl"));
    await act(async () => pendingUkraine.resolve(response(UKRAINE, "ua-late")));

    expect(result.current.data?.samples[0]?.id).toBe("pl");
  });

  it("rejects a response whose echoed scope token differs", async () => {
    vi.spyOn(api, "getTimeWindow").mockResolvedValue(response(POLAND, "wrong"));
    const { result } = renderHook(() => useTimeWindow(true, query(UKRAINE), 0, 3));

    await waitFor(() => expect(result.current.error?.message).toMatch(/scope echo/i));
    expect(result.current.data).toBeNull();
    expect(result.current.loading).toBe(false);
  });

  it("surfaces backend failures instead of swallowing them", async () => {
    vi.spyOn(api, "getTimeWindow").mockRejectedValue(new Error("backend unavailable"));
    const { result } = renderHook(() => useTimeWindow(true, query(UKRAINE), 0, 3));

    await waitFor(() => expect(result.current.error?.message).toBe("backend unavailable"));
    expect(result.current.data).toBeNull();
  });

  it("does not issue a legacy fallback request while the next scope is unavailable", async () => {
    const spy = vi.spyOn(api, "getTimeWindow").mockResolvedValue(response(UKRAINE, "ua"));
    const { result, rerender } = renderHook(
      ({ enabled, spatialScope }) =>
        useTimeWindow(
          enabled,
          spatialScope ? query(spatialScope) : { tStart: "a", tEnd: "b" },
          0,
          5,
        ),
      { initialProps: { enabled: true, spatialScope: UKRAINE as SpatialQueryRef | null } },
    );
    await waitFor(() => expect(result.current.data).not.toBeNull());

    rerender({ enabled: false, spatialScope: null });

    expect(result.current.data).toBeNull();
    expect(spy).toHaveBeenCalledTimes(1);
  });
});
