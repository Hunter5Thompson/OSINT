// services/frontend/src/services/__tests__/consumeSSE.test.ts
import { describe, it, expect, vi } from "vitest";
import { consumeSSE } from "../api";

function streamFrom(chunks: string[]): ReadableStream<Uint8Array> {
  const enc = new TextEncoder();
  let i = 0;
  return new ReadableStream({
    pull(c) {
      if (i < chunks.length) c.enqueue(enc.encode(chunks[i++]));
      else c.close();
    },
  });
}

describe("consumeSSE", () => {
  it("preserves event type across chunk boundaries and calls onDone once", async () => {
    const onStatus = vi.fn(), onResult = vi.fn(), onError = vi.fn(), onDone = vi.fn();
    // event: and data: split across chunks; CRLF; two frames; explicit done frame
    const body = streamFrom([
      "event: status\r\n",
      "data: {\"agent\":\"a\"}\r\n\r\n",
      "event: result\r\ndata: {\"analysis\":\"ok\"}\r\n\r\nevent: done\r\ndata: \r\n\r\n",
    ]);
    await consumeSSE(body, { onStatus, onResult, onError, onDone });
    expect(onStatus).toHaveBeenCalledTimes(1);
    expect(onResult).toHaveBeenCalledWith({ analysis: "ok" });
    expect(onError).not.toHaveBeenCalled();
    expect(onDone).toHaveBeenCalledTimes(1);
  });

  it("calls onError for an error event and still calls onDone once", async () => {
    const onStatus = vi.fn(), onResult = vi.fn(), onError = vi.fn(), onDone = vi.fn();
    const body = streamFrom([
      "event: error\r\ndata: boom\r\n\r\nevent: done\r\ndata: \r\n\r\n",
    ]);
    await consumeSSE(body, { onStatus, onResult, onError, onDone });
    expect(onError).toHaveBeenCalledWith("boom");
    expect(onDone).toHaveBeenCalledTimes(1);
  });

  it("skips a malformed-JSON frame without throwing and keeps streaming", async () => {
    const onStatus = vi.fn(), onResult = vi.fn(), onError = vi.fn(), onDone = vi.fn();
    const body = streamFrom([
      "event: status\r\ndata: {not json}\r\n\r\nevent: result\r\ndata: {\"analysis\":\"ok\"}\r\n\r\n",
    ]);
    await consumeSSE(body, { onStatus, onResult, onError, onDone });
    expect(onStatus).not.toHaveBeenCalled();          // malformed status frame skipped
    expect(onResult).toHaveBeenCalledWith({ analysis: "ok" });
    expect(onDone).toHaveBeenCalledTimes(1);           // stream end → onDone once
  });

  it("calls onDone exactly once when the stream ends without a done frame", async () => {
    const onResult = vi.fn(), onDone = vi.fn();
    const body = streamFrom([
      "event: result\r\ndata: {\"analysis\":\"ok\"}\r\n\r\n",   // no done frame
    ]);
    await consumeSSE(body, { onStatus: vi.fn(), onResult, onError: vi.fn(), onDone });
    expect(onResult).toHaveBeenCalledWith({ analysis: "ok" });
    expect(onDone).toHaveBeenCalledTimes(1);
  });
});
