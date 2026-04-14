/**
 * Tests for `useSignalFeed` (ODIN S1 · Task 6).
 *
 * Verifies:
 *  1. Initial status is `idle`, transitions to `live` once the EventSource
 *     `open` event fires.
 *  2. On mount the hook hydrates by calling `/api/signals/latest?limit=6`
 *     and initializing `items` from the response (newest-first).
 *  3. Incoming SSE frames prepend new items, capped at 6 entries.
 *  4. Duplicate `event_id`s are ignored (dedupe set).
 *  5. On `event: reset` the dedupe set is cleared, the latest endpoint is
 *     re-fetched, and `items` are replaced with the new snapshot.
 *  6. On EventSource error, status transitions `live → reconnecting` and a
 *     new EventSource is created after backoff (1 s, 2 s, 4 s …).
 *  7. Unmount closes the EventSource (readyState == 2).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { useSignalFeed } from "../../hooks/useSignalFeed";
import {
  MockEventSource,
  installMockEventSource,
  uninstallMockEventSource,
} from "../utils/mockEventSource";
import type { SignalEnvelope } from "../../types/signals";

function currentEventSource(): MockEventSource {
  const all = MockEventSource.instances;
  const es = all[all.length - 1];
  if (!es) throw new Error("no EventSource instance installed yet");
  return es;
}

function envelope(id: string, title: string, ts = "2026-04-14T12:00:00.000Z"): SignalEnvelope {
  return {
    event_id: id,
    ts,
    type: "signal.firms",
    payload: {
      title,
      severity: "medium",
      source: "firms",
      url: "",
      redis_id: id,
    },
  };
}

function mockFetchLatest(items: SignalEnvelope[]) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input.toString();
    if (url.includes("/api/signals/latest")) {
      return new Response(JSON.stringify(items), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }
    return new Response("not found", { status: 404 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

beforeEach(() => {
  installMockEventSource();
});

afterEach(() => {
  uninstallMockEventSource();
  vi.unstubAllGlobals();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("useSignalFeed · initial state and hydration", () => {
  it("starts idle and transitions to live on open", async () => {
    mockFetchLatest([]);
    const { result } = renderHook(() => useSignalFeed());
    expect(result.current.status).toBe("idle");

    // Allow hydration + EventSource construction to happen.
    await waitFor(() => expect(MockEventSource.instances.length).toBe(1));
    act(() => {
      currentEventSource().open();
    });
    await waitFor(() => expect(result.current.status).toBe("live"));
  });

  it("hydrates items from /api/signals/latest on mount", async () => {
    const initial = [envelope("0000000001000-000001", "sinjar cluster")];
    const fetchMock = mockFetchLatest(initial);
    const { result } = renderHook(() => useSignalFeed());

    await waitFor(() => expect(result.current.items.length).toBe(1));
    expect(result.current.items[0]?.payload.title).toBe("sinjar cluster");
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/api/signals/latest?limit=6"),
      expect.anything(),
    );
  });
});

describe("useSignalFeed · live events", () => {
  it("prepends live events and caps at 6", async () => {
    mockFetchLatest([envelope("0000000001000-000001", "seed")]);
    const { result } = renderHook(() => useSignalFeed());
    await waitFor(() => expect(result.current.items.length).toBe(1));

    const es = currentEventSource();
    act(() => es.open());

    for (let i = 2; i <= 8; i++) {
      const padded = String(i).padStart(6, "0");
      const id = `0000000001000-${padded}`;
      act(() => {
        es.trigger(
          "signal.firms",
          JSON.stringify(envelope(id, `event ${i}`)),
          id,
        );
      });
    }

    expect(result.current.items.length).toBe(6);
    // Newest first.
    expect(result.current.items[0]?.payload.title).toBe("event 8");
    expect(result.current.lastEventId).toBe("0000000001000-000008");
  });

  it("dedupes events by event_id", async () => {
    mockFetchLatest([]);
    const { result } = renderHook(() => useSignalFeed());
    await waitFor(() => expect(MockEventSource.instances.length).toBe(1));
    const es = currentEventSource();
    act(() => es.open());

    const id = "0000000001000-000001";
    act(() => {
      es.trigger("signal.firms", JSON.stringify(envelope(id, "first")), id);
    });
    act(() => {
      es.trigger("signal.firms", JSON.stringify(envelope(id, "duplicate")), id);
    });

    expect(result.current.items.length).toBe(1);
    expect(result.current.items[0]?.payload.title).toBe("first");
  });
});

describe("useSignalFeed · reset handling", () => {
  it("clears dedupe and replaces items on reset frame", async () => {
    const initial = [envelope("0000000001000-000001", "stale")];
    const fetchMock = mockFetchLatest(initial);

    const { result } = renderHook(() => useSignalFeed());
    await waitFor(() => expect(result.current.items.length).toBe(1));

    const es = currentEventSource();
    act(() => es.open());

    // Swap the fetch response for what we want the reset refetch to return.
    fetchMock.mockImplementation(async () => {
      return new Response(
        JSON.stringify([envelope("0000000002000-000001", "fresh")]),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    });

    act(() => {
      es.trigger("reset", JSON.stringify({ reason: "stale-last-event-id" }));
    });

    await waitFor(() => {
      expect(result.current.items[0]?.payload.title).toBe("fresh");
    });

    // Same id that used to be deduped should now be accepted.
    act(() => {
      es.trigger(
        "signal.firms",
        JSON.stringify(envelope("0000000001000-000001", "stale-reborn")),
        "0000000001000-000001",
      );
    });
    expect(
      result.current.items.some((e) => e.payload.title === "stale-reborn"),
    ).toBe(true);
  });
});

describe("useSignalFeed · reconnect", () => {
  it("transitions live → reconnecting on error and recreates EventSource after backoff", async () => {
    mockFetchLatest([]);
    vi.useFakeTimers();

    const { result } = renderHook(() => useSignalFeed());
    await vi.waitFor(() => expect(MockEventSource.instances.length).toBe(1));
    act(() => currentEventSource().open());
    expect(result.current.status).toBe("live");

    act(() => {
      currentEventSource().fail();
    });
    expect(result.current.status).toBe("reconnecting");

    // Before backoff elapses → still exactly 1 instance.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(500);
    });
    expect(MockEventSource.instances.length).toBe(1);

    // After 1s → reconnect.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(MockEventSource.instances.length).toBe(2);
  });
});

describe("useSignalFeed · cleanup", () => {
  it("closes the EventSource on unmount", async () => {
    mockFetchLatest([]);
    const { unmount } = renderHook(() => useSignalFeed());
    await waitFor(() => expect(MockEventSource.instances.length).toBe(1));
    const es = currentEventSource();
    unmount();
    expect(es.readyState).toBe(2);
  });

  it(
    "does not leak an orphan EventSource under React 19 Strict-Mode " +
      "double-invocation (mount → unmount → remount before hydration resolves)",
    async () => {
      mockFetchLatest([]);
      // First mount: start hydration, immediately unmount before the fetch
      // resolves, then remount — this mirrors what <React.StrictMode> does.
      const first = renderHook(() => useSignalFeed());
      first.unmount();
      const second = renderHook(() => useSignalFeed());

      // Let hydration + microtasks drain for both effects.
      await waitFor(() =>
        expect(MockEventSource.instances.length).toBeGreaterThanOrEqual(1),
      );
      // Allow extra microtasks — any orphan would show up as a second open
      // EventSource here.
      await new Promise((r) => setTimeout(r, 0));
      await new Promise((r) => setTimeout(r, 0));

      const openSources = MockEventSource.instances.filter(
        (es) => es.readyState !== 2,
      );
      expect(openSources.length).toBe(1);

      second.unmount();
      // After final unmount everything is closed.
      const stillOpen = MockEventSource.instances.filter(
        (es) => es.readyState !== 2,
      );
      expect(stillOpen.length).toBe(0);
    },
  );
});

describe("useSignalFeed · manual reconnect URL", () => {
  it("includes ?last_event_id=<last> on the reconnect EventSource URL", async () => {
    mockFetchLatest([]);
    vi.useFakeTimers();

    const { result } = renderHook(() => useSignalFeed());
    await vi.waitFor(() => expect(MockEventSource.instances.length).toBe(1));
    const first = currentEventSource();
    act(() => first.open());

    // Deliver a live event so `lastEventId` advances beyond the hydrated null.
    const id = "0000000001000-000042";
    act(() => {
      first.trigger("signal.firms", JSON.stringify(envelope(id, "evt")), id);
    });
    await vi.waitFor(() => expect(result.current.lastEventId).toBe(id));

    // Force a reconnect.
    act(() => first.fail());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(MockEventSource.instances.length).toBe(2);
    const reconnected = currentEventSource();
    expect(reconnected.url).toContain("last_event_id=");
    expect(reconnected.lastEventIdHint).toBe(id);
  });
});
