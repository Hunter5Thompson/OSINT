/**
 * Typed API client for WorldView backend.
 * All calls go through the Vite proxy to /api/*.
 */

import type {
  Aircraft,
  AircraftTrack,
  CableDataset,
  ClientConfig,
  Earthquake,
  EONETEvent,
  FIRMSHotspot,
  GDACSEvent,
  GeoEventsResponse,
  Hotspot,
  IntelAnalysis,
  IntelEvent,
  IntelQuery,
  ReportCreateRequest,
  ReportMessage,
  ReportMessageCreate,
  ReportRecord,
  HistogramResponse,
  ReportUpdateRequest,
  Satellite,
  SpatialApplicationV1,
  TimeHistogramQuery,
  TimeWindowQuery,
  TimelineEventDetail,
  Vessel,
  WindowResponse,
} from "../types";

const BASE = "/api";

function adminHeaders(headers: Record<string, string> = {}): Record<string, string> {
  const token = import.meta.env.VITE_ADMIN_TOKEN;
  return token ? { ...headers, "X-Admin-Token": token } : headers;
}

// ── S1 endpoints — mounted at /api ──────────────────────────────────────────
// The Hlíðskjalf S1 backend router mounts at bare /api.

import type { LandingSummary } from "../types/landing";
import type { SignalEnvelope } from "../types/signals";
import type { Incident, IncidentCreateRequest } from "../types/incident";
import type { AlmanacSignalResponse, CountryAlmanac } from "../types/almanac";
import type { SpatialQueryRef } from "../spatial/contracts";

export const SIGNAL_STREAM_URL = "/api/signals/stream";

export async function getLandingSummary(
  window: "24h" = "24h",
): Promise<LandingSummary> {
  const res = await fetch(`/api/landing/summary?window=${window}`, {
    headers: { Accept: "application/json" },
  });
  if (!res.ok) {
    throw new Error(`landing summary failed: ${res.status} ${res.statusText}`);
  }
  return (await res.json()) as LandingSummary;
}

export async function getLatestSignals(limit = 6): Promise<SignalEnvelope[]> {
  const res = await fetch(`/api/signals/latest?limit=${limit}`, {
    headers: { Accept: "application/json" },
  });
  if (!res.ok) {
    throw new Error(`latest signals failed: ${res.status} ${res.statusText}`);
  }
  return (await res.json()) as SignalEnvelope[];
}

export async function getCountryAlmanac(
  countryId: string,
  signal?: AbortSignal,
): Promise<CountryAlmanac> {
  const res = await fetch(`/api/almanac/countries/${encodeURIComponent(countryId)}`, {
    headers: { Accept: "application/json" },
    signal,
  });
  if (!res.ok) {
    throw new Error(`country almanac failed: ${res.status} ${res.statusText}`);
  }
  return (await res.json()) as CountryAlmanac;
}

export async function getSpatialCountryAlmanac(
  query: Pick<SpatialQueryRef, "scopeKey" | "catalogRevision">,
  signal?: AbortSignal,
): Promise<CountryAlmanac> {
  const parameters = new URLSearchParams({
    scope_key: query.scopeKey,
    catalog_revision: query.catalogRevision,
  });
  const res = await fetch(`/api/almanac/country?${parameters.toString()}`, {
    headers: { Accept: "application/json" },
    signal,
  });
  if (!res.ok) {
    throw new Error(`spatial country almanac failed: ${res.status} ${res.statusText}`);
  }
  return (await res.json()) as CountryAlmanac;
}

export async function getCountryAlmanacSignals(
  countryId: string,
  limit = 5,
  signal?: AbortSignal,
): Promise<AlmanacSignalResponse> {
  const res = await fetch(
    `/api/almanac/countries/${encodeURIComponent(countryId)}/signals?limit=${limit}`,
    { headers: { Accept: "application/json" }, signal },
  );
  if (!res.ok) {
    throw new Error(`country almanac signals failed: ${res.status} ${res.statusText}`);
  }
  return (await res.json()) as AlmanacSignalResponse;
}

