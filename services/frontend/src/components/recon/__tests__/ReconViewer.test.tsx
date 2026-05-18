import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ReconProvider, useRecon } from "../../../state/ReconContext";
import { ReconViewer } from "../ReconViewer";

// vi.mock factories are HOISTED above imports — they cannot reference
// module-scope `let`/`const` declarations (TDZ at hoist time). The
// canonical workaround is `vi.hoisted()` for any mock state shared
// between the factory and the test bodies.
const mocks = vi.hoisted(() => {
  const defaultScenes = [{
    scene_id: "jax_068",
    hf_filename: "JAX_068_final.ply",
    display_name: "Jacksonville District 068",
    ply_url: "/static/recon/JAX_068_final.ply?sha=" + "a".repeat(64),
    ply_size_bytes: 1000,
    bounds: { center_lat: 30.33, center_lon: -81.65, radius_m: 350 },
    bounds_source: "spacenet_metadata" as const,
    default_camera: {
      position: [0, 0, 200] as [number, number, number],
      look_at: [0, 0, 0] as [number, number, number],
      fov_deg: 60,
    },
    attribution: "Reconstruction: Skyfall-GS — Apache 2.0. Source imagery: SpaceNet 4.",
    source: "skyfall_gs_hf",
  }];
  const largeScene = {
    scene_id: "nyc_219",
    hf_filename: "NYC_219_final.ply",
    display_name: "New York City Tile 219",
    ply_url: "/static/recon/NYC_219_final.ply?sha=" + "c".repeat(64),
    ply_size_bytes: 324_186_833,
    bounds: { center_lat: 40.758, center_lon: -73.985, radius_m: 500 },
    bounds_source: "spacenet_metadata" as const,
    default_camera: {
      position: [0, 0, 500] as [number, number, number],
      look_at: [0, 0, 0] as [number, number, number],
      fov_deg: 60,
    },
    attribution: "x",
    source: "skyfall_gs_hf",
  };
  return {
    handle: {
      dispose: vi.fn(),
      captureScreenshot: vi.fn(async () =>
        new Blob([new Uint8Array([137, 80, 78, 71])], { type: "image/png" })
      ),
      getCanvas: () => document.createElement("canvas"),
      move: vi.fn(),
      look: vi.fn(),
    },
    defaultScenes,
    largeScene,
    state: {
      rendererBehavior: "ok" as "ok" | "error",
      scenes: defaultScenes as typeof defaultScenes,
    },
  };
});

vi.mock("../renderer", () => ({
  loadDefaultSplatRenderer: vi.fn(async () => ({
    render: vi.fn(async (_canvas, opts) => {
      if (mocks.state.rendererBehavior === "error") {
        opts.onError?.(new Error("simulated PLY parse error"));
        throw new Error("simulated PLY parse error");
      }
      opts.onProgress?.({ loaded: 100, total: 1000 });
      opts.onFirstFrame?.();
      return mocks.handle;
    }),
  })),
}));

vi.mock("../../../lib/recon/manifest", () => ({
  useReconManifest: () => ({
    scenes: mocks.state.scenes,
    loading: false,
    error: null,
  }),
  _resetReconManifestCache: () => {},
}));

import { waitFor } from "@testing-library/react";
import { beforeEach } from "vitest";

function Opener() {
  const { openScene } = useRecon();
  return <button onClick={() => openScene("jax_068")}>open</button>;
}

beforeEach(() => {
  mocks.state.rendererBehavior = "ok";
  mocks.state.scenes = mocks.defaultScenes;
  mocks.handle.dispose.mockClear();
  mocks.handle.captureScreenshot.mockClear();
  // Default: fast connection so BandwidthGuard auto-passes children through.
  Object.defineProperty(navigator, "connection",
    { value: { effectiveType: "4g" }, configurable: true });
});

afterEach(() => {
  Object.defineProperty(navigator, "connection",
    { value: undefined, configurable: true });
});

