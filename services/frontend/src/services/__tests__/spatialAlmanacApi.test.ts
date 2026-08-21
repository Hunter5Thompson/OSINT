import { afterEach, describe, expect, it, vi } from "vitest";

import {
  parseCatalogRevision,
  parseScopeKeyCandidate,
  type SpatialQueryRef,
} from "../../spatial/contracts";
import {
  getSpatialCountryAlmanacSignals,
  saveSpatialCountryBriefing,
  streamSpatialCountryBriefing,
} from "../api";

afterEach(() => vi.restoreAllMocks());

function query(): SpatialQueryRef {
  return {
    schemaVersion: 1,
    scopeKey: parseScopeKeyCandidate("country:UKR"),
    catalogRevision: parseCatalogRevision("spatial-v1-fe9828dcda05"),
    boundaryPolicy: "odin-reference-v1",
  };
}

describe("Spatial country inspector API", () => {
  it("uses one exact query token for signals, briefing generation, and save", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response(JSON.stringify({ country_id: "UKR", items: [] })))
      .mockResolvedValueOnce({ ok: false, status: 503, body: null } as Response)
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "r-1" })));
    const token = query();

    await getSpatialCountryAlmanacSignals(token, 5, new AbortController().signal);
    streamSpatialCountryBriefing(token, vi.fn(), vi.fn(), vi.fn(), vi.fn());
    await saveSpatialCountryBriefing(
      token,
      { query: "q", analysis: "Scoped", confidence: 0.8 } as never,
      new AbortController().signal,
    );

    expect(fetchMock.mock.calls.map(([input]) => String(input))).toEqual([
      "/api/almanac/country/signals?scope_key=country%3AUKR"
        + "&catalog_revision=spatial-v1-fe9828dcda05&limit=5",
      "/api/almanac/country/briefing?scope_key=country%3AUKR"
        + "&catalog_revision=spatial-v1-fe9828dcda05",
      "/api/almanac/country/briefing/save?scope_key=country%3AUKR"
        + "&catalog_revision=spatial-v1-fe9828dcda05",
    ]);
    expect(fetchMock.mock.calls[2]?.[1]).toEqual(expect.objectContaining({
      method: "POST",
      signal: expect.any(AbortSignal),
    }));
  });
});
