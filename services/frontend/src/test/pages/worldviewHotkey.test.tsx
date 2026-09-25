import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
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

describe("WorldviewPage hotkeys", () => {
  it("preserves a typed search when temporarily focusing the map", async () => {
    renderWorldview();
    fireEvent.click(await screen.findByRole("button", { name: /expand Search/i }));
    fireEvent.change(screen.getByRole("textbox", { name: /Search entities/i }), { target: { value: "Black Sea" } });
    fireEvent.click(screen.getByRole("button", { name: /enter focus mode/i }));
    expect(screen.queryByRole("textbox", { name: /Search entities/i })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /exit focus mode/i }));
    expect(screen.getByRole("textbox", { name: /Search entities/i })).toHaveValue("Black Sea");
  });
  it("does not hijack shortcuts in editable content or with browser modifiers", async () => {
    renderWorldview();
    await screen.findByRole("button", { name: /expand Search/i });
    const editor = document.createElement("div");
    editor.setAttribute("contenteditable", "true");
    document.body.appendChild(editor);
    fireEvent.keyDown(editor, { key: "/" });
    fireEvent.keyDown(window, { key: "/", ctrlKey: true });
    expect(screen.queryByPlaceholderText(/search entities/i)).not.toBeInTheDocument();
    editor.remove();
  });

  it("restores the expanded panels after leaving focus mode", async () => {
    renderWorldview();
    fireEvent.click(await screen.findByRole("button", { name: /expand Layers/i }));
    fireEvent.click(screen.getByRole("button", { name: /enter focus mode/i }));
    expect(screen.queryByRole("region", { name: /^Layers$/i })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /exit focus mode/i }));
    expect(screen.getByRole("region", { name: /^Layers$/i })).toBeInTheDocument();
  });
  it("does NOT trigger the Search panel when / is typed inside an input", async () => {
    renderWorldview();
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
    renderWorldview();
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
