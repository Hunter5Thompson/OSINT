import { afterEach, describe, expect, it, vi } from "vitest";
import {
  parseCatalogRevision,
  parseScopeKeyCandidate,
  type SpatialQueryRef,
} from "../../spatial/contracts";
import type { HistogramResponse, WindowResponse } from "../../types";
import { getTimeHistogram, getTimeWindow } from "../api";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

const SCOPE: SpatialQueryRef = {
  schemaVersion: 1,
  scopeKey: parseScopeKeyCandidate("country:FJI"),
  catalogRevision: parseCatalogRevision("spatial-v1-123456789abc"),
  boundaryPolicy: "natural-earth-admin-v1",
};

const APPLICATION = {
  schema_version: 1,
  requested_scope_key: SCOPE.scopeKey,
  catalog_revision: SCOPE.catalogRevision,
  derivation_revision: "spatial-derive-v1-123456789abc",
  boundary_policy: SCOPE.boundaryPolicy,
  relation: "occurs-in",
  mode: "bbox_approximate",
  completeness: "partial",
  included_count: 2,
  excluded_unlocated_count: 1,
  excluded_conflict_count: 0,
  excluded_stale_revision_count: 0,
} as const;

const WINDOW: WindowResponse = {
  domain: "events",
  tier: "fine",
  t_start: "a",
  t_end: "b",
  bbox: null,
  samples: [],
  total_count: 2,
  truncated: false,
  spatial_application: APPLICATION,
};

const HISTOGRAM: HistogramResponse = {
  t_start: "a",
  t_end: "b",
  bucket_ms: 1,
  buckets: [],
  notables: [],
  geo_events: [],
  total_count: 2,
  geo_located_count: 2,
  geo_truncated: false,
  spatial_application: APPLICATION,
};

function mockJson(body: unknown): ReturnType<typeof vi.fn> {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => body,
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("timeline API spatial contract", () => {
  it("serializes scope identity for window requests without browser-derived bounds", async () => {
    const fetchMock = mockJson(WINDOW);

    await getTimeWindow({
      tStart: "a",
      tEnd: "b",
      domain: "events",
      spatialScope: SCOPE,
    });

    const url = String(fetchMock.mock.calls[0]?.[0]);
    const params = new URL(url, "http://odin.test").searchParams;
    expect(params.get("scope_key")).toBe("country:FJI");
    expect(params.get("catalog_revision")).toBe("spatial-v1-123456789abc");
    expect(params.has("bbox")).toBe(false);
    expect(params.has("boundary_policy")).toBe(false);
  });

  it("serializes the same scope identity for histogram requests", async () => {
    const fetchMock = mockJson(HISTOGRAM);

    await getTimeHistogram({ tStart: "a", tEnd: "b", buckets: 120, spatialScope: SCOPE });

    const url = String(fetchMock.mock.calls[0]?.[0]);
    const params = new URL(url, "http://odin.test").searchParams;
    expect(params.get("scope_key")).toBe("country:FJI");
    expect(params.get("catalog_revision")).toBe("spatial-v1-123456789abc");
  });

  it("rejects scope plus legacy bbox before making either request", async () => {
    const fetchMock = mockJson(WINDOW);
    const conflicted = {
      tStart: "a",
      tEnd: "b",
      spatialScope: SCOPE,
      bbox: [1, 2, 3, 4] as const,
    };

    await expect(getTimeWindow(conflicted)).rejects.toThrow(/mutually exclusive/i);
    await expect(getTimeHistogram(conflicted)).rejects.toThrow(/mutually exclusive/i);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("rejects malformed spatial application accounting at the response boundary", async () => {
    mockJson({ ...WINDOW, spatial_application: { ...APPLICATION, mode: "exact-ish" } });

    await expect(getTimeWindow({ tStart: "a", tEnd: "b", spatialScope: SCOPE }))
      .rejects.toThrow(/spatial_application/i);
  });

  it("accepts additive spatial application fields from a newer backend", async () => {
    mockJson({
      ...WINDOW,
      spatial_application: {
        ...APPLICATION,
        excluded_boundary_uncertain_count: 4,
        future_coverage_note: "additive-v1-field",
      },
    });

    const response = await getTimeWindow({ tStart: "a", tEnd: "b", spatialScope: SCOPE });

    expect(response.spatial_application.mode).toBe("bbox_approximate");
  });

  it("still rejects missing required fields and unknown schema versions", async () => {
    const missingBoundaryPolicy = Object.fromEntries(
      Object.entries(APPLICATION).filter(([key]) => key !== "boundary_policy"),
    );
    mockJson({ ...WINDOW, spatial_application: missingBoundaryPolicy });
    await expect(getTimeWindow({ tStart: "a", tEnd: "b", spatialScope: SCOPE }))
      .rejects.toThrow(/spatial_application/i);

    mockJson({ ...WINDOW, spatial_application: { ...APPLICATION, schema_version: 2 } });
    await expect(getTimeWindow({ tStart: "a", tEnd: "b", spatialScope: SCOPE }))
      .rejects.toThrow(/spatial_application/i);
  });
});
