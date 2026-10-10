import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { LayerVisibility } from "../../types";
import { LayersPanel } from "./LayersPanel";

const layers: LayerVisibility = { countryBorders: false, cityBuildings: false,
  flights: true, satellites: false, earthquakes: false, vessels: false, cctv: false,
  events: false, firmsHotspots: false, milAircraft: false, datacenters: false,
  refineries: false, nuclearPlants: false, icbmBases: false, militaryBases: false,
  eonet: false, gdacs: false, recon: false, cables: false, pipelines: false };

describe("flight source and rendering status", () => {
  const density = { total: 1503, valid: 1500, invalid: 2, duplicates: 1,
    inView: 1000, shown: 250, omitted: 750, band: "GLOBE" as const, cap: 250 };
  it("shows rendering limits, viewport exclusions and malformed rows separately", () => {
    render(<LayersPanel layers={layers} onToggle={vi.fn()} activeShader="none" onShaderChange={vi.fn()}
      flightStatus={{ density, loading: false, error: null, lastUpdate: new Date("2026-10-10T00:00:00Z") }} />);
    const status = screen.getByRole("status", { name: "Flight source and rendering" });
    expect(status).toHaveTextContent("250/1000 im Ausschnitt · 750 durch Darstellungslimit ausgeblendet");
    expect(status).toHaveTextContent("500 außerhalb · 2 ungültig · 1 doppelt");
    expect(status).toHaveTextContent("Clientabruf UTC: 2026-10-10T00:00:00.000Z");
    expect(status).toHaveTextContent("Keine globale Vollständigkeit");
  });
  it("marks failed refresh of usable data as a previous client snapshot", () => {
    render(<LayersPanel layers={layers} onToggle={vi.fn()} activeShader="none" onShaderChange={vi.fn()}
      flightStatus={{ density, loading: false, error: "unavailable", lastUpdate: new Date("2026-10-10T00:00:00Z") }} />);
    expect(screen.getByRole("status", { name: "Flight source and rendering" }))
      .toHaveTextContent("Abruf fehlgeschlagen · Vorheriger Clientstand");
  });
  it("distinguishes healthy empty from an unavailable first request", () => {
    const { rerender } = render(<LayersPanel layers={layers} onToggle={vi.fn()} activeShader="none" onShaderChange={vi.fn()}
      flightStatus={{ density: null, loading: false, error: "unavailable", lastUpdate: null }} />);
    expect(screen.getByRole("status", { name: "Flight source and rendering" })).toHaveTextContent("Nicht verfügbar");
    expect(screen.getByRole("status", { name: "Flight source and rendering" })).not.toHaveTextContent("Keine Kontakte");
    rerender(<LayersPanel layers={layers} onToggle={vi.fn()} activeShader="none" onShaderChange={vi.fn()}
      flightStatus={{ density: { ...density, total: 0, valid: 0, invalid: 0, duplicates: 0, inView: 0, shown: 0, omitted: 0 },
        loading: false, error: null, lastUpdate: new Date("2026-10-10T00:00:00Z") }} />);
    expect(screen.getByRole("status", { name: "Flight source and rendering" })).toHaveTextContent("Keine Kontakte im letzten Clientabruf");
  });
});

it("shows event aggregates and withheld members as distinct quantities", () => {
  render(<LayersPanel layers={{ ...layers, events: true }} onToggle={vi.fn()} activeShader="none" onShaderChange={vi.fn()}
    eventDensity={{ total: 2000, valid: 1990, invalid: 2, unlocated: 5, duplicates: 3,
      inView: 1800, outsideWindow: 100, outsideView: 90, represented: 1500, symbols: 250,
      aggregates: 240, omitted: 300, band: "GLOBE", cap: 250 }} />);
  const status = screen.getByRole("status", { name: "Event rendering" });
  expect(status).toHaveTextContent("250 Symbole · 240 Aggregate · 1500/1800 Ereignisse im Ausschnitt");
  expect(status).toHaveTextContent("300 durch Darstellungslimit ausgeblendet");
  expect(status).toHaveTextContent("90 außerhalb · 100 Zeitfenster/Datum · 5 ohne Ort · 2 ungültig · 3 doppelt");
});
