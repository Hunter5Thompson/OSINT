// ── Data Models (matching backend Pydantic models) ──

export interface Aircraft {
  icao24: string;
  callsign: string | null;
  latitude: number;
  longitude: number;
  altitude_m: number;
  velocity_ms: number;
  heading: number;
  vertical_rate: number;
  on_ground: boolean;
  last_contact: string;
  is_military: boolean;
  aircraft_type: string | null;
}

export interface Satellite {
  norad_id: number;
  name: string;
  tle_line1: string;
  tle_line2: string;
  category: string;
  inclination_deg: number;
  period_min: number;
  operator_country: string | null;
  satellite_type: string;
}

export interface Earthquake {
  id: string;
  latitude: number;
  longitude: number;
  depth_km: number;
  magnitude: number;
  place: string;
  time: string;
  tsunami: boolean;
  url: string | null;
}

export interface Vessel {
  mmsi: number;
  name: string | null;
  latitude: number;
  longitude: number;
  speed_knots: number;
  course: number;
  ship_type: number;
  destination: string | null;
}

export interface Hotspot {
  id: string;
  name: string;
  latitude: number;
  longitude: number;
  region: string;
  threat_level: "CRITICAL" | "HIGH" | "ELEVATED" | "MODERATE";
  description: string;
  last_updated: string;
  sources: string[];
}

export interface FIRMSHotspot {
  id: string;
  latitude: number;
  longitude: number;
  frp: number;
  brightness: number;
  confidence: string;
  acq_date: string;
  acq_time: string;
  satellite: string;
  bbox_name: string;
  possible_explosion: boolean;
  firms_map_url: string;
}

export interface AircraftPoint {
  lat: number;
  lon: number;
  altitude_m: number | null;
  speed_ms: number | null;
  heading: number | null;
  timestamp: number;
}

export interface AircraftTrack {
  icao24: string;
  callsign: string | null;
  type_code: string | null;
  military_branch: string | null;
  registration: string | null;
  points: AircraftPoint[];
}

export interface IntelAnalysis {
  query: string;
  agent_chain: string[];
  sources_used: string[];
  analysis: string;
  confidence: number;
  threat_assessment: string | null;
  timestamp: string;
  tool_trace?: Array<{ tool_name: string; duration_ms?: number; success?: boolean }>;
  mode?: "react" | "legacy" | "legacy_fallback" | "error";
}

export interface IntelQuery {
  query: string;
  region?: string;
  hotspot_id?: string;
  use_legacy?: boolean;
}

export interface IntelEvent {
  id: string;
  title: string;
  codebook_type: string;
  severity: string;
  timestamp: string | null;
  location_name: string | null;
  country: string | null;
  lat: number | null;
  lon: number | null;
}

export interface GeoEventsResponse {
  events: IntelEvent[];
  total_count: number;
}

export interface SubmarineCable {
  id: string;
  name: string;
  color: string;
  is_planned: boolean;
  owners: string | null;
  capacity_tbps: number | null;
  length_km: number | null;
  rfs: string | null;
  url: string | null;
  landing_point_ids: string[];
  coordinates: number[][][];
}

export interface LandingPoint {
  id: string;
  name: string;
  country: string | null;
  latitude: number;
  longitude: number;
}

export interface CableDataset {
  cables: SubmarineCable[];
  landing_points: LandingPoint[];
  source: string;
}

// ── UI State Types ──

export interface LayerVisibility {
  flights: boolean;
  satellites: boolean;
  earthquakes: boolean;
  vessels: boolean;
  cctv: boolean;
  events: boolean;
  cables: boolean;
  pipelines: boolean;
  firmsHotspots: boolean;
  milAircraft: boolean;
}

export type ShaderType = "none" | "crt" | "nightvision" | "flir";

export interface ClientConfig {
  cesium_ion_token: string;
  default_layers: LayerVisibility;
  api_version: string;
}

export interface DataFreshness {
  flights: Date | null;
  satellites: Date | null;
  earthquakes: Date | null;
  vessels: Date | null;
  events: Date | null;
  cables: Date | null;
  pipelines: Date | null;
}

export type { PipelineProperties, PipelineFeature, PipelineGeoJSON } from "./pipeline";
export { PIPELINE_COLORS, PIPELINE_LOD_THRESHOLDS } from "./pipeline";
