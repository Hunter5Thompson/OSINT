import type { SpatialQueryRef } from "../spatial/contracts";

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

export interface SpatialApplicationV1 {
  readonly schema_version: 1;
  readonly requested_scope_key: string | null;
  readonly catalog_revision: string | null;
  readonly derivation_revision: string | null;
  readonly boundary_policy: string | null;
  readonly relation: "occurs-in" | "intersects";
  readonly mode: "global" | "semantic_key" | "point_in_boundary" | "bbox_approximate";
  readonly completeness: "complete" | "partial";
  readonly included_count: number;
  readonly excluded_unlocated_count: number;
  readonly excluded_conflict_count: number;
  readonly excluded_stale_revision_count: number;
  readonly excluded_unsupported_count: number;
}

export interface WindowResponse {
  domain: "events" | "movements";
  tier: "coarse" | "fine";
  t_start: string;
  t_end: string;
  bbox: { west: number; south: number; east: number; north: number } | null;
  samples: WindowSample[];
  total_count: number;
  truncated: boolean;
  spatial_application: SpatialApplicationV1;
}

export interface TimeWindowQuery {
  tStart: string;
  tEnd: string;
  domain?: "events" | "movements";
  tier?: "coarse" | "fine";
  movementKind?: "mil_aircraft" | "civil_aircraft" | "ship" | "satellite";
  spatialScope?: SpatialQueryRef;
  bbox?: readonly [number, number, number, number];
  limit?: number;
}

export interface TimeHistogramQuery {
  tStart: string;
  tEnd: string;
  buckets?: number;
  spatialScope?: SpatialQueryRef;
  bbox?: readonly [number, number, number, number];
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
  spatial_application?: SpatialRunApplicationV1 | null;
}

export interface SpatialRunScopeV1 {
  readonly schema_version: 1;
  readonly scope_key: string;
  readonly catalog_revision: string;
  readonly derivation_revision: string;
  readonly boundary_policy: string;
}

export interface SpatialRunConsumerApplication {
  readonly status: "applied" | "not-called" | "unsupported" | "failed";
  readonly mode: "global" | "semantic-key";
  readonly completeness: "complete" | "partial" | "unknown";
  readonly detail_code?: string | null;
}

export interface SpatialRunApplicationV1 {
  readonly schema_version: 1;
  readonly scope: SpatialRunScopeV1;
  readonly relation: "about" | "occurrence" | "either";
  readonly qdrant: SpatialRunConsumerApplication;
  readonly neo4j: SpatialRunConsumerApplication;
  readonly blocked_tools: readonly string[];
  readonly coverage_revision: string | null;
}

export interface IntelQuery {
  query: string;
  region?: string;
  hotspot_id?: string;
  use_legacy?: boolean;
  report_id?: string;
  report_message?: string;
  spatialScope?: SpatialQueryRef;
  spatialRelation?: "about" | "occurrence" | "either";
  imageUrl?: string;
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
  spatial_application?: SpatialRunApplicationV1 | null;
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
  spatial_application?: SpatialRunApplicationV1 | null;
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
  recon: boolean;
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
  spatial_application: SpatialApplicationV1;
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
