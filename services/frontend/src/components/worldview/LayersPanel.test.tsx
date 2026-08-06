import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { LayersPanel } from "./LayersPanel";
import type { LayerVisibility } from "../../types";
import type { SpatialBoundaryProvenanceState } from "../../hooks/useSpatialBoundaryProvenance";
import type { SpatialBoundaryProvenance } from "../../spatial/catalog";
import { parseCatalogRevision } from "../../spatial/contracts";

const allOff: LayerVisibility = {
  flights: false, satellites: false, earthquakes: false, vessels: false,
  cctv: false, events: false, cables: false, pipelines: false,
  countryBorders: false, cityBuildings: false, firmsHotspots: false,
  milAircraft: false, datacenters: false, refineries: false, eonet: false, gdacs: false,
};

const provenanceData: SpatialBoundaryProvenance = {
  boundaryPolicy: "odin-reference-v1",
  catalogRevision: parseCatalogRevision("spatial-v1-fe9828dcda05"),
  representationNote: "ODIN reference boundary representation; disputed claims are contextual.",
  sources: [
    {
      sourceId: "geoboundaries-gbopen-ukr-admin1",
      release: "2023-12-12+9469f09592ce",
      licenseId: "CC-BY-4.0",
      text: "geoBoundaries / William & Mary geoLab",
    },
    {
      sourceId: "natural-earth-admin0",
      release: "5.1.2+f1890d9f152c",
      licenseId: "public-domain",
      text: "Natural Earth",
    },
  ],
};

const readyProvenance: SpatialBoundaryProvenanceState = {
  status: "ready",
  error: null,
  data: provenanceData,
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

  it("opens accessible cartographic policy details for the committed revision", () => {
    render(
      <LayersPanel
        layers={allOff}
        onToggle={() => {}}
        activeShader="none"
        onShaderChange={() => {}}
        spatialProvenance={readyProvenance}
      />,
    );

    const link = screen.getByRole("link", { name: "Data / Boundary policy" });
    expect(link).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(link);

    expect(link).toHaveAttribute("aria-expanded", "true");
    const details = screen.getByRole("region", { name: "Boundary data and policy" });
    expect(details).toHaveTextContent("odin-reference-v1");
    expect(details).toHaveTextContent("spatial-v1-fe9828dcda05");
    expect(details).toHaveTextContent(
      "ODIN reference boundary representation; disputed claims are contextual.",
    );
    expect(details).toHaveTextContent("2023-12-12+9469f09592ce");
    expect(details).toHaveTextContent("CC-BY-4.0");
    expect(details).toHaveTextContent("geoBoundaries / William & Mary geoLab");
    expect(details).toHaveTextContent("5.1.2+f1890d9f152c");
    expect(details).toHaveTextContent("Natural Earth");
  });

  it("renders attribution values only as escaped text", () => {
    const unsafeFixture: SpatialBoundaryProvenanceState = {
      ...readyProvenance,
      data: {
        ...provenanceData,
        sources: [{
          ...provenanceData.sources[0]!,
          text: "<strong>reviewed attribution</strong>",
        }],
      },
    };
    const { container } = render(
      <LayersPanel
        layers={allOff}
        onToggle={() => {}}
        activeShader="none"
        onShaderChange={() => {}}
        spatialProvenance={unsafeFixture}
      />,
    );

    fireEvent.click(screen.getByRole("link", { name: "Data / Boundary policy" }));
    expect(screen.getByText("<strong>reviewed attribution</strong>")).toBeInTheDocument();
    expect(container.querySelector("strong")).toBeNull();
  });
});
