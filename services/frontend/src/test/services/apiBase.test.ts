import { describe, it, expect, vi, beforeEach } from "vitest";

describe("api BASE", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllEnvs();
    vi.resetModules();
  });

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

  it("adds the admin token to report write requests", async () => {
    vi.stubEnv("VITE_ADMIN_TOKEN", "dev-admin-token");
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) });
    vi.stubGlobal("fetch", fetchMock);
    const {
      appendReportMessage,
      createReport,
      deleteReport,
      saveCountryBriefing,
      updateReport,
    } = await import("../../services/api");

    await createReport({ title: "Dossier" });
    await updateReport("r-1", { title: "Updated" });
    await deleteReport("r-1");
    await appendReportMessage("r-1", { role: "user", text: "Brief me" });
    await saveCountryBriefing("276", {
      query: "q",
      agent_chain: [],
      sources_used: [],
      analysis: "Lage stabil",
      confidence: 0.8,
      threat_assessment: "MODERATE",
      timestamp: "2026-06-23T00:00:00Z",
      tool_trace: [],
      mode: "react",
    });

    for (const call of fetchMock.mock.calls) {
      const init = call[1] as RequestInit;
      const headers = init.headers as Record<string, string>;
      expect(headers["X-Admin-Token"]).toBe("dev-admin-token");
    }
  });

  it("adds the admin token to incident admin write requests", async () => {
    vi.stubEnv("VITE_ADMIN_TOKEN", "dev-admin-token");
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) });
    vi.stubGlobal("fetch", fetchMock);
    const { promoteIncident, silenceIncident, triggerIncident } = await import(
      "../../services/api"
    );

    await triggerIncident({
      title: "x",
      kind: "firms.cluster",
      severity: "elevated",
      coords: [36.34, 41.87],
    });
    await silenceIncident("inc-1");
    await promoteIncident("inc-1");

    for (const call of fetchMock.mock.calls) {
      const init = call[1] as RequestInit;
      const headers = init.headers as Record<string, string>;
      expect(headers["X-Admin-Token"]).toBe("dev-admin-token");
    }
  });

  it("does not add the admin token to read requests", async () => {
    vi.stubEnv("VITE_ADMIN_TOKEN", "dev-admin-token");
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => [] });
    vi.stubGlobal("fetch", fetchMock);
    const { getReports } = await import("../../services/api");

    await getReports();

    const init = fetchMock.mock.calls[0]![1] as RequestInit | undefined;
    expect(init?.headers).not.toMatchObject({ "X-Admin-Token": "dev-admin-token" });
  });
});
