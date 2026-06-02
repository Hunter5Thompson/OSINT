// services/frontend/src/hooks/__tests__/useCountryBriefing.test.tsx
import { describe, it, expect, vi, afterEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";

afterEach(() => vi.restoreAllMocks());

describe("useCountryBriefing", () => {
  it("transitions loading -> result", async () => {
    const api = await import("../../services/api");
    vi.spyOn(api, "streamCountryBriefing").mockImplementation(
      (_id, _s, onResult, _e, onDone) => {
        onResult({ query: "q", analysis: "ok", confidence: 0.8 } as never);
        onDone();
        return new AbortController();
      },
    );
    const { useCountryBriefing } = await import("../useCountryBriefing");
    const { result } = renderHook(() => useCountryBriefing("276"));
    act(() => result.current.run());
    await waitFor(() => expect(result.current.result?.analysis).toBe("ok"));
    expect(result.current.loading).toBe(false);
  });

  it("surfaces errors and clears loading", async () => {
    const api = await import("../../services/api");
    vi.spyOn(api, "streamCountryBriefing").mockImplementation(
      (_id, _s, _r, onError, onDone) => { onError("boom"); onDone(); return new AbortController(); },
    );
    const { useCountryBriefing } = await import("../useCountryBriefing");
    const { result } = renderHook(() => useCountryBriefing("276"));
    act(() => result.current.run());
    await waitFor(() => expect(result.current.error).toBe("boom"));
    expect(result.current.loading).toBe(false);
  });

  it("reset returns to initial state", async () => {
    const api = await import("../../services/api");
    vi.spyOn(api, "streamCountryBriefing").mockImplementation(
      (_id, _s, onResult, _e, onDone) => {
        onResult({ query: "q", analysis: "ok", confidence: 0.8 } as never);
        onDone();
        return new AbortController();
      },
    );
    const { useCountryBriefing } = await import("../useCountryBriefing");
    const { result } = renderHook(() => useCountryBriefing("276"));
    act(() => result.current.run());
    await waitFor(() => expect(result.current.result?.analysis).toBe("ok"));
    act(() => result.current.reset());
    expect(result.current.result).toBeNull();
    expect(result.current.loading).toBe(false);
  });

  it("aborts the previous stream when run is called again", async () => {
    const controllers: AbortController[] = [];
    const api = await import("../../services/api");
    vi.spyOn(api, "streamCountryBriefing").mockImplementation(
      (_id, _s, _r, _e, onDone) => {
        const c = new AbortController();
        vi.spyOn(c, "abort");
        controllers.push(c);
        onDone();
        return c;
      },
    );
    const { useCountryBriefing } = await import("../useCountryBriefing");
    const { result } = renderHook(() => useCountryBriefing("276"));
    act(() => result.current.run());
    act(() => result.current.run());
    const [first] = controllers;
    expect(first?.abort).toHaveBeenCalled(); // first stream aborted on second run
  });

  it("aborts the in-flight stream on reset", async () => {
    const controllers: AbortController[] = [];
    const api = await import("../../services/api");
    vi.spyOn(api, "streamCountryBriefing").mockImplementation((_id, _s, _r, _e, _d) => {
      const c = new AbortController();
      vi.spyOn(c, "abort");
      controllers.push(c);
      return c; // do NOT fire callbacks (simulate in-flight)
    });
    const { useCountryBriefing } = await import("../useCountryBriefing");
    const { result } = renderHook(() => useCountryBriefing("276"));
    act(() => result.current.run());
    act(() => result.current.reset());
    const [first] = controllers;
    expect(first?.abort).toHaveBeenCalled();
  });

  it("ignores a stale callback that arrives after reset (no result lands under the new country)", async () => {
    let capturedOnResult: ((a: never) => void) | undefined;
    const api = await import("../../services/api");
    vi.spyOn(api, "streamCountryBriefing").mockImplementation((_id, _s, onResult) => {
      capturedOnResult = onResult; // capture, fire later (simulate late arrival)
      return new AbortController();
    });
    const { useCountryBriefing } = await import("../useCountryBriefing");
    const { result } = renderHook(() => useCountryBriefing("276"));
    act(() => result.current.run()); // stream A starts
    act(() => result.current.reset()); // country switched away → reset aborts + invalidates
    act(() => capturedOnResult?.({ query: "q", analysis: "STALE-A", confidence: 0.5 } as never));
    expect(result.current.result).toBeNull(); // A's late result is ignored, not shown
  });
});