async function fetchJSON<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, init);
  if (!res.ok) {
    throw new Error(`API error: ${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

/** Extract the human-readable message from an SSE `error` event payload.
 *  The backend sends a JSON body ({"error": "...", "code": "..."}); fall back to
 *  the trimmed raw line if it is not JSON. */
function parseSseError(data: string): string {
  try {
    const parsed = JSON.parse(data) as { error?: unknown };
    if (typeof parsed.error === "string") {
      return parsed.error;
    }
  } catch {
    // Not JSON — use the raw line.
  }
  return data.trim();
}

export async function getConfig(): Promise<ClientConfig> {
  return fetchJSON<ClientConfig>("/config");
}

export async function getFlights(): Promise<Aircraft[]> {
  return fetchJSON<Aircraft[]>("/flights");
}

export async function getMilitaryFlights(): Promise<Aircraft[]> {
  return fetchJSON<Aircraft[]>("/flights/military");
}

export async function getSatellites(): Promise<Satellite[]> {
  return fetchJSON<Satellite[]>("/satellites");
}

export async function getEarthquakes(): Promise<Earthquake[]> {
  return fetchJSON<Earthquake[]>("/earthquakes");
}

export async function getVessels(): Promise<Vessel[]> {
  return fetchJSON<Vessel[]>("/vessels");
}

export async function getCables(): Promise<CableDataset> {
  return fetchJSON<CableDataset>("/cables");
}

export async function getHotspots(): Promise<Hotspot[]> {
  return fetchJSON<Hotspot[]>("/hotspots");
}

export async function getHotspot(id: string): Promise<Hotspot> {
  return fetchJSON<Hotspot>(`/hotspots/${id}`);
}

export async function getGeoEvents(limit = 100): Promise<IntelEvent[]> {
  const data = await fetchJSON<GeoEventsResponse>(`/graph/events/geo?limit=${limit}`);
  return data.events;
}

/**
 * Callbacks fired by {@link consumeSSE} as parsed SSE frames arrive.
 */
export interface SSEHandlers {
  onStatus: (d: { agent: string; status: string }) => void;
  onResult: (a: IntelAnalysis) => void;
  onError: (msg: string) => void;
  onDone: () => void;
}

/**
 * Block-based SSE frame parser.
 *
 * Reads a response body stream and dispatches whole frames (delimited by a
 * blank line) to the supplied handlers. Event type and data are preserved
 * across chunk boundaries because parsing happens per-frame, not per-chunk.
 * `onDone` is guaranteed to fire exactly once: either via an explicit `done`
 * frame, or when the stream ends without one.
 *
 * Note: consumeSSE has no independent cancel path — to stop streaming the
 * caller must abort the underlying fetch via its AbortController `signal`.
 */
export async function consumeSSE(
  body: ReadableStream<Uint8Array>,
  h: SSEHandlers,
): Promise<void> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let done = false;

  const dispatch = (frame: string): void => {
    let event = "";
    let data = "";
    for (const raw of frame.split("\n")) {
      const line = raw.replace(/\r$/, "");
      if (line.startsWith("event:")) event = line.slice(6).trim();
      else if (line.startsWith("data:")) data += line.slice(5).replace(/^ /, "");
    }
    if (!event) return;
    try {
      if (event === "status") {
        h.onStatus(JSON.parse(data) as { agent: string; status: string });
      } else if (event === "result") {
        h.onResult(JSON.parse(data) as IntelAnalysis);
      } else if (event === "error") {
        h.onError(parseSseError(data));
      } else if (event === "done") {
        if (!done) {
          done = true;
          h.onDone();
        }
      }
    } catch {
      // skip malformed events
    }
  };

  try {
    let streaming = true;
    while (streaming) {
      const { done: streamDone, value } = await reader.read();
      if (streamDone) {
        streaming = false;
        break;
      }
      buffer += decoder.decode(value, { stream: true });
      // frame boundary = blank line (handle \n\n and \r\n\r\n)
      let idx = buffer.search(/\r?\n\r?\n/);
      while (idx !== -1) {
        const frame = buffer.slice(0, idx);
        const delim = buffer.slice(idx).match(/^\r?\n\r?\n/);
        // search already matched at idx → delim is always present;
        // 2 is an unreachable belt-and-suspenders fallback.
        const delimLen = delim ? delim[0].length : 2;
        buffer = buffer.slice(idx + delimLen);
        dispatch(frame);
        idx = buffer.search(/\r?\n\r?\n/);
      }
    }
    if (buffer.trim()) dispatch(buffer);
  } finally {
    reader.releaseLock();
  }

  if (!done) h.onDone();
}

/**
 * Query intelligence via SSE stream.
 * Calls the provided callbacks as events arrive.
 */
export function queryIntel(
  query: IntelQuery,
  onStatus: (data: { agent: string; status: string }) => void,
  onResult: (analysis: IntelAnalysis) => void,
  onError: (error: string) => void,
  onDone: () => void,
): AbortController {
  const controller = new AbortController();
  const { spatialScope, spatialRelation, imageUrl, ...baseQuery } = query;
  const wireQuery = {
    ...baseQuery,
    ...(spatialScope === undefined
      ? {}
      : {
          spatial_scope: {
            schema_version: spatialScope.schemaVersion,
            scope_key: spatialScope.scopeKey,
            catalog_revision: spatialScope.catalogRevision,
            boundary_policy: spatialScope.boundaryPolicy,
          },
        }),
    ...(spatialRelation === undefined ? {} : { spatial_relation: spatialRelation }),
    ...(imageUrl === undefined ? {} : { image_url: imageUrl }),
  };

  fetch(`${BASE}/intel/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(wireQuery),
    signal: controller.signal,
  })
    .then(async (res) => {
      if (!res.ok || !res.body) {
        onError(`HTTP ${res.status}`);
        onDone();
        return;
      }
      await consumeSSE(res.body, { onStatus, onResult, onError, onDone });
    })
    .catch((err: Error) => {
      if (err.name !== "AbortError") {
        onError(err.message);
        onDone();
      }
    });

  return controller;
}

