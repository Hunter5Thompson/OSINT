import type { Aircraft } from "../../types";
import { bandForHeight, inViewBounds, type AltitudeBand, type ViewBounds } from "../../lib/lod";

const CAPS: Record<AltitudeBand, number> = { GLOBE: 250, REGIONAL: 600, LOCAL: 1500 };

export interface FlightDensity {
  total: number;
  valid: number;
  invalid: number;
  duplicates: number;
  inView: number;
  shown: number;
  omitted: number;
  band: AltitudeBand;
  cap: number;
}

/** Rendering selection only; it does not certify source coverage or military identity. */
export function selectFlightRenderSet(
  flights: readonly Aircraft[], height: number, bounds: ViewBounds | null, pinnedId?: string,
): { flights: Aircraft[]; density: FlightDensity } {
  const band = bandForHeight(height);
  const cap = CAPS[band];
  const ids = new Set<string>();
  const candidates: Aircraft[] = [];
  let invalid = 0, duplicates = 0;
  for (const flight of flights) {
    const id = flight.icao24?.trim();
    if (!id || !Number.isFinite(flight.latitude) || !Number.isFinite(flight.longitude)
      || Math.abs(flight.latitude) > 90 || Math.abs(flight.longitude) > 180) {
      invalid++;
      continue;
    }
    if (ids.has(id)) { duplicates++; continue; }
    ids.add(id);
    if (inViewBounds(flight.longitude, flight.latitude, bounds)) candidates.push(flight);
  }
  const rank = (f: Aircraft) => f.icao24.trim() === pinnedId ? 2 : f.is_military ? 1 : 0;
  // Stable sorting retains source order within a priority class.
  candidates.sort((a, b) => rank(b) - rank(a));
  const selected = candidates.slice(0, cap);
  return { flights: selected, density: { total: flights.length, valid: ids.size, invalid,
    duplicates, inView: candidates.length, shown: selected.length,
    omitted: candidates.length - selected.length, band, cap } };
}
