import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { OperationsPanel } from "../OperationsPanel";
import type { LayerVisibility } from "../../../types";

const baseLayers: LayerVisibility = {
  flights: true, satellites: true, earthquakes: true, vessels: false,
  cctv: false, events: false, cables: false, pipelines: false,
  firmsHotspots: true, milAircraft: true,
  datacenters: false, refineries: false,
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
    fireEvent.click(screen.getByText("DATACENTERS"));
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
    fireEvent.click(screen.getByText("REFINERIES"));
    expect(toggle).toHaveBeenCalledWith("refineries");
  });
});
