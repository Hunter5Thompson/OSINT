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
  ReportUpdateRequest,
  Satellite,
  Vessel,
} from "../types";

const BASE = "/api";

// ── S1 endpoints — mounted at /api ──────────────────────────────────────────
// The Hlíðskjalf S1 backend router mounts at bare /api.

import type { LandingSummary } from "../types/landing";
import type { SignalEnvelope } from "../types/signals";
import type { Incident, IncidentCreateRequest } from "../types/incident";
import type { AlmanacSignalResponse, CountryAlmanac } from "../types/almanac";

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

export async function getCountryAlmanac(countryId: string): Promise<CountryAlmanac> {
  const res = await fetch(`/api/almanac/countries/${encodeURIComponent(countryId)}`, {
    headers: { Accept: "application/json" },
  });
  if (!res.ok) {
    throw new Error(`country almanac failed: ${res.status} ${res.statusText}`);
  }
  return (await res.json()) as CountryAlmanac;
}

export async function getCountryAlmanacSignals(
  countryId: string,
  limit = 5,
): Promise<AlmanacSignalResponse> {
  const res = await fetch(
    `/api/almanac/countries/${encodeURIComponent(countryId)}/signals?limit=${limit}`,
    { headers: { Accept: "application/json" } },
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

  fetch(`${BASE}/intel/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(query),
    signal: controller.signal,
  })
    .then(async (res) => {
      if (!res.ok || !res.body) {
        onError(`HTTP ${res.status}`);
        return;
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      // Carried ACROSS chunk boundaries: an `event:` line and its `data:` line
      // can arrive in separate reads, so the current event type must survive
      // the per-chunk loop (like `buffer`).
      let currentEvent = "";
      let doneEmitted = false;
      const emitDone = (): void => {
        if (!doneEmitted) {
          doneEmitted = true;
          onDone();
        }
      };

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        // Split on CRLF or LF — the backend (sse-starlette) emits \r\n.
        const lines = buffer.split(/\r?\n/);
        buffer = lines.pop() ?? "";

        for (const line of lines) {
          if (line.startsWith("event: ")) {
            currentEvent = line.slice(7).trim();
          } else if (line.startsWith("data: ")) {
            const data = line.slice(6);
            try {
              if (currentEvent === "status") {
                onStatus(JSON.parse(data) as { agent: string; status: string });
              } else if (currentEvent === "result") {
                onResult(JSON.parse(data) as IntelAnalysis);
              } else if (currentEvent === "error") {
                onError(parseSseError(data));
              } else if (currentEvent === "done") {
                emitDone();
              }
            } catch {
              // skip malformed events
            }
          }
        }
      }
      emitDone();
    })
    .catch((err: Error) => {
      if (err.name !== "AbortError") {
        onError(err.message);
      }
    });

  return controller;
}

export async function getIntelHistory(): Promise<IntelAnalysis[]> {
  return fetchJSON<IntelAnalysis[]>("/intel/history");
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
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function updateReport(
  reportId: string,
  payload: ReportUpdateRequest,
): Promise<ReportRecord> {
  return fetchJSON<ReportRecord>(`/reports/${encodeURIComponent(reportId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function deleteReport(reportId: string): Promise<void> {
  const res = await fetch(`${BASE}/reports/${encodeURIComponent(reportId)}`, {
    method: "DELETE",
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
    headers: { "Content-Type": "application/json" },
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
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!resp.ok) throw new Error(`trigger incident: ${resp.status}`);
  return (await resp.json()) as Incident;
}

export async function silenceIncident(id: string): Promise<Incident> {
  const resp = await fetch(`${BASE}/incidents/${encodeURIComponent(id)}/silence`, {
    method: "POST",
  });
  if (!resp.ok) throw new Error(`silence ${id}: ${resp.status}`);
  return (await resp.json()) as Incident;
}

export async function promoteIncident(id: string): Promise<Incident> {
  const resp = await fetch(`${BASE}/incidents/${encodeURIComponent(id)}/promote`, {
    method: "POST",
  });
  if (!resp.ok) throw new Error(`promote ${id}: ${resp.status}`);
  return (await resp.json()) as Incident;
}
