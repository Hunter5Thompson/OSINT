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
});