export async function getIntelHistory(): Promise<IntelAnalysis[]> {
  return fetchJSON<IntelAnalysis[]>("/intel/history");
}

/**
 * Stream a country briefing via status-SSE.
 * POSTs to the almanac briefing endpoint and dispatches frames through
 * {@link consumeSSE}. Returns an AbortController to cancel the stream.
 */
export function streamCountryBriefing(
  countryId: string,
  onStatus: SSEHandlers["onStatus"],
  onResult: SSEHandlers["onResult"],
  onError: SSEHandlers["onError"],
  onDone: SSEHandlers["onDone"],
): AbortController {
  const controller = new AbortController();
  fetch(
    `${BASE}/almanac/countries/${encodeURIComponent(countryId)}/briefing`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      signal: controller.signal,
    },
  )
    .then(async (res) => {
      if (!res.ok || !res.body) {
        onError(`HTTP ${res.status}`);
        onDone();
        return;
      }
      await consumeSSE(res.body, { onStatus, onResult, onError, onDone });
    })
    .catch((err: Error) => {
      if (err.name !== "AbortError") {
        onError(err.message);
        onDone();
      }
    });
  return controller;
}

/**
 * Persist a generated country briefing as a report record.
 */
export async function saveCountryBriefing(
  countryId: string,
  analysis: IntelAnalysis,
): Promise<ReportRecord> {
  const res = await fetch(
    `${BASE}/almanac/countries/${encodeURIComponent(countryId)}/briefing/save`,
    {
      method: "POST",
      headers: adminHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ analysis }),
    },
  );
  if (!res.ok) throw new Error(`briefing save failed: ${res.status}`);
  return (await res.json()) as ReportRecord;
}

export async function getFIRMSHotspots(sinceHours = 24): Promise<FIRMSHotspot[]> {
  return fetchJSON<FIRMSHotspot[]>(`/firms/hotspots?since_hours=${sinceHours}`);
}

export async function getAircraftTracks(sinceHours = 24): Promise<AircraftTrack[]> {
  return fetchJSON<AircraftTrack[]>(`/aircraft/tracks?since_hours=${sinceHours}`);
}

export async function getEONETEvents(sinceHours = 168): Promise<EONETEvent[]> {
  return fetchJSON<EONETEvent[]>(`/eonet/events?since_hours=${sinceHours}`);
}

export async function getGDACSEvents(sinceHours = 168): Promise<GDACSEvent[]> {
  return fetchJSON<GDACSEvent[]>(`/gdacs/events?since_hours=${sinceHours}`);
}

// ── S3 Reports (Briefing Room) ──────────────────────────────────────────────

