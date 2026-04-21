import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";

const listeners = new Map<string, (ev: MessageEvent) => void>();
class FakeEventSource {
  url: string;
  addEventListener = vi.fn((type: string, cb: (ev: MessageEvent) => void) => {
    listeners.set(type, cb);
  });
  removeEventListener = vi.fn();
  close = vi.fn();
  onopen?: () => void;
  onerror?: () => void;
  set onmessage(cb: ((ev: MessageEvent) => void) | undefined) {
    if (cb) listeners.set("message", cb);
  }
  constructor(url: string) {
    this.url = url;
    setTimeout(() => this.onopen?.(), 0);
  }
}

describe("useSignalFeed wildcard", () => {
  beforeEach(() => {
    listeners.clear();
    vi.stubGlobal("EventSource", FakeEventSource as unknown as typeof EventSource);
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: true, json: async () => [] }),
    );
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("accepts any codebook_type via the onmessage wildcard (no signal.* filter)", async () => {
    const { useSignalFeed } = await import("../../hooks/useSignalFeed");
    const { result } = renderHook(() => useSignalFeed());
    await waitFor(() => expect(result.current.status).toBe("live"));

    const onmessage = listeners.get("message");
    expect(onmessage).toBeDefined();

    // A real taxonomy type — not under the signal.* namespace.
    act(() => {
      onmessage!({
        data: JSON.stringify({
          event_id: "01A",
          ts: "2026-04-21T00:00:00Z",
          type: "military.air_activity",
          payload: { title: "tu-95 barents", severity: "medium", source: "gdelt", url: "" },
        }),
        lastEventId: "01A",
      } as MessageEvent);
    });

    await waitFor(() => {
      expect(result.current.items.some((i) => i.type === "military.air_activity")).toBe(true);
    });
  });

  it("routes named SSE frames for new types via signal-feed:register", async () => {
    const { useSignalFeed } = await import("../../hooks/useSignalFeed");
    const { result } = renderHook(() => useSignalFeed());
    await waitFor(() => expect(result.current.status).toBe("live"));

    act(() => {
      window.dispatchEvent(
        new CustomEvent("signal-feed:register", { detail: { type: "other.unclassified" } }),
      );
    });
    const namedCb = listeners.get("other.unclassified");
    expect(namedCb).toBeDefined();

    act(() => {
      namedCb!({
        data: JSON.stringify({
          event_id: "01B",
          ts: "2026-04-21T00:00:00Z",
          type: "other.unclassified",
          payload: { title: "raw rss item", severity: "low", source: "rss", url: "" },
        }),
        lastEventId: "01B",
      } as MessageEvent);
    });

    await waitFor(() => {
      expect(result.current.items.some((i) => i.type === "other.unclassified")).toBe(true);
    });
  });

  it("removes the window register listener on unmount", async () => {
    const spy = vi.spyOn(window, "removeEventListener");
    const { useSignalFeed } = await import("../../hooks/useSignalFeed");
    const { unmount } = renderHook(() => useSignalFeed());
    unmount();
    expect(spy).toHaveBeenCalledWith("signal-feed:register", expect.any(Function));
    spy.mockRestore();
  });
});
