import type { ReconScene, ReconScenesResponse } from "./types";

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function finite(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function vector3(value: unknown): value is [number, number, number] {
  return Array.isArray(value) && value.length === 3 && value.every(finite);
}

function scene(value: unknown): value is ReconScene {
  if (!record(value)) return false;
  const bounds = value.bounds;
  const camera = value.default_camera;
  return typeof value.scene_id === "string"
    && typeof value.hf_filename === "string"
    && typeof value.display_name === "string"
    && typeof value.ply_url === "string"
    && typeof value.ply_sha256 === "string"
    && /^[a-f0-9]{64}$/.test(value.ply_sha256)
    && value.ply_url.endsWith(`?sha=${value.ply_sha256}`)
    && finite(value.ply_size_bytes) && Number.isInteger(value.ply_size_bytes)
    && value.ply_size_bytes > 0
    && (value.bounds_source === "spacenet_metadata" || value.bounds_source === "manual")
    && record(bounds)
    && finite(bounds.center_lat) && Math.abs(bounds.center_lat) <= 90
    && finite(bounds.center_lon) && Math.abs(bounds.center_lon) <= 180
    && finite(bounds.radius_m) && bounds.radius_m > 0
    && record(camera)
    && vector3(camera.position) && vector3(camera.look_at)
    && finite(camera.fov_deg) && camera.fov_deg > 0 && camera.fov_deg <= 180
    && typeof value.attribution === "string"
    && typeof value.source === "string";
}

export function decodeReconResponse(value: unknown): ReconScenesResponse {
  if (!record(value) || !Array.isArray(value.scenes) || !value.scenes.every(scene)) {
    throw new Error("Invalid Recon scene response");
  }
  // Older servers expose only scenes; retain that deployment contract.
  const availability = value.availability ?? "available";
  const reason = value.reason ?? null;
  if (availability === "disabled") {
    if (value.scenes.length !== 0 || (reason !== "not_configured" && reason !== "operator_disabled")) {
      throw new Error("Invalid inactive Recon response");
    }
    return { scenes: [], availability, reason };
  }
  if (availability !== "available" || reason !== null) {
    throw new Error("Invalid Recon availability");
  }
  return { scenes: value.scenes, availability, reason };
}
