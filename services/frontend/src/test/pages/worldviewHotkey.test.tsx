import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

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

describe("WorldviewPage hotkeys", () => {
  it("does NOT trigger the Search panel when / is typed inside an input", async () => {
    render(<WorldviewPage />);
    // Expand the search panel first so its <input> is in the DOM.
    fireEvent.click(await screen.findByRole("button", { name: /expand Search/i }));
    const searchInput = await screen.findByPlaceholderText(/search entities/i);
    searchInput.focus();

    // Typing "/" inside an input must not preventDefault or re-trigger panel logic.
    const event = new KeyboardEvent("keydown", {
      key: "/",
      bubbles: true,
      cancelable: true,
    });
    searchInput.dispatchEvent(event);

    // If the hotkey handler called preventDefault, the event would be flagged.
    expect(event.defaultPrevented).toBe(false);
    // Panel is expanded (we opened it via the tab click) and must stay that way.
    expect(screen.getByPlaceholderText(/search entities/i)).toBeInTheDocument();
  });

  it("DOES trigger the Search panel when / is pressed outside any input", async () => {
    render(<WorldviewPage />);
    // Collapsed by default — the expand button is visible.
    expect(await screen.findByRole("button", { name: /expand Search/i })).toBeInTheDocument();

    const event = new KeyboardEvent("keydown", {
      key: "/",
      bubbles: true,
      cancelable: true,
    });
    window.dispatchEvent(event);

    expect(event.defaultPrevented).toBe(true);
    await waitFor(() => expect(screen.getByPlaceholderText(/search entities/i)).toBeInTheDocument());
  });
});
