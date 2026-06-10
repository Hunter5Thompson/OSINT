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

// --- Windowed-data contract (/api/timeline/window) ---
export interface WindowTrackPoint {
  ts_ms: number;
  lat: number;
  lon: number;
  altitude_m?: number | null;
  speed_ms?: number | null;
  heading?: number | null;
}

export interface WindowTrackSample {
  kind: "track";
  id: string;
  icao24?: string | null;
  callsign?: string | null;
  type_code?: string | null;
  military_branch?: string | null;
  registration?: string | null;
  points: WindowTrackPoint[];
}

export interface WindowEventSample {
  kind: "event";
  id: string;
  time: string;
  time_basis: string;
  title?: string | null;
  codebook_type?: string | null;
  severity?: string | null;
  lat?: number | null;
  lon?: number | null;
  location_name?: string | null;
  country?: string | null;
}

export type WindowSample = WindowEventSample | WindowTrackSample;

export interface WindowResponse {
  domain: "events" | "movements";
  tier: "coarse" | "fine";
  t_start: string;
  t_end: string;
  bbox: { west: number; south: number; east: number; north: number } | null;
  samples: WindowSample[];
  total_count: number;
  truncated: boolean;
}

export interface TimeWindowQuery {
  tStart: string;
  tEnd: string;
  domain?: "events" | "movements";
  tier?: "coarse" | "fine";
  movementKind?: "mil_aircraft" | "civil_aircraft" | "ship" | "satellite";
  bbox?: [number, number, number, number];
  limit?: number;
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
  mode?: "react" | "legacy" | "error";
}

export interface IntelQuery {
  query: string;
  region?: string;
  hotspot_id?: string;
  use_legacy?: boolean;
  report_id?: string;
  report_message?: string;
}

export type ReportStatus = "Draft" | "Published" | "Archived";
export type MessageRole = "user" | "munin" | "system";
export type MetricTone = "sentinel" | "amber" | "sage";

export interface DossierMetric {
  label: string;
  value: string;
  sub: string;
  tone: MetricTone;
}

export interface MarginEntry {
  label: string;
  value: string;
}

export interface ReportRecord {
  id: string;
  paragraph_num: number;
  stamp: string;
  title: string;
  scope_key?: string | null;
  status: ReportStatus;
  confidence: number;
  location: string;
  coords: string;
  findings: string[];
  metrics: DossierMetric[];
  context: string;
  body_title: string;
  body_paragraphs: string[];
  margin: MarginEntry[];
  sources: string[];
  created_at: string;
  updated_at: string;
}

export interface ReportCreateRequest {
  title?: string;
  status?: ReportStatus;
  confidence?: number;
  location?: string;
  coords?: string;
  findings?: string[];
  metrics?: DossierMetric[];
  context?: string;
  body_title?: string;
  body_paragraphs?: string[];
  margin?: MarginEntry[];
  sources?: string[];
}

export interface ReportUpdateRequest extends ReportCreateRequest {}

export interface ReportMessage {
  id: string;
  role: MessageRole;
  text: string;
  ts: string;
  refs: string[];
}

export interface ReportMessageCreate {
  role: MessageRole;
  text: string;
  ts?: string;
  refs?: string[];
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

export interface EONETEvent {
  id: string;
  title: string;
  category: string;
  status: string;
  latitude: number;
  longitude: number;
  event_date: string;
}

export interface GDACSEvent {
  id: string;
  event_type: string;
  event_name: string;
  alert_level: string;
  severity: number;
  country: string;
  latitude: number;
  longitude: number;
  from_date: string;
  to_date: string;
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
  countryBorders: boolean;
  cityBuildings: boolean;
  firmsHotspots: boolean;
  milAircraft: boolean;
  datacenters: boolean;
  refineries: boolean;
  eonet: boolean;
  gdacs: boolean;
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

export type {
  DatacenterTier,
  RefineryStatus,
  DatacenterProperties,
  RefineryProperties,
  InfraFeature,
  InfraGeoJSON,
  DatacenterGeoJSON,
  RefineryGeoJSON,
} from "./infrastructure";

// --- Timeline histogram + detail contract (/api/timeline/histogram, /events/{id}) ---
export interface HistogramBucket {
  ts: string;
  count: number;
  dominant_category: string;
  by_category: Record<string, number>;
  by_severity: Record<string, number>;
}
export interface TimelineNotable {
  id: string;
  time: string;
  time_basis: string;
  severity: string;
  title?: string | null;
  codebook_type?: string | null;
  lat?: number | null;
  lon?: number | null;
  is_incident: boolean;
  rank: number;
}
export interface TimelineGeoEvent {
  id: string;
  time: string;
  codebook_type?: string | null;
  severity: string;
  lat: number;
  lon: number;
  is_incident: boolean;
}
export interface HistogramResponse {
  t_start: string;
  t_end: string;
  bucket_ms: number;
  buckets: HistogramBucket[];
  notables: TimelineNotable[];
  geo_events: TimelineGeoEvent[];
  total_count: number;
  geo_located_count: number;
  geo_truncated: boolean;
}
export interface TimelineEventDetail {
  id: string;
  time: string;
  time_basis: string;
  title?: string | null;
  codebook_type?: string | null;
  severity?: string | null;
  source?: string | null;
  url?: string | null;
  location_name?: string | null;
  country?: string | null;
  lat?: number | null;
  lon?: number | null;
}
