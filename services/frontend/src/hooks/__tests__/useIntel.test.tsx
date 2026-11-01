import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useIntel } from "../useIntel";
import { queryIntel } from "../../services/api";
vi.mock("../../services/api", () => ({ queryIntel: vi.fn() }));
const calls: { args: Parameters<typeof queryIntel>; controller: AbortController }[] = [];
vi.mocked(queryIntel).mockImplementation((...args) => {
  const controller = new AbortController();
  calls.push({ args, controller });
  return controller;
});
afterEach(() => { calls.length = 0; });

describe("owned intelligence request", () => {
  it("cancels superseded work and ignores late error/done callbacks", () => {
    const { result } = renderHook(useIntel);
    act(() => { result.current.runQuery({ query: "first" }); });
    act(() => { result.current.runQuery({ query: "second" }); });
    expect(calls[0]!.controller.signal.aborted).toBe(true);
    act(() => { calls[0]!.args[3]("stale error"); calls[0]!.args[4](); });
    expect(result.current.loading).toBe(true);
    expect(result.current.error).toBeNull();
  });
  it("cancel clears pending UI and blocks late callbacks", () => {
    const { result } = renderHook(useIntel);
    let stop: () => void = () => {};
    act(() => { stop = result.current.runQuery({ query: "first" }); });
    act(() => { stop(); });
    expect(calls[0]!.controller.signal.aborted).toBe(true);
    expect(result.current.loading).toBe(false);
    act(() => { calls[0]!.args[1]({ agent: "late", status: "processing" }); });
    expect(result.current.currentAgent).toBeNull();
  });
  it("an obsolete cancel handle cannot cancel the new request", () => {
    const { result } = renderHook(useIntel);
    let stop: () => void = () => {};
    act(() => { stop = result.current.runQuery({ query: "first" }); });
    act(() => { result.current.runQuery({ query: "second" }); });
    act(() => { stop(); });
    expect(calls[1]!.controller.signal.aborted).toBe(false);
    expect(result.current.loading).toBe(true);
  });
  it("aborts on unmount", () => {
    const { result, unmount } = renderHook(useIntel);
    act(() => { result.current.runQuery({ query: "first" }); });
    unmount();
    expect(calls[0]!.controller.signal.aborted).toBe(true);
  });
});
