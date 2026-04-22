import { describe, it, expect, vi, beforeEach } from "vitest";

describe("api BASE", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("uses /api (not /api/v1) for getFlights", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => [] });
    vi.stubGlobal("fetch", fetchMock);
    const { getFlights } = await import("../../services/api");
    await getFlights();
    const firstCallArgs = fetchMock.mock.calls[0];
    expect(firstCallArgs).toBeDefined();
    const url = firstCallArgs![0] as string;
    expect(url).toBe("/api/flights");
  });
});
