import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

const scope = {
  phase: "ready" as const,
  stateRevision: 2,
  current: {
    key: "country:UKR",
    kind: "country" as const,
    label: "Ukraine",
    shortLabel: "Ukraine",
    parentKey: "world",
    childrenAvailable: true,
    presentation: "boundary" as const,
  },
  path: [
    {
      key: "world",
      kind: "world" as const,
      label: "World",
      shortLabel: "World",
      parentKey: null,
      childrenAvailable: true,
      presentation: "boundary" as const,
    },
    {
      key: "country:UKR",
      kind: "country" as const,
      label: "Ukraine",
      shortLabel: "Ukraine",
      parentKey: "world",
      childrenAvailable: true,
      presentation: "boundary" as const,
    },
  ],
  query: {
    schemaVersion: 1 as const,
    scopeKey: "country:UKR",
    catalogRevision: "spatial-v1-fe9828dcda05",
    boundaryPolicy: "odin-reference-v1",
  },
  pending: null,
  problem: null,
  visual: { phase: "ready" as const, stateRevision: 2 },
  enter: vi.fn(),
  ascend: vi.fn(),
  prefetch: vi.fn(),
  cancelPending: vi.fn(),
  rehydrate: vi.fn(),
};

vi.mock("../../spatial/react", () => ({
  SPATIAL_SCOPE_ENABLED: true,
  SpatialScopeProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  useOptionalSpatialScope: () => scope,
  useSpatialScope: () => scope,
}));

vi.mock("../../spatial/containment", () => ({
  createSpatialContainmentController: () => {
    const snapshot = {
      phase: "ready" as const,
      stateRevision: 2,
      contains: () => "inside" as const,
    };
    return {
      getSnapshot: () => snapshot,
      subscribe: () => () => undefined,
      commit: vi.fn(),
      reset: vi.fn(),
      dispose: vi.fn(),
    };
  },
}));

vi.mock("../../components/globe/GlobeViewer", () => ({
  GlobeViewer: () => <div data-testid="globe-viewer" />,
}));

vi.mock("../../components/globe/PerformanceGuard", () => ({
  PerformanceGuard: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  usePerformance: () => ({ fps: 60, degradation: 0 }),
}));

vi.mock("../../components/layers/FlightLayer", () => ({
  FlightLayer: ({ visible }: { visible: boolean }) => (
    <div data-testid="flight-policy">{String(visible)}</div>
  ),
}));

vi.mock("../../components/layers/SatelliteLayer", () => ({
  SatelliteLayer: ({ visible }: { visible: boolean }) => (
    <div data-testid="satellite-policy">{String(visible)}</div>
  ),
}));

vi.mock("../../components/layers/EarthquakeLayer", () => ({
  EarthquakeLayer: ({
    visible,
    spatialAdapter,
  }: {
    visible: boolean;
    spatialAdapter?: unknown;
  }) => (
    <div data-testid="earthquake-policy">
      {String(visible)}:{spatialAdapter === undefined ? "none" : "adapter"}
    </div>
  ),
}));

vi.mock("../../services/api", () => ({
  getConfig: vi.fn().mockResolvedValue({
    cesium_ion_token: "",
    default_layers: {},
    api_version: "v1",
  }),
  getFlights: vi.fn().mockResolvedValue([]),
  getSatellites: vi.fn().mockResolvedValue([]),
  getEarthquakes: vi.fn().mockResolvedValue([]),
  getCables: vi.fn().mockResolvedValue({ cables: [], landing_points: [] }),
  getVessels: vi.fn().mockResolvedValue([]),
  getFIRMSHotspots: vi.fn().mockResolvedValue([]),
  getAircraftTracks: vi.fn().mockResolvedValue([]),
  getEONETEvents: vi.fn().mockResolvedValue([]),
  getGDACSEvents: vi.fn().mockResolvedValue([]),
  getTimeWindow: vi.fn(),
  getTimeHistogram: vi.fn().mockResolvedValue({
    t_start: "a",
    t_end: "b",
    bucket_ms: 1,
    buckets: [],
    notables: [],
    geo_events: [],
    total_count: 0,
    geo_located_count: 0,
    geo_truncated: false,
    spatial_application: {
      schema_version: 1,
      requested_scope_key: "country:UKR",
      catalog_revision: "spatial-v1-fe9828dcda05",
      derivation_revision: null,
      boundary_policy: "odin-reference-v1",
      relation: "occurs-in",
      mode: "bbox_approximate",
      completeness: "complete",
      included_count: 0,
      excluded_unlocated_count: 0,
      excluded_conflict_count: 0,
      excluded_stale_revision_count: 0,
      excluded_unsupported_count: 0,
    },
  }),
}));

import { WorldviewPage } from "../../pages/WorldviewPage";
import { ReconProvider } from "../../state/ReconContext";

describe("WorldviewPage spatial layer policy wiring", () => {
  it("fails unsupported layers closed while retaining declared context and point paths", async () => {
    render(
      <MemoryRouter initialEntries={["/worldview"]}>
        <ReconProvider>
          <WorldviewPage />
        </ReconProvider>
      </MemoryRouter>,
    );

    expect(await screen.findByTestId("flight-policy")).toHaveTextContent("false");
    expect(screen.getByTestId("satellite-policy")).toHaveTextContent("true");
    expect(screen.getByTestId("earthquake-policy")).toHaveTextContent("true:adapter");

    fireEvent.click(screen.getByRole("button", { name: /expand Layers/i }));
    expect(screen.getByTestId("layer-scope-flights")).toHaveTextContent(
      "unavailable in scope",
    );
    expect(screen.getByTestId("layer-scope-satellites")).toHaveTextContent(
      "global context",
    );
    expect(screen.getByTestId("layer-scope-earthquakes")).toHaveTextContent(
      "strict · point boundary",
    );
  });
});
