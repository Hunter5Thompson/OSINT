import { describe, it, expect, vi } from "vitest";
import { render } from "@testing-library/react";
import * as Cesium from "cesium";
import { ReconLayer } from "../ReconLayer";
import type { ReconScene } from "../../../lib/recon/types";

function fakeViewer(): Cesium.Viewer {
  const primitives = { add: vi.fn((p: unknown) => p), remove: vi.fn() };
  const canvas = document.createElement("canvas");
  return {
    scene: {
      primitives,
      requestRender: vi.fn(),
      frameState: { mode: Cesium.SceneMode.SCENE3D },
      pick: vi.fn(() => undefined),
    },
    canvas,
    isDestroyed: () => false,
  } as unknown as Cesium.Viewer;
}

const sample = (id: string, lat: number, lon: number): ReconScene => ({
  scene_id: id,
  hf_filename: `${id.toUpperCase()}_final.ply`,
  display_name: id,
  ply_url: `/static/recon/${id}.ply`,
  ply_size_bytes: 1,
  bounds: { center_lat: lat, center_lon: lon, radius_m: 100 },
  bounds_source: "spacenet_metadata",
  default_camera: { position: [0, 0, 200], look_at: [0, 0, 0], fov_deg: 60 },
  attribution: "x",
  source: "skyfall_gs_hf",
});

describe("ReconLayer", () => {
  it("renders without throwing for two scenes", () => {
    const viewer = fakeViewer();
    const onSelect = vi.fn();
    render(
      <ReconLayer
        viewer={viewer}
        scenes={[sample("a", 30, -81), sample("b", 40, -74)]}
        visible
        onSelect={onSelect}
      />
    );
    expect((viewer.scene.primitives as unknown as { add: ReturnType<typeof vi.fn> }).add).toHaveBeenCalled();
  });

  it("does nothing when viewer is null", () => {
    const onSelect = vi.fn();
    render(
      <ReconLayer
        viewer={null}
        scenes={[sample("a", 30, -81)]}
        visible
        onSelect={onSelect}
      />
    );
    expect(onSelect).not.toHaveBeenCalled();
  });
});
