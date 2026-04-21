import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { OperationsPanel } from "../OperationsPanel";
import type { LayerVisibility } from "../../../types";

const baseLayers: LayerVisibility = {
  flights: true, satellites: true, earthquakes: true, vessels: false,
  cctv: false, events: false, cables: false, pipelines: false,
  countryBorders: true, cityBuildings: true,
  firmsHotspots: true, milAircraft: true,
  datacenters: false, refineries: false,
  eonet: false, gdacs: false,
};

describe("OperationsPanel — EONET/GDACS layers", () => {
  it("renders EONET EVENTS and GDACS ALERTS toggles", () => {
    render(
      <OperationsPanel
        layers={baseLayers}
        onToggleLayer={vi.fn()}
        activeShader="none"
        onShaderChange={vi.fn()}
      />,
    );
    expect(screen.getByText("EONET EVENTS")).toBeDefined();
    expect(screen.getByText("GDACS ALERTS")).toBeDefined();
  });

  it("calls onToggleLayer with correct keys", () => {
    const toggle = vi.fn();
    render(
      <OperationsPanel
        layers={baseLayers}
        onToggleLayer={toggle}
        activeShader="none"
        onShaderChange={vi.fn()}
      />,
    );
    fireEvent.click(screen.getAllByRole("button", { name: "EONET EVENTS" }).at(-1)!);
    expect(toggle).toHaveBeenCalledWith("eonet");
    fireEvent.click(screen.getAllByRole("button", { name: "GDACS ALERTS" }).at(-1)!);
    expect(toggle).toHaveBeenCalledWith("gdacs");
  });
});
