import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useCountryAlmanac } from "../useCountryAlmanac";

afterEach(() => {
  vi.restoreAllMocks();
});

function mockFetch() {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/api/almanac/countries/GRC/signals")) {
      return new Response(JSON.stringify({ country_id: "GRC", items: [] }), { status: 200 });
    }
    if (url.includes("/api/almanac/countries/732/signals")) {
      return new Response(JSON.stringify({ country_id: "732", items: [] }), { status: 200 });
    }
    if (url.includes("/api/almanac/countries/GRC")) {
      return new Response(
        JSON.stringify({
          id: "GRC",
          iso3: "GRC",
          m49: "300",
          name: "Greece",
          region: "Europe",
          subregion: "Southern Europe",
          capital: { name: "Athens", lat: 37.98, lon: 23.73 },
          facts: {
            profile: [{ label: "Currency", value: "Euro (EUR)" }],
            people: [],
            government: [],
            economy: [],
            security: [],
          },
          updated_at: "2026-05-19",
          source_note: "ODIN static country almanac",
        }),
        { status: 200 },
      );
    }
    if (url.includes("/api/almanac/countries/732")) {
      return new Response(
        JSON.stringify({
          id: "732",
          iso3: null,
          m49: "732",
          name: "W. Sahara",
          region: "Africa",
          subregion: "Northern Africa",
          capital: null,
          facts: { profile: [], people: [], government: [], economy: [], security: [] },
          updated_at: "2026-05-19",
          source_note: "ODIN static country almanac",
        }),
        { status: 200 },
      );
    }
    return new Response("not found", { status: 404 });
  });
}

describe("useCountryAlmanac", () => {
  it("fetches almanac facts and signals by iso3", async () => {
    const fetchMock = mockFetch();
    const { result } = renderHook(() => useCountryAlmanac({ iso3: "GRC", m49: "300" }));

    await waitFor(() => expect(result.current.facts.status).toBe("ready"));

    expect(result.current.facts.data?.name).toBe("Greece");
    expect(result.current.signals.status).toBe("ready");
    expect(fetchMock).toHaveBeenCalledWith("/api/almanac/countries/GRC", expect.any(Object));
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/almanac/countries/GRC/signals?limit=5",
      expect.any(Object),
    );
  });

  it("falls back to m49 when iso3 is null", async () => {
    const fetchMock = mockFetch();
    renderHook(() => useCountryAlmanac({ iso3: null, m49: "732" }));
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("/api/almanac/countries/732", expect.any(Object));
    });
  });
});
