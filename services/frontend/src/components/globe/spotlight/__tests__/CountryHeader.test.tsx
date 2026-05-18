import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CountryHeader } from "../CountryHeader";

afterEach(() => {
  vi.restoreAllMocks();
});

function mockCountryFetch(status = 200) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/signals")) {
      return new Response(
        JSON.stringify({
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
});