export async function getReports(limit = 200): Promise<ReportRecord[]> {
  return fetchJSON<ReportRecord[]>(`/reports?limit=${limit}`);
}

export async function getReport(reportId: string): Promise<ReportRecord> {
  return fetchJSON<ReportRecord>(`/reports/${encodeURIComponent(reportId)}`);
}

export async function createReport(
  payload: ReportCreateRequest = {},
): Promise<ReportRecord> {
  return fetchJSON<ReportRecord>("/reports", {
    method: "POST",
    headers: adminHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(payload),
  });
}

export async function updateReport(
  reportId: string,
  payload: ReportUpdateRequest,
): Promise<ReportRecord> {
  return fetchJSON<ReportRecord>(`/reports/${encodeURIComponent(reportId)}`, {
    method: "PATCH",
    headers: adminHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(payload),
  });
}

export async function deleteReport(reportId: string): Promise<void> {
  const res = await fetch(`${BASE}/reports/${encodeURIComponent(reportId)}`, {
    method: "DELETE",
    headers: adminHeaders(),
  });
  if (!res.ok) {
    throw new Error(`API error: ${res.status} ${res.statusText}`);
  }
}

export async function getReportMessages(
  reportId: string,
  limit = 500,
): Promise<ReportMessage[]> {
  return fetchJSON<ReportMessage[]>(
    `/reports/${encodeURIComponent(reportId)}/messages?limit=${limit}`,
  );
}

export async function appendReportMessage(
  reportId: string,
  payload: ReportMessageCreate,
): Promise<ReportMessage> {
  return fetchJSON<ReportMessage>(`/reports/${encodeURIComponent(reportId)}/messages`, {
    method: "POST",
    headers: adminHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(payload),
  });
}

// ── S4 Incidents (War Room) ─────────────────────────────────────────────────

export const INCIDENT_STREAM_URL = `${BASE}/incidents/stream`;

export async function getIncidents(limit = 50): Promise<Incident[]> {
  const resp = await fetch(`${BASE}/incidents?limit=${limit}`);
  if (!resp.ok) throw new Error(`incidents: ${resp.status}`);
  return (await resp.json()) as Incident[];
}

export async function getIncident(id: string): Promise<Incident> {
  const resp = await fetch(`${BASE}/incidents/${encodeURIComponent(id)}`);
  if (!resp.ok) throw new Error(`incident ${id}: ${resp.status}`);
  return (await resp.json()) as Incident;
}

export async function triggerIncident(payload: IncidentCreateRequest): Promise<Incident> {
  const resp = await fetch(`${BASE}/incidents/_admin/trigger`, {
    method: "POST",
    headers: adminHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(payload),
  });
  if (!resp.ok) throw new Error(`trigger incident: ${resp.status}`);
  return (await resp.json()) as Incident;
}

export async function silenceIncident(id: string): Promise<Incident> {
  const resp = await fetch(`${BASE}/incidents/${encodeURIComponent(id)}/silence`, {
    method: "POST",
    headers: adminHeaders(),
  });
  if (!resp.ok) throw new Error(`silence ${id}: ${resp.status}`);
  return (await resp.json()) as Incident;
}

interface TimelineSpatialQuery {
  readonly spatialScope?: SpatialQueryRef;
  readonly bbox?: readonly [number, number, number, number];
}

const REQUIRED_SPATIAL_APPLICATION_FIELDS = [
  "schema_version",
  "requested_scope_key",
  "catalog_revision",
  "derivation_revision",
  "boundary_policy",
  "relation",
  "mode",
  "completeness",
  "included_count",
  "excluded_unlocated_count",
  "excluded_conflict_count",
  "excluded_stale_revision_count",
  "excluded_unsupported_count",
] as const;
const SPATIAL_FILTER_MODES = new Set<SpatialApplicationV1["mode"]>([
  "global",
  "semantic_key",
  "point_in_boundary",
  "bbox_approximate",
]);
const SPATIAL_COMPLETENESS = new Set<SpatialApplicationV1["completeness"]>([
  "complete",
  "partial",
]);
const SPATIAL_RELATIONS = new Set<SpatialApplicationV1["relation"]>([
  "occurs-in",
  "intersects",
]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === "string";
}

function isNonNegativeInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}

function invalidSpatialApplication(): never {
  throw new Error("invalid timeline spatial_application contract");
}

