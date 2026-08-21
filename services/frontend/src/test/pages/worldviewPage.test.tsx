import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

vi.mock("../../components/globe/GlobeViewer", () => ({
  GlobeViewer: ({ onViewerReady }: { onViewerReady: (v: unknown) => void }) => {
    onViewerReady(null);
    return <div data-testid="globe-viewer" />;
  },
}));
vi.mock("../../components/globe/PerformanceGuard", () => ({
  PerformanceGuard: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  usePerformance: () => ({ fps: 60, degradation: 0 }),
}));
vi.mock("../../services/api", () => ({
  getConfig: vi.fn().mockResolvedValue({
    cesium_ion_token: "",
    default_layers: {},
    api_version: "v1",
  }),
  getHotspots: vi.fn().mockResolvedValue([]),
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
      requested_scope_key: null,
      catalog_revision: null,
      derivation_revision: null,
      boundary_policy: null,
      relation: "occurs-in",
      mode: "global",
      completeness: "complete",
      included_count: 0,
      excluded_unlocated_count: 0,
      excluded_outside_count: 0,
      excluded_conflict_count: 0,
      excluded_stale_revision_count: 0,
      excluded_unsupported_count: 0,
    },
  }),
}));
vi.mock("../../spatial/react", () => ({
  SPATIAL_SCOPE_ENABLED: false,
  SpatialScopeProvider: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="spatial-scope-provider">{children}</div>
  ),
  useOptionalSpatialScope: () => null,
}));

import { WorldviewPage } from "../../pages/WorldviewPage";
import { ReconProvider } from "../../state/ReconContext";

function renderWorldview() {
  return render(
    <MemoryRouter initialEntries={["/worldview"]}>
      <ReconProvider>
        <WorldviewPage />
      </ReconProvider>
    </MemoryRouter>,
  );
}

describe("WorldviewPage", () => {
  it("renders the globe and four overlay panel tabs/expanded forms", async () => {
    renderWorldview();
    expect(await screen.findByTestId("spatial-scope-provider")).toBeInTheDocument();
    expect(await screen.findByTestId("globe-viewer")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /expand Layers/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /expand Search/i })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: /Ticker/i })).toBeInTheDocument();
  });

  it("does not render legacy ClockBar / StatusBar / ThreatRegister", () => {
    renderWorldview();
    expect(screen.queryByTestId("clock-bar")).not.toBeInTheDocument();
    expect(screen.queryByTestId("status-bar")).not.toBeInTheDocument();
    expect(screen.queryByTestId("threat-register")).not.toBeInTheDocument();
  });
});
