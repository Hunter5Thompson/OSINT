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
  it("groups toggles by dimension and marks active layer as pressed", () => {
    render(
      <LayersPanel
        layers={{ ...allOff, flights: true }}
        onToggle={vi.fn()}
        activeShader="none"
        onShaderChange={vi.fn()}
      />,
    );
    expect(screen.getByText(/Transport/i)).toBeInTheDocument();
    expect(screen.getByText(/Incidents/i)).toBeInTheDocument();
    expect(screen.getByText(/Infrastructure/i)).toBeInTheDocument();
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
});
