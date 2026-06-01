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

  it("does not replay queryIntel (POST) against /api/v1 on a 404", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: false, status: 404, body: null });
    vi.stubGlobal("fetch", fetchMock);
    const { queryIntel } = await import("../../services/api");

    let resolveErr: () => void = () => {};
    const errored = new Promise<void>((r) => {
      resolveErr = r;
    });
    queryIntel({ query: "q" }, () => {}, () => {}, () => resolveErr(), () => {});
    await errored;
    await new Promise((r) => setTimeout(r, 0));

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0]![0]).toBe("/api/intel/query");
  });

  it("does not replay deleteReport (DELETE) against /api/v1 on a 404", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue({ ok: false, status: 404, statusText: "Not Found" });
    vi.stubGlobal("fetch", fetchMock);
    const { deleteReport } = await import("../../services/api");

    await expect(deleteReport("r-404")).rejects.toThrow();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0]![0]).toBe("/api/reports/r-404");
  });
});