function decodeSpatialApplication(value: unknown): SpatialApplicationV1 {
  if (!isRecord(value)) invalidSpatialApplication();
  if (
    REQUIRED_SPATIAL_APPLICATION_FIELDS.some((key) => !Object.hasOwn(value, key))
    || value.schema_version !== 1
    || !isNullableString(value.requested_scope_key)
    || !isNullableString(value.catalog_revision)
    || !isNullableString(value.derivation_revision)
    || !isNullableString(value.boundary_policy)
    || !SPATIAL_RELATIONS.has(value.relation as SpatialApplicationV1["relation"])
    || !SPATIAL_FILTER_MODES.has(value.mode as SpatialApplicationV1["mode"])
    || !SPATIAL_COMPLETENESS.has(value.completeness as SpatialApplicationV1["completeness"])
    || !isNonNegativeInteger(value.included_count)
    || !isNonNegativeInteger(value.excluded_unlocated_count)
    || !isNonNegativeInteger(value.excluded_conflict_count)
    || !isNonNegativeInteger(value.excluded_stale_revision_count)
    || !isNonNegativeInteger(value.excluded_unsupported_count)
  ) {
    invalidSpatialApplication();
  }
  return value as unknown as SpatialApplicationV1;
}

function assertTimelineSpatialMode(query: TimelineSpatialQuery): void {
  if (query.spatialScope !== undefined && query.bbox !== undefined) {
    throw new Error("timeline spatialScope and bbox are mutually exclusive");
  }
}

function appendSpatialScope(
  parameters: URLSearchParams,
  spatialScope: SpatialQueryRef | undefined,
): void {
  if (spatialScope === undefined) return;
  parameters.set("scope_key", spatialScope.scopeKey);
  parameters.set("catalog_revision", spatialScope.catalogRevision);
}

function decodeWindowResponse(value: unknown): WindowResponse {
  if (!isRecord(value)) invalidSpatialApplication();
  decodeSpatialApplication(value.spatial_application);
  return value as unknown as WindowResponse;
}

function decodeHistogramResponse(value: unknown): HistogramResponse {
  if (!isRecord(value)) invalidSpatialApplication();
  decodeSpatialApplication(value.spatial_application);
  return value as unknown as HistogramResponse;
}

export async function getTimeWindow(
  q: TimeWindowQuery,
  signal?: AbortSignal,
): Promise<WindowResponse> {
  assertTimelineSpatialMode(q);
  const p = new URLSearchParams({ t_start: q.tStart, t_end: q.tEnd });
  if (q.domain) p.set("domain", q.domain);
  if (q.tier) p.set("tier", q.tier);
  if (q.movementKind) p.set("movement_kind", q.movementKind);
  appendSpatialScope(p, q.spatialScope);
  if (q.bbox) p.set("bbox", q.bbox.join(","));
  if (q.limit) p.set("limit", String(q.limit));
  const response = await fetchJSON<unknown>(`/timeline/window?${p.toString()}`, { signal });
  return decodeWindowResponse(response);
}

export async function promoteIncident(id: string): Promise<Incident> {
  const resp = await fetch(`${BASE}/incidents/${encodeURIComponent(id)}/promote`, {
    method: "POST",
    headers: adminHeaders(),
  });
  if (!resp.ok) throw new Error(`promote ${id}: ${resp.status}`);
  return (await resp.json()) as Incident;
}

export async function getTimeHistogram(
  q: TimeHistogramQuery,
  signal?: AbortSignal,
): Promise<HistogramResponse> {
  assertTimelineSpatialMode(q);
  const p = new URLSearchParams({ t_start: q.tStart, t_end: q.tEnd, domain: "events" });
  if (q.buckets) p.set("buckets", String(q.buckets));
  appendSpatialScope(p, q.spatialScope);
  if (q.bbox) p.set("bbox", q.bbox.join(","));
  const response = await fetchJSON<unknown>(`/timeline/histogram?${p.toString()}`, { signal });
  return decodeHistogramResponse(response);
}

export async function getEventDetail(
  id: string,
  signal?: AbortSignal,
): Promise<TimelineEventDetail> {
  return fetchJSON<TimelineEventDetail>(`/timeline/events/${encodeURIComponent(id)}`, { signal });
}
