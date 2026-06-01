import { describe, it, expect, vi, beforeEach } from "vitest";

import type { IntelQuery } from "../../types";
import { queryIntel } from "../api";

/** Build a fake streaming Response whose body yields the given chunks verbatim. */
function streamResponse(chunks: string[]): Response {
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(encoder.encode(chunk));
      }
      controller.close();
    },
  });
  return { ok: true, status: 200, body } as unknown as Response;
}

describe("queryIntel SSE parser", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("parses a result split across chunks and fires onDone exactly once", async () => {
    // The `event:` and `data:` lines for the result arrive in SEPARATE chunks,
    // so a per-chunk `currentEvent` loses the event type at the boundary.
    // The trailing explicit `done` event also exercises the double-onDone bug
    // (in-loop dispatch + unconditional post-loop call).
    const chunks = [
      "event: result\n",
      `data: ${JSON.stringify({ query: "q", analysis: "ok" })}\n`,
      "event: done\ndata: {}\n",
    ];
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(streamResponse(chunks)));

    const onStatus = vi.fn();
    const onResult = vi.fn();
    const onError = vi.fn();
    let resolveFinished: () => void = () => {};
    const finished = new Promise<void>((r) => {
      resolveFinished = r;
    });
    const onDone = vi.fn(() => resolveFinished());

    const query: IntelQuery = { query: "q" };
    queryIntel(query, onStatus, onResult, onError, onDone);

    await finished;
    // Flush any trailing microtask (the buggy unconditional post-loop onDone).
    await new Promise((r) => setTimeout(r, 0));

    expect(onError).not.toHaveBeenCalled();
    expect(onResult).toHaveBeenCalledTimes(1);
    expect(onResult.mock.calls[0]![0]).toMatchObject({ analysis: "ok" });
    expect(onDone).toHaveBeenCalledTimes(1);
  });
});