describe("ReconViewer", () => {
  it("does not render when no active scene", () => {
    render(<ReconProvider><Opener /><ReconViewer /></ReconProvider>);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("renders modal + attribution footer when scene is opened", async () => {
    render(<ReconProvider><Opener /><ReconViewer /></ReconProvider>);
    fireEvent.click(screen.getByText("open"));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText(/Skyfall-GS/)).toBeInTheDocument();
    expect(screen.getByText(/SpaceNet 4/)).toBeInTheDocument();
  });

  it("closes on ESC", () => {
    render(<ReconProvider><Opener /><ReconViewer /></ReconProvider>);
    fireEvent.click(screen.getByText("open"));
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("renders Capture button and downloads PNG when clicked", async () => {
    const createObjectURL = vi.fn(() => "blob:fake");
    const revokeObjectURL = vi.fn();
    Object.defineProperty(URL, "createObjectURL", { value: createObjectURL, configurable: true });
    Object.defineProperty(URL, "revokeObjectURL", { value: revokeObjectURL, configurable: true });

    render(<ReconProvider><Opener /><ReconViewer /></ReconProvider>);
    fireEvent.click(screen.getByText("open"));
    // Wait for the renderer to finish + Capture button to mount
    await waitFor(() => screen.getByRole("button", { name: /capture/i }));
    fireEvent.click(screen.getByRole("button", { name: /capture/i }));
    await waitFor(() => expect(mocks.handle.captureScreenshot).toHaveBeenCalled());
    expect(createObjectURL).toHaveBeenCalled();
  });

  it("shows error message and Retry button when renderer fails", async () => {
    mocks.state.rendererBehavior = "error";
    render(<ReconProvider><Opener /><ReconViewer /></ReconProvider>);
    fireEvent.click(screen.getByText("open"));
    await waitFor(() => expect(screen.getByText(/simulated PLY parse error/i)).toBeInTheDocument());
    expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument();
  });

  it("Retry re-runs the renderer", async () => {
    mocks.state.rendererBehavior = "error";
    render(<ReconProvider><Opener /><ReconViewer /></ReconProvider>);
    fireEvent.click(screen.getByText("open"));
    await waitFor(() => screen.getByRole("button", { name: /retry/i }));
    mocks.state.rendererBehavior = "ok";
    fireEvent.click(screen.getByRole("button", { name: /retry/i }));
    await waitFor(() => expect(screen.queryByText(/simulated PLY parse error/i)).toBeNull());
  });

  it("disposes the handle on close", async () => {
    render(<ReconProvider><Opener /><ReconViewer /></ReconProvider>);
    fireEvent.click(screen.getByText("open"));
    await waitFor(() => screen.getByRole("button", { name: /close/i }));
    fireEvent.click(screen.getByRole("button", { name: /close/i }));
    await waitFor(() => expect(mocks.handle.dispose).toHaveBeenCalled());
  });

  it("on metered connection: renderer does NOT start until Load anyway is clicked", async () => {
    Object.defineProperty(navigator, "connection",
      { value: { effectiveType: "3g" }, configurable: true });
    const renderer = (await import("../renderer")) as {
      loadDefaultSplatRenderer: ReturnType<typeof vi.fn>;
    };
    const renderSpy = vi.fn(async (_canvas, opts) => {
      opts.onFirstFrame?.();
      return mocks.handle;
    });
    renderer.loadDefaultSplatRenderer.mockResolvedValue({ render: renderSpy });

    render(<ReconProvider><Opener /><ReconViewer /></ReconProvider>);
    fireEvent.click(screen.getByText("open"));

    // Bandwidth dialog visible; canvas + renderer not invoked yet
    expect(screen.getByRole("button", { name: /load anyway/i })).toBeInTheDocument();
    expect(renderSpy).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: /load anyway/i }));
    await waitFor(() => expect(renderSpy).toHaveBeenCalledTimes(1));
  });

  it("shows LARGE badge for scenes over 300 MB", () => {
    // Swap the manifest hook's data BEFORE rendering. The vi.mock factory
    // reads mocks.state.scenes by reference, so mutating it here makes the
    // next useReconManifest() call see nyc_219 without re-importing modules.
    mocks.state.scenes = [mocks.largeScene];

    function OpenLarge() {
      const { openScene } = useRecon();
      return <button onClick={() => openScene("nyc_219")}>open-large</button>;
    }

    render(<ReconProvider><OpenLarge /><ReconViewer /></ReconProvider>);
    fireEvent.click(screen.getByText("open-large"));
    expect(screen.getByLabelText(/large scene/i)).toBeInTheDocument();
    // 324_186_833 / (1024*1024) rounds to 309
    expect(screen.getByText(/LARGE — 309 MB/)).toBeInTheDocument();
  });

  it("does NOT show LARGE badge for scenes under 300 MB", () => {
    render(<ReconProvider><Opener /><ReconViewer /></ReconProvider>);
    fireEvent.click(screen.getByText("open"));
    expect(screen.queryByLabelText(/large scene/i)).toBeNull();
  });
});
