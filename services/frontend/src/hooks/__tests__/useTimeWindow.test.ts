import { afterEach, describe, expect, it, vi } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import * as api from "../../services/api";
import { useTimeWindow } from "../useTimeWindow";

afterEach(() => vi.restoreAllMocks());

const RESP = {
  domain: "movements", tier: "fine", t_start: "a", t_end: "b", bbox: null,
  samples: [{ kind: "track", id: "abc", icao24: "abc", points: [] }],
  total_count: 1, truncated: false,
} as const;

describe("useTimeWindow", () => {
  it("fetches when enabled with params", async () => {
    const spy = vi.spyOn(api, "getTimeWindow").mockResolvedValue(RESP as never);
    const { result } = renderHook(() =>
      useTimeWindow(true, {
        tStart: "2026-05-01T00:00:00Z", tEnd: "2026-05-02T00:00:00Z",
        domain: "movements", tier: "fine", movementKind: "mil_aircraft",
      }),
    );
    await waitFor(() => expect(result.current.data?.samples.length).toBe(1));
    expect(spy).toHaveBeenCalledTimes(1);
  });

  it("does not fetch when disabled", async () => {
    const spy = vi.spyOn(api, "getTimeWindow").mockResolvedValue(RESP as never);
    renderHook(() => useTimeWindow(false, { tStart: "a", tEnd: "b" }));
    expect(spy).not.toHaveBeenCalled();
  });

  it("aborts the in-flight request on unmount", () => {
    let signal: AbortSignal | undefined;
    vi.spyOn(api, "getTimeWindow").mockImplementation((_q, s) => {
      signal = s;
      return new Promise<never>(() => {}); // never resolves
    });
    const { unmount } = renderHook(() =>
      useTimeWindow(true, { tStart: "a", tEnd: "b" }),
    );
    expect(signal?.aborted).toBe(false);
    unmount();
    expect(signal?.aborted).toBe(true);
  });

  it("aborts the previous request when the query changes (seq guard)", () => {
    const signals: AbortSignal[] = [];
    vi.spyOn(api, "getTimeWindow").mockImplementation((_q, s) => {
      if (s) signals.push(s);
      return new Promise<never>(() => {});
    });
    const { rerender } = renderHook(({ q }) => useTimeWindow(true, q), {
      initialProps: { q: { tStart: "a", tEnd: "b" } },
    });
    rerender({ q: { tStart: "a", tEnd: "c" } });
    expect(signals.length).toBeGreaterThanOrEqual(2);
    expect(signals[0]?.aborted).toBe(true); // first request cancelled on key change
  });
});
