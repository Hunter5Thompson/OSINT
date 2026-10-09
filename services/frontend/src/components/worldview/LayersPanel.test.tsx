import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { LayersPanel } from "./LayersPanel";
import type { LayerVisibility } from "../../types";
import type { SpatialBoundaryProvenanceState } from "../../hooks/useSpatialBoundaryProvenance";
import type { SpatialBoundaryProvenance } from "../../spatial/catalog";
import { parseCatalogRevision } from "../../spatial/contracts";
import type { LayerSpatialStatus } from "../../spatial/layerScopePolicy";
import type { UseReconManifestResult } from "../../lib/recon/manifest";

const allOff: LayerVisibility = {
  flights: false, satellites: false, earthquakes: false, vessels: false,
  cctv: false, events: false, cables: false, pipelines: false,
  countryBorders: false, cityBuildings: false, firmsHotspots: false,
  milAircraft: false, datacenters: false, refineries: false, eonet: false, gdacs: false,
  recon: false,
  nuclearPlants: false, icbmBases: false, militaryBases: false,
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
  it.each([
    ["loading", null, "Checking scene availability…"],
    ["disabled", "not_configured", "No Recon scenes configured"],
    ["disabled", "operator_disabled", "Recon disabled by operator"],
    ["error", null, "Recon scene data unavailable"],
    ["available", null, "No Recon scenes available"],
  ] as const)("shows %s Recon availability without enabling an empty layer", (status, reason, label) => {
    const onToggle = vi.fn();
    const recon: UseReconManifestResult = {
      scenes: [], status, reason, loading: status === "loading",
      error: status === "error" ? new Error("delivery failed") : null, retry: vi.fn(),
    };
    render(<LayersPanel layers={{ ...allOff, recon: true, flights: true }}
      onToggle={onToggle} activeShader="none" onShaderChange={vi.fn()} recon={recon} />);
    expect(screen.getByText(label)).toBeInTheDocument();
    const toggle = screen.getByRole("button", { name: "recon" });
    expect(toggle).toBeDisabled();
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(toggle);
    expect(onToggle).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "flights" })).toHaveAttribute("aria-pressed", "true");
  });

  it("offers a retry for a failed Recon delivery", () => {
    const retry = vi.fn();
    render(<LayersPanel layers={allOff} onToggle={vi.fn()} activeShader="none"
      onShaderChange={vi.fn()} recon={{ scenes: [], status: "error", reason: null,
        loading: false, error: new Error("unavailable"), retry }} />);
    fireEvent.click(screen.getByRole("button", { name: "Retry Recon" }));
    expect(retry).toHaveBeenCalledTimes(1);
  });

  it("exposes the three strategic reference layers", () => {
    render(<LayersPanel layers={allOff} onToggle={() => {}} activeShader="none" onShaderChange={() => {}} />);
    for (const name of ["Nuclear Power Plants", "ICBM Bases", "Major Military Bases"]) {
      expect(screen.getByText(name)).toBeInTheDocument();
    }
  });
  it("renders registry-owned scope behavior beside runtime layers", () => {
    const spatialStatuses: Partial<Record<keyof LayerVisibility, LayerSpatialStatus>> = {
      flights: {
        render: false,
        label: "unavailable in scope",
        title: "Flights are unavailable outside world scope",
        tone: "unsupported",
      },
      satellites: {
        render: true,
        label: "global context",
        title: "Satellites remain global context",
        tone: "global",
      },
    };
    render(
      <LayersPanel
        layers={{ ...allOff, flights: true, satellites: true }}
        onToggle={() => {}}
        activeShader="none"
        onShaderChange={() => {}}
        spatialStatuses={spatialStatuses}
      />,
    );

    expect(screen.getByTestId("layer-scope-flights")).toHaveTextContent(
      "unavailable in scope",
    );
    expect(screen.getByTestId("layer-scope-satellites")).toHaveTextContent(
      "global context",
    );
    expect(screen.getByTestId("layer-scope-flights")).toHaveAttribute(
      "title",
      "Flights are unavailable outside world scope",
    );
  });

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

  it("renders all 17 LayerVisibility keys under correct groups", () => {
    render(<LayersPanel layers={allOff} onToggle={() => {}} activeShader="none" onShaderChange={() => {}} />);
    const expectedKeys = ["flights","satellites","earthquakes","vessels","cctv","events","cables","pipelines","countryBorders","cityBuildings","firmsHotspots","milAircraft","datacenters","refineries","eonet","gdacs","recon"];
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

    const disclosure = screen.getByRole("button", { name: "Data / Boundary policy" });
    expect(disclosure).toHaveAttribute("type", "button");
    expect(disclosure).toHaveAttribute("aria-expanded", "false");
    const detailsId = disclosure.getAttribute("aria-controls");
    expect(detailsId).toBeTruthy();
    const closedDetails = document.getElementById(detailsId!);
    expect(closedDetails).toBeInTheDocument();
    expect(closedDetails).toHaveAttribute("hidden");

    disclosure.focus();
    fireEvent.click(disclosure);

    expect(disclosure).toHaveAttribute("aria-expanded", "true");
    expect(document.activeElement).toBe(disclosure);
    const details = screen.getByRole("region", { name: "Boundary data and policy" });
    expect(details).toBe(closedDetails);
    expect(details).not.toHaveAttribute("hidden");
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

    fireEvent.click(screen.getByRole("button", { name: "Data / Boundary policy" }));
    expect(screen.getByText("<strong>reviewed attribution</strong>")).toBeInTheDocument();
    expect(container.querySelector("strong")).toBeNull();
  });
});
