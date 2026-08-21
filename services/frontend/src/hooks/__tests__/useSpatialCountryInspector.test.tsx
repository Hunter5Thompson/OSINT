import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  parseCatalogRevision,
  parseScopeKeyCandidate,
  type SpatialQueryRef,
} from "../../spatial/contracts";
import type { IntelAnalysis } from "../../types";
import { useSpatialCountryBriefing } from "../useSpatialCountryBriefing";
import { useSpatialCountrySignals } from "../useSpatialCountrySignals";

afterEach(() => vi.restoreAllMocks());

function query(scopeKey: string): SpatialQueryRef {
  return {
    schemaVersion: 1,
    scopeKey: parseScopeKeyCandidate(scopeKey),
    catalogRevision: parseCatalogRevision("spatial-v1-fe9828dcda05"),
    boundaryPolicy: "odin-reference-v1",
  };
}

function signalResponse(countryId: string, title: string): Response {
  return new Response(JSON.stringify({
    country_id: countryId,
    scope_key: `country:${countryId}`,
    catalog_revision: "spatial-v1-fe9828dcda05",
    items: [{
      event_id: `${countryId}-1`,
      ts: "2026-08-10T00:00:00Z",
      type: "signal.rss",
      title,
      severity: "low",
      source: "rss",
      url: "",
    }],
  }), { status: 200 });
}

function deferred<T>() {
  let resolvePromise: (value: T) => void = () => undefined;
  const promise = new Promise<T>((resolve) => {
    resolvePromise = resolve;
  });
  return { promise, resolve: resolvePromise };
}

describe("useSpatialCountrySignals", () => {
  it("requests the exact committed scope and catalog revision", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValue(signalResponse("UKR", "Ukraine signal"));
    const token = query("country:UKR");
    const { result } = renderHook(() => useSpatialCountrySignals(token));

    await waitFor(() => expect(result.current.status).toBe("ready"));

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/almanac/country/signals?scope_key=country%3AUKR"
        + "&catalog_revision=spatial-v1-fe9828dcda05&limit=5",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
  });

  it("cannot commit a late response from selection A after selection B", async () => {
    const first = deferred<Response>();
    const second = deferred<Response>();
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockImplementationOnce(() => first.promise)
      .mockImplementationOnce(() => second.promise);
    const ukraine = query("country:UKR");
    const poland = query("country:POL");
    const { result, rerender } = renderHook(
      ({ token }) => useSpatialCountrySignals(token),
      { initialProps: { token: ukraine } },
    );
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));

    rerender({ token: poland });
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    const firstSignal = (fetchMock.mock.calls[0]?.[1] as RequestInit).signal;
    expect(firstSignal?.aborted).toBe(true);

    await act(async () => first.resolve(signalResponse("UKR", "STALE Ukraine")));
    expect(result.current.status).toBe("loading");

    await act(async () => second.resolve(signalResponse("POL", "Poland signal")));
    await waitFor(() => expect(result.current.status).toBe("ready"));
    expect(result.current.data?.country_id).toBe("POL");
    expect(result.current.data?.items[0]?.title).toBe("Poland signal");
  });

  it("rejects a response whose committed scope identity differs", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      signalResponse("POL", "wrong scope"),
    );
    const { result } = renderHook(() => useSpatialCountrySignals(query("country:UKR")));

    await waitFor(() => expect(result.current.status).toBe("error"));
    expect(result.current.error).toMatch(/scope echo/i);
    expect(result.current.data).toBeNull();
  });
});

function scopedAnalysis(scopeKey: string, analysis: string): IntelAnalysis {
  return {
    query: "q",
    agent_chain: [],
    sources_used: [],
    analysis,
    confidence: 0.8,
    threat_assessment: null,
    timestamp: "2026-08-10T00:00:00Z",
    spatial_application: {
      schema_version: 1,
      scope: {
        schema_version: 1,
        scope_key: scopeKey,
        catalog_revision: "spatial-v1-fe9828dcda05",
        derivation_revision: "spatial-derive-v1-123456789abc",
        boundary_policy: "odin-reference-v1",
      },
      relation: "either",
      qdrant: { status: "applied", mode: "semantic-key", completeness: "partial" },
      neo4j: { status: "not-called", mode: "semantic-key", completeness: "unknown" },
      blocked_tools: [],
      coverage_revision: null,
    },
  };
}

describe("useSpatialCountryBriefing", () => {
  it("pins every chunk to the exact query and rejects chunks from selection A", async () => {
    const api = await import("../../services/api");
    const runs: Array<{
      readonly query: SpatialQueryRef;
      readonly onStatus: (status: { agent: string; status: string }) => void;
      readonly onResult: (analysis: IntelAnalysis) => void;
      readonly onDone: () => void;
      readonly controller: AbortController;
    }> = [];
    vi.spyOn(api, "streamSpatialCountryBriefing").mockImplementation(
      (requested, onStatus, onResult, _onError, onDone) => {
        const controller = new AbortController();
        runs.push({ query: requested, onStatus, onResult, onDone, controller });
        return controller;
      },
    );
    const ukraine = query("country:UKR");
    const poland = query("country:POL");
    const { result, rerender } = renderHook(
      ({ token }) => useSpatialCountryBriefing(token),
      { initialProps: { token: ukraine } },
    );

    act(() => result.current.run());
    expect(runs[0]?.query).toBe(ukraine);

    rerender({ token: poland });
    await waitFor(() => expect(runs[0]?.controller.signal.aborted).toBe(true));
    act(() => {
      runs[0]?.onStatus({ agent: "stale-agent", status: "running" });
      runs[0]?.onResult(scopedAnalysis("country:UKR", "STALE Ukraine"));
      runs[0]?.onDone();
    });
    expect(result.current.result).toBeNull();
    expect(result.current.currentAgent).toBeNull();

    act(() => result.current.run());
    expect(runs[1]?.query).toBe(poland);
    act(() => {
      runs[1]?.onResult(scopedAnalysis("country:POL", "Poland current"));
      runs[1]?.onDone();
    });
    expect(result.current.result?.analysis).toBe("Poland current");
    expect(result.current.loading).toBe(false);
  });

  it("rejects a current briefing result with the wrong scope echo", async () => {
    const api = await import("../../services/api");
    let onResult: ((analysis: IntelAnalysis) => void) | null = null;
    vi.spyOn(api, "streamSpatialCountryBriefing").mockImplementation(
      (_requested, _onStatus, resultHandler) => {
        onResult = resultHandler;
        return new AbortController();
      },
    );
    const { result } = renderHook(() => useSpatialCountryBriefing(query("country:UKR")));

    act(() => result.current.run());
    act(() => onResult?.(scopedAnalysis("country:POL", "wrong")));

    expect(result.current.result).toBeNull();
    expect(result.current.error).toMatch(/scope echo/i);
  });
});
