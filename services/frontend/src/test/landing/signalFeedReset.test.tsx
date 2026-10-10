import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "../../services/api";
import { useSignalFeed } from "../../hooks/useSignalFeed";
import type { SignalEnvelope } from "../../types/signals";
import { MockEventSource, installMockEventSource, uninstallMockEventSource } from "../utils/mockEventSource";

const id = (n: number) => `0000000001000-${String(n).padStart(6, "0")}`;
function env(n: number): SignalEnvelope {
  return { event_id: id(n), ts: "2026-01-01T00:00:00Z", type: "signal.firms", payload: { redis_id: id(n), title: String(n) } };
}
function deferred() {
  let resolve!: (value: SignalEnvelope[]) => void;
  let reject!: (failure: Error) => void;
  const promise = new Promise<SignalEnvelope[]>((done, fail) => { resolve = done; reject = fail; });
  return { promise, resolve, reject };
}
async function start() {
  const fetch = vi.spyOn(api, "getLatestSignals").mockResolvedValueOnce([env(1)]);
  const hook = renderHook(() => useSignalFeed());
  await act(async () => {});
  const es = MockEventSource.instances[0]!;
  expect(es).toBeDefined();
  return { ...hook, es, fetch };
}
beforeEach(installMockEventSource);
afterEach(() => { cleanup(); uninstallMockEventSource(); vi.restoreAllMocks(); vi.useRealTimers(); });

describe("signal reset generation", () => {
  it("merges live arrivals during snapshot, dedupes and never rewinds the cursor", async () => {
    const { result, es, fetch } = await start();
    const snapshot = deferred();
    fetch.mockReturnValueOnce(snapshot.promise);
    act(() => es.trigger("reset", "{}"));
    act(() => es.trigger("signal.firms", JSON.stringify(env(5)), id(5)));
    await act(async () => snapshot.resolve([env(4), env(3), env(3)]));
    expect(result.current.items.map(e => e.event_id)).toEqual([id(5), id(4), id(3)]);
    expect(result.current.lastEventId).toBe(id(5));
    act(() => es.trigger("signal.firms", JSON.stringify(env(5)), id(5)));
    expect(result.current.items).toHaveLength(3);
  });

  it("the newer reset wins out of order and preserves only its live buffer", async () => {
    const { result, es, fetch } = await start();
    const a = deferred(); const b = deferred();
    fetch.mockReturnValueOnce(a.promise).mockReturnValueOnce(b.promise);
    act(() => es.trigger("reset", "{}"));
    act(() => es.trigger("reset", "{}"));
    act(() => es.trigger("signal.firms", JSON.stringify(env(6)), id(6)));
    await act(async () => b.resolve([env(5)]));
    await act(async () => a.resolve([env(2)]));
    expect(result.current.items.map(e => e.event_id)).toEqual([id(6), id(5)]);
    expect(result.current.lastEventId).toBe(id(6));
  });

  it("a failed reset retains the usable display, dedupe and live events", async () => {
    const { result, es, fetch } = await start();
    const snapshot = deferred();
    fetch.mockReturnValueOnce(snapshot.promise);
    act(() => es.trigger("reset", "{}"));
    act(() => es.trigger("signal.firms", JSON.stringify(env(1)), id(1)));
    act(() => es.trigger("signal.firms", JSON.stringify(env(2)), id(2)));
    await act(async () => snapshot.reject(new Error("snapshot unavailable")));
    expect(result.current.items.map(e => e.event_id)).toEqual([id(2), id(1)]);
    expect(result.current.lastEventId).toBe(id(2));
  });

  it("sorts by the canonical server ID, caps and dedupes snapshot plus live", async () => {
    const { result, es, fetch } = await start();
    const snapshot = deferred();
    fetch.mockReturnValueOnce(snapshot.promise);
    act(() => es.trigger("reset", "{}"));
    for (const n of [7, 9, 8]) act(() => es.trigger("signal.firms", JSON.stringify(env(n)), id(n)));
    await act(async () => snapshot.resolve([env(8), env(6), env(5), env(4), env(3), env(2)]));
    expect(result.current.items.map(e => e.event_id)).toEqual([9, 8, 7, 6, 5, 4].map(id));
    expect(result.current.lastEventId).toBe(id(9));
  });

  it("ignores reset completions after unmount", async () => {
    const { result, es, fetch, unmount } = await start();
    const snapshot = deferred();
    fetch.mockReturnValueOnce(snapshot.promise);
    act(() => es.trigger("reset", "{}"));
    const before = result.current;
    unmount();
    await act(async () => snapshot.resolve([env(9)]));
    expect(es.readyState).toBe(2);
    expect(result.current).toBe(before);
  });

  it("reconnects with the highest cursor after reset and ignores closed-source callbacks", async () => {
    vi.useFakeTimers();
    const { result, es, fetch } = await start();
    const snapshot = deferred();
    fetch.mockReturnValueOnce(snapshot.promise);
    act(() => es.trigger("reset", "{}"));
    act(() => es.trigger("signal.firms", JSON.stringify(env(8)), id(8)));
    await act(async () => snapshot.resolve([env(6)]));
    act(() => es.fail());
    act(() => vi.advanceTimersByTime(1000));
    const next = MockEventSource.instances[1]!;
    expect(next.lastEventIdHint).toBe(id(8));
    act(() => es.trigger("signal.firms", JSON.stringify(env(9)), id(9)));
    expect(result.current.lastEventId).toBe(id(8));
  });
});
