import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  parseCatalogRevision,
  parseScopeKeyCandidate,
  type SpatialQueryRef,
} from "../../spatial/contracts";
import { useSpatialCountryAlmanac } from "../useSpatialCountryAlmanac";

afterEach(() => vi.restoreAllMocks());

function deferred<T>() {
  let resolvePromise: (value: T) => void = () => undefined;
  const promise = new Promise<T>((resolve) => {
    resolvePromise = resolve;
  });
  return { promise, resolve: resolvePromise };
}

function query(scopeKey: string): SpatialQueryRef {
  return {
    schemaVersion: 1,
    scopeKey: parseScopeKeyCandidate(scopeKey),
    catalogRevision: parseCatalogRevision("spatial-v1-fe9828dcda05"),
    boundaryPolicy: "odin-reference-v1",
  };
}

function response(name: string): Response {
  return new Response(JSON.stringify({
    id: name,
    iso3: name.slice(0, 3).toUpperCase(),
    m49: "000",
    name,
    region: "Europe",
    subregion: "",
    capital: null,
    facts: { profile: [], people: [], government: [], economy: [], security: [] },
    updated_at: "2026-08-06",
    source_note: "fixture",
  }), { status: 200 });
}

describe("useSpatialCountryAlmanac", () => {
  it("requests only the exact committed scope and catalog revision", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(response("Ukraine"));
    const token = query("country:UKR");
    const { result } = renderHook(() => useSpatialCountryAlmanac(token));

    await waitFor(() => expect(result.current.status).toBe("ready"));

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/almanac/country?scope_key=country%3AUKR"
        + "&catalog_revision=spatial-v1-fe9828dcda05",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("ignores a late response from the previous committed query token", async () => {
    const first = deferred<Response>();
    const second = deferred<Response>();
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockImplementationOnce(() => first.promise)
      .mockImplementationOnce(() => second.promise);
    const ukraine = query("country:UKR");
    const poland = query("country:POL");
    const { result, rerender } = renderHook(
      ({ token }) => useSpatialCountryAlmanac(token),
      { initialProps: { token: ukraine } },
    );
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));

    rerender({ token: poland });
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    const firstSignal = (fetchMock.mock.calls[0]?.[1] as RequestInit).signal;
    expect(firstSignal).toBeInstanceOf(AbortSignal);
    expect(firstSignal?.aborted).toBe(true);

    await act(async () => first.resolve(response("STALE Ukraine")));
    expect(result.current.status).toBe("loading");

    await act(async () => second.resolve(response("Poland")));
    await waitFor(() => expect(result.current.status).toBe("ready"));
    expect(result.current.data?.name).toBe("Poland");
  });

  it("does not issue an identity lookup without a committed token", () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    const { result } = renderHook(() => useSpatialCountryAlmanac(null));
    expect(result.current.status).toBe("idle");
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
