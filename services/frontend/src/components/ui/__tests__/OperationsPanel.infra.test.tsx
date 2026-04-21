import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { OperationsPanel } from "../OperationsPanel";
import type { LayerVisibility } from "../../../types";

const baseLayers: LayerVisibility = {
  flights: true, satellites: true, earthquakes: true, vessels: false,
  cctv: false, events: false, cables: false, pipelines: false,
  countryBorders: true, cityBuildings: true,
  firmsHotspots: true, milAircraft: true,
  datacenters: false, refineries: false, eonet: false, gdacs: false,
};

describe("OperationsPanel — infrastructure layers", () => {
  it("renders DATACENTERS and REFINERIES toggles", () => {
    render(
      <OperationsPanel
        layers={baseLayers}
        onToggleLayer={vi.fn()}
        activeShader="none"
        onShaderChange={vi.fn()}
      />,
    );
    expect(screen.getByText("DATACENTERS")).toBeDefined();
    expect(screen.getByText("REFINERIES")).toBeDefined();
    expect(screen.getByText("COUNTRY BORDERS")).toBeDefined();
    expect(screen.getByText("3D BUILDINGS")).toBeDefined();
  });

  it("calls onToggleLayer with 'datacenters' when clicked", () => {
    const toggle = vi.fn();
    render(
      <OperationsPanel
        layers={baseLayers}
        onToggleLayer={toggle}
        activeShader="none"
        onShaderChange={vi.fn()}
      />,
    );
    fireEvent.click(screen.getAllByRole("button", { name: "DATACENTERS" }).at(-1)!);
    expect(toggle).toHaveBeenCalledWith("datacenters");
  });

  it("calls onToggleLayer with 'refineries' when clicked", () => {
    const toggle = vi.fn();
    render(
      <OperationsPanel
        layers={baseLayers}
        onToggleLayer={toggle}
        activeShader="none"
        onShaderChange={vi.fn()}
      />,
    );
    fireEvent.click(screen.getAllByRole("button", { name: "REFINERIES" }).at(-1)!);
    expect(toggle).toHaveBeenCalledWith("refineries");
  });

  it("calls onToggleLayer for globe visuals", () => {
    const toggle = vi.fn();
    render(
      <OperationsPanel
        layers={baseLayers}
        onToggleLayer={toggle}
        activeShader="none"
        onShaderChange={vi.fn()}
      />,
    );
    fireEvent.click(screen.getAllByRole("button", { name: "COUNTRY BORDERS" }).at(-1)!);
    expect(toggle).toHaveBeenCalledWith("countryBorders");
    fireEvent.click(screen.getAllByRole("button", { name: "3D BUILDINGS" }).at(-1)!);
    expect(toggle).toHaveBeenCalledWith("cityBuildings");
  });
});
