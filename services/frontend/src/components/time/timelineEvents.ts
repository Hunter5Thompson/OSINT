import type { IntelEvent, TimelineGeoEvent } from "../../types";

/** Preserve source titles; older responses use neutral type/ID labels without a detail fetch. */
export function toTimelineLayerEvents(events: readonly TimelineGeoEvent[]): IntelEvent[] {
  return events.map(g => ({
    id: g.id,
    title: g.title?.trim() ? g.title : g.codebook_type || g.id,
    codebook_type: g.codebook_type ?? "other",
    severity: g.severity,
    timestamp: g.time,
    location_name: null,
    country: null,
    lat: g.lat,
    lon: g.lon,
  }));
}
