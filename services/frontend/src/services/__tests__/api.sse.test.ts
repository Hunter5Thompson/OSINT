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
    // so parsing must carry state across the chunk boundary. Events are blank-line
    // separated per the SSE spec (sse-starlette emits `\r\n\r\n`); the trailing
    // explicit `done` event also exercises the once-only onDone guard.
    const chunks = [
      "event: result\n",
      `data: ${JSON.stringify({ query: "q", analysis: "ok" })}\n\n`,
      "event: done\ndata: {}\n\n",
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

  it("delivers the parsed error message on a CRLF-separated error event", async () => {
    // The backend emits SSE with CRLF and a JSON error body
    // ({"error": "...", "code": "..."}). onError must receive the human-readable
    // message, not the raw JSON string with a trailing carriage return.
    const chunks = [
      "event: error\r\n",
      'data: {"error":"boom","code":"INTEL_SERVICE_ERROR"}\r\n',
    ];
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(streamResponse(chunks)));

    const onStatus = vi.fn();
    const onResult = vi.fn();
    const onDone = vi.fn();
    let resolveFinished: () => void = () => {};
    const finished = new Promise<void>((r) => {
      resolveFinished = r;
    });
    const onError = vi.fn(() => resolveFinished());

    const query: IntelQuery = { query: "q" };
    queryIntel(query, onStatus, onResult, onError, onDone);

    await finished;
    await new Promise((r) => setTimeout(r, 0));

    expect(onResult).not.toHaveBeenCalled();
    expect(onError).toHaveBeenCalledTimes(1);
    expect(onError).toHaveBeenCalledWith("boom");
  });
});
