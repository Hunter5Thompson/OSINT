/**
 * Typed API client for WorldView backend.
 * All calls go through the Vite proxy to /api/*.
 * If an endpoint is not mounted there yet, we transparently fall back to /api/v1/*.
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
const LEGACY_BASE = "/api/v1";

// ── S1 endpoints — mounted at /api (not /api/v1) ────────────────────────────
// The Hlíðskjalf S1 backend router mounts at bare /api. Keep these helpers
// separate from the legacy /api/v1 client rather than reshuffling everything.

import type { LandingSummary } from "../types/landing";
import type { SignalEnvelope } from "../types/signals";

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

async function fetchWithFallback(path: string, init?: RequestInit): Promise<Response> {
  let res = await fetch(`${BASE}${path}`, init);
  if (res.status === 404) {
    res = await fetch(`${LEGACY_BASE}${path}`, init);
  }
  return res;
}

async function fetchJSON<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetchWithFallback(path, init);
  if (!res.ok) {
    throw new Error(`API error: ${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<T>;
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

  fetchWithFallback("/intel/query", {
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

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";

        let currentEvent = "";
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
                onError(data);
              } else if (currentEvent === "done") {
                onDone();
              }
            } catch {
              // skip malformed events
            }
          }
        }
      }
      onDone();
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
  const res = await fetchWithFallback(`/reports/${encodeURIComponent(reportId)}`, {
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
