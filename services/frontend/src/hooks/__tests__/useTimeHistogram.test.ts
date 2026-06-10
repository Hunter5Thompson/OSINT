import { afterEach, describe, it, expect, vi } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import * as api from "../../services/api";
import { useTimeHistogram } from "../useTimeHistogram";

afterEach(() => vi.restoreAllMocks());

const RESP = {
  t_start: "a", t_end: "b", bucket_ms: 1,
  buckets: [{ ts: "a", count: 1, dominant_category: "civil", by_category: {}, by_severity: {} }],
  notables: [], geo_events: [], total_count: 1, geo_located_count: 0, geo_truncated: false,
} as const;

describe("useTimeHistogram", () => {
  it("fetches when enabled", async () => {
    const spy = vi.spyOn(api, "getTimeHistogram").mockResolvedValue(RESP as never);
    const { result } = renderHook(() =>
      useTimeHistogram(true, { tStart: "a", tEnd: "b", buckets: 120 }),
    );
    await waitFor(() => expect(result.current.data?.buckets.length).toBe(1));
    expect(spy).toHaveBeenCalledTimes(1);
  });
  it("does not fetch when disabled", () => {
    const spy = vi.spyOn(api, "getTimeHistogram").mockResolvedValue(RESP as never);
    renderHook(() => useTimeHistogram(false, { tStart: "a", tEnd: "b" }));
    expect(spy).not.toHaveBeenCalled();
  });
});
