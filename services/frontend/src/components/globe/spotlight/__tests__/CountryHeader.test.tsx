import { render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  CountryHeader,
  SpatialCountryHeader,
} from "../CountryHeader";
import {
  parseCatalogRevision,
  parseScopeKeyCandidate,
} from "../../../../spatial/contracts";

afterEach(() => {
  vi.restoreAllMocks();
});

function mockCountryFetch(status = 200) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/signals")) {
      return new Response(
        JSON.stringify({
          ...(url.includes("/api/almanac/country/signals")
            ? {
                scope_key: "country:UKR",
                catalog_revision: "spatial-v1-fe9828dcda05",
              }
            : {}),
          country_id: "GRC",
          items: [
            {
              event_id: "1",
              ts: "2026-05-19T10:20:00.000Z",
              type: "signal.rss",
              title: "Diplomatic statement indexed by Hugin",
              severity: "low",
              source: "rss",
              url: "",
            },
          ],
        }),
        { status: 200 },
      );
    }
    if (status !== 200) return new Response("missing", { status });
    return new Response(
      JSON.stringify({
        ...(url.includes("/api/almanac/country?")
          ? {
              scope_key: "country:UKR",
              catalog_revision: "spatial-v1-fe9828dcda05",
            }
          : {}),
        id: "GRC",
        iso3: "GRC",
        m49: "300",
        name: "Greece",
        region: "Europe",
        subregion: "Southern Europe",
        capital: { name: "Athens", lat: 37.98, lon: 23.73 },
        facts: {
          profile: [{ label: "Currency", value: "Euro (EUR)" }],
          people: [{ label: "Languages", value: "Greek" }],
          government: [],
          economy: [],
          security: [],
        },
        updated_at: "2026-05-19",
        source_note: "ODIN static country almanac",
      }),
      { status: 200 },
    );
  });
}

describe("CountryHeader", () => {
  it("renders name, capital, almanac facts, and linked signals", async () => {
    mockCountryFetch();
    render(
      <CountryHeader
        name="Greece"
        iso3="GRC"
        m49="300"
        capital={{ name: "Athens", coords: { lon: 23.7, lat: 37.9 } }}
      />,
    );

    expect(screen.getByText(/Greece/)).toBeInTheDocument();
    expect(screen.getByText(/Athens/)).toBeInTheDocument();
    expect(screen.getByText("Athens · 37.90N · 23.70E")).toBeInTheDocument();
    expect(screen.queryByText(/S2\.5 coming soon/i)).not.toBeInTheDocument();

    expect(await screen.findByText(/WorldReport/i)).toBeInTheDocument();
    expect(screen.getByText(/Euro \(EUR\)/)).toBeInTheDocument();
    expect(screen.getByText(/Diplomatic statement indexed by Hugin/)).toBeInTheDocument();
  });

  it("falls back gracefully without iso3 and uses m49", async () => {
    const fetchMock = mockCountryFetch();
    render(<CountryHeader name="W. Sahara" iso3={null} m49="732" capital={null} />);
    expect(screen.getByText(/W\. Sahara/)).toBeInTheDocument();
    expect(screen.getByText(/m49 · 732/)).toBeInTheDocument();
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith("/api/almanac/countries/732", expect.any(Object)),
    );
  });

  it("keeps country title when almanac is unavailable", async () => {
    mockCountryFetch(404);
    render(<CountryHeader name="Atlantis" iso3="ATL" m49="999" capital={null} />);
    expect(screen.getByText(/Atlantis/)).toBeInTheDocument();
    expect(await screen.findByText(/unavailable for this country/i)).toBeInTheDocument();
  });

  it("keeps canonical identity while exposing the complete Spatial inspector parity set", async () => {
    const fetchMock = mockCountryFetch();
    const scopeKey = parseScopeKeyCandidate("country:UKR");
    render(
      <SpatialCountryHeader
        selection={{ scopeKey, label: "Canonical Ukraine" }}
        query={{
          schemaVersion: 1,
          scopeKey,
          catalogRevision: parseCatalogRevision("spatial-v1-fe9828dcda05"),
          boundaryPolicy: "odin-reference-v1",
        }}
      />,
    );

    expect(screen.getByText("Canonical Ukraine")).toBeInTheDocument();
    expect(await screen.findByText(/Euro \(EUR\)/)).toBeInTheDocument();
    expect(screen.getByText("Athens · 37.98N · 23.73E")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Greece" })).toBeNull();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/almanac/country?scope_key=country%3AUKR"
        + "&catalog_revision=spatial-v1-fe9828dcda05",
      expect.any(Object),
    );
    expect(await screen.findByText(/Diplomatic statement indexed by Hugin/)).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/almanac/country/signals?scope_key=country%3AUKR"
        + "&catalog_revision=spatial-v1-fe9828dcda05&limit=5",
      expect.any(Object),
    );
    expect(screen.getByRole("button", { name: /Munin-Briefing erzeugen/i }))
      .toBeInTheDocument();
    const capabilityList = screen.getByLabelText("ODIN capabilities");
    for (const capability of ["Hugin", "Signalia", "Vectorium", "Memoria", "Fenestra"]) {
      expect(within(capabilityList).getByText(capability)).toBeInTheDocument();
    }
  });

  it("uses the shared south/west formatter in Legacy and Spatial headers", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/signals")) {
        return new Response(JSON.stringify({
          ...(url.includes("/api/almanac/country/signals")
            ? {
                scope_key: "country:ARG",
                catalog_revision: "spatial-v1-fe9828dcda05",
              }
            : {}),
          country_id: "ARG",
          items: [],
        }), {
          status: 200,
        });
      }
      return new Response(JSON.stringify({
        ...(url.includes("/api/almanac/country?")
          ? {
              scope_key: "country:ARG",
              catalog_revision: "spatial-v1-fe9828dcda05",
            }
          : {}),
        id: "ARG",
        iso3: "ARG",
        m49: "032",
        name: "Argentina",
        region: "Americas",
        subregion: "South America",
        capital: { name: "Buenos Aires", lat: -34.6, lon: -58.4 },
        facts: {
          profile: [],
          people: [],
          government: [],
          economy: [],
          security: [],
        },
        updated_at: "2026-08-10",
        source_note: "fixture",
      }), { status: 200 });
    });
    const scopeKey = parseScopeKeyCandidate("country:ARG");

    render(
      <>
        <CountryHeader
          name="Argentina"
          iso3="ARG"
          m49="032"
          capital={{ name: "Buenos Aires", coords: { lon: -58.4, lat: -34.6 } }}
        />
        <SpatialCountryHeader
          selection={{ scopeKey, label: "Canonical Argentina" }}
          query={{
            schemaVersion: 1,
            scopeKey,
            catalogRevision: parseCatalogRevision("spatial-v1-fe9828dcda05"),
            boundaryPolicy: "odin-reference-v1",
          }}
        />
      </>,
    );

    await waitFor(() => {
      expect(screen.getAllByText("Buenos Aires · 34.60S · 58.40W")).toHaveLength(2);
    });
  });
});
