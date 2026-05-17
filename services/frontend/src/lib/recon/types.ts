export interface GeoBounds {
  center_lat: number;
  center_lon: number;
  radius_m: number;
}

export interface DefaultCamera {
  position: [number, number, number];
  look_at: [number, number, number];
  fov_deg: number;
}

export type BoundsSource = "spacenet_metadata" | "manual";

export interface ReconScene {
  scene_id: string;
  hf_filename: string;
  display_name: string;
  ply_url: string;
  ply_size_bytes: number;
  bounds: GeoBounds;
  bounds_source: BoundsSource;
  default_camera: DefaultCamera;
  attribution: string;
  source: string;
}

export interface ReconScenesResponse {
  scenes: ReconScene[];
}
