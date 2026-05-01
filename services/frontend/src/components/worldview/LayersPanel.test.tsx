import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { LayersPanel } from "./LayersPanel";
import type { LayerVisibility } from "../../types";

const allOff: LayerVisibility = {
  flights: false, satellites: false, earthquakes: false, vessels: false,
  cctv: false, events: false, cables: false, pipelines: false,
  countryBorders: false, cityBuildings: false, firmsHotspots: false,
  milAircraft: false, datacenters: false, refineries: false, eonet: false, gdacs: false,
};

describe("LayersPanel", () => {
  it("renders groups and marks active layer as pressed", () => {
    render(
      <LayersPanel
        layers={{ ...allOff, flights: true }}
        onToggle={vi.fn()}
        activeShader="none"
        onShaderChange={vi.fn()}
      />,
    );
    expect(screen.getByText(/C · signal · glyphs/i)).toBeInTheDocument();
    expect(screen.getByText(/C · signal · network/i)).toBeInTheDocument();
    expect(screen.getByText(/B · earth/i)).toBeInTheDocument();
    expect(screen.getByText(/Visual Filter/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /flights/i })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("calls onToggle with the layer key when clicked", () => {
    const onToggle = vi.fn();
    render(
      <LayersPanel
        layers={allOff}
        onToggle={onToggle}
        activeShader="none"
        onShaderChange={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /satellites/i }));
    expect(onToggle).toHaveBeenCalledWith("satellites");
  });

  it("renders 4 groups with §-eyebrow", () => {
    render(<LayersPanel layers={allOff} onToggle={() => {}} activeShader="none" onShaderChange={() => {}} />);
    expect(screen.getByText(/A · sky/i)).toBeInTheDocument();
    expect(screen.getByText(/B · earth/i)).toBeInTheDocument();
    expect(screen.getByText(/C · signal · glyphs/i)).toBeInTheDocument();
    expect(screen.getByText(/D · lens & chrome/i)).toBeInTheDocument();
  });

  it("renders all 16 LayerVisibility keys under correct groups", () => {
    render(<LayersPanel layers={allOff} onToggle={() => {}} activeShader="none" onShaderChange={() => {}} />);
    const expectedKeys = ["flights","satellites","earthquakes","vessels","cctv","events","cables","pipelines","countryBorders","cityBuildings","firmsHotspots","milAircraft","datacenters","refineries","eonet","gdacs"];
    for (const k of expectedKeys) {
      expect(screen.getByTestId(`layer-toggle-${k}`)).toBeInTheDocument();
    }
  });
});
