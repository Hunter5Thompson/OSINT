import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

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
}));

import { WorldviewPage } from "../../pages/WorldviewPage";

describe("WorldviewPage", () => {
  it("renders the globe and four overlay panel tabs/expanded forms", async () => {
    render(<WorldviewPage />);
    expect(await screen.findByTestId("globe-viewer")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /expand Layers/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /expand Search/i })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: /Ticker/i })).toBeInTheDocument();
  });

  it("does not render legacy ClockBar / StatusBar / ThreatRegister", () => {
    render(<WorldviewPage />);
    expect(screen.queryByTestId("clock-bar")).not.toBeInTheDocument();
    expect(screen.queryByTestId("status-bar")).not.toBeInTheDocument();
    expect(screen.queryByTestId("threat-register")).not.toBeInTheDocument();
  });
});
