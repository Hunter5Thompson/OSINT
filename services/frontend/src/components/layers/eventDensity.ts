import type { IntelEvent } from "../../types";
import { bandForHeight, inViewBounds, type AltitudeBand, type ViewBounds } from "../../lib/lod";

const CAPS: Record<AltitudeBand, number> = { GLOBE: 250, REGIONAL: 600, LOCAL: 1500 };
const SEVERITY: Record<string, number> = { critical: 4, high: 3, medium: 2, low: 1 };
export interface EventCluster {
  count: number;
  lat: number;
  lon: number;
  codebook_type: string;
  severity: string;
  eventTimes: number[];
}
export interface EventDensity {
  total: number;
  valid: number;
  invalid: number;
  unlocated: number;
  duplicates: number;
  outsideWindow: number;
  outsideView: number;
  inView: number;
  represented: number;
  symbols: number;
  aggregates: number;
  omitted: number;
  band: AltitudeBand;
  cap: number;
}

/** Visual clusters count actual supplied members; they are never individual source events. */
export function selectEventRenderSet(
  events: readonly IntelEvent[], height: number, bounds: ViewBounds | null,
  window: { startMs: number; endMs: number } | null, pinnedId?: string,
): { events: IntelEvent[]; clusters: EventCluster[]; density: EventDensity } {
  const band = bandForHeight(height), cap = CAPS[band];
  const ids = new Set<string>(), candidates: IntelEvent[] = [];
  let invalid = 0, unlocated = 0, duplicates = 0, outsideWindow = 0, outsideView = 0;
  for (const event of events) {
    if (event.lat == null || event.lon == null) { unlocated++; continue; }
    if (!event.id || !Number.isFinite(event.lat) || !Number.isFinite(event.lon)
      || Math.abs(event.lat) > 90 || Math.abs(event.lon) > 180) { invalid++; continue; }
    if (ids.has(event.id)) { duplicates++; continue; }
    ids.add(event.id);
    const time = Date.parse(event.timestamp ?? "");
    if (window && (!Number.isFinite(time) || time < window.startMs || time > window.endMs)) {
      outsideWindow++; continue;
    }
    if (!inViewBounds(event.lon, event.lat, bounds)) { outsideView++; continue; }
    candidates.push(event);
  }
  const rank = (e: IntelEvent) => e.id === pinnedId ? 100 : SEVERITY[e.severity] ?? 0;
  candidates.sort((a, b) => rank(b) - rank(a));
  const groups = new Map<string, IntelEvent[]>();
  for (const event of candidates) {
    // Shift the longitude grid so ±180 belongs to the same cell; all exact pole
    // longitudes refer to one physical point. No original coordinate is rewritten.
    const lonCell = Math.abs(event.lat!) === 90 ? 0 : Math.floor(((event.lon! + 185) % 360) / 10);
    const latCell = Math.min(17, Math.floor((event.lat! + 90) / 10));
    const key = band === "GLOBE" && event.id !== pinnedId
      ? `cell:${latCell}:${lonCell}:${event.codebook_type.split(".")[0]}` : `event:${event.id}`;
    const members = groups.get(key);
    if (members) members.push(event); else groups.set(key, [event]);
  }
  const shown: IntelEvent[] = [], clusters: EventCluster[] = [];
  let represented = 0, symbols = 0;
  // Groups retain the highest-priority member's first-seen position.
  for (const members of groups.values()) {
    if (symbols >= cap) break;
    symbols++;
    represented += members.length;
    const first = members[0]!;
    if (members.length === 1) { shown.push(first); continue; }
    const lat = members.reduce((sum, e) => sum + e.lat!, 0) / members.length;
    const sin = members.reduce((sum, e) => sum + Math.sin(e.lon! * Math.PI / 180), 0);
    const cos = members.reduce((sum, e) => sum + Math.cos(e.lon! * Math.PI / 180), 0);
    const lon = Math.abs(lat) === 90 ? 0 : members.every(e => e.lon === first.lon)
      ? first.lon! : Math.atan2(sin, cos) * 180 / Math.PI;
    clusters.push({ count: members.length, lat, lon,
      severity: first.severity, codebook_type: first.codebook_type,
      eventTimes: members.map(e => Date.parse(e.timestamp ?? "")).filter(Number.isFinite).sort((a, b) => a - b) });
  }
  return { events: shown, clusters, density: { total: events.length, valid: ids.size, invalid,
    unlocated, duplicates, outsideWindow, outsideView, inView: candidates.length,
    represented, symbols, aggregates: clusters.length, omitted: candidates.length - represented, band, cap } };
}
