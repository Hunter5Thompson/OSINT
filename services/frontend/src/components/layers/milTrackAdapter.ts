import type { AircraftTrack, WindowTrackSample } from "../../types";

export interface MilTrackPoint {
  lat: number;
  lon: number;
  altitude_m: number | null;
  speed_ms: number | null;
  heading: number | null;
  ts_ms: number;
}

export interface MilTrackRender {
  icao24: string;
  callsign: string | null;
  type_code: string | null;
  military_branch: string | null;
  registration: string | null;
  points: MilTrackPoint[];
}

export function fromLiveTrack(t: AircraftTrack): MilTrackRender {
  return {
    icao24: t.icao24,
    callsign: t.callsign,
    type_code: t.type_code,
    military_branch: t.military_branch,
    registration: t.registration,
    points: t.points.map((p) => ({
      lat: p.lat, lon: p.lon, altitude_m: p.altitude_m,
      speed_ms: p.speed_ms, heading: p.heading,
      ts_ms: p.timestamp * 1000, // collector stores epoch seconds
    })),
  };
}

export function fromWindowTrack(s: WindowTrackSample): MilTrackRender {
  return {
    icao24: s.icao24 ?? s.id,
    callsign: s.callsign ?? null,
    type_code: s.type_code ?? null,
    military_branch: s.military_branch ?? null,
    registration: s.registration ?? null,
    points: s.points.map((p) => ({
      lat: p.lat, lon: p.lon,
      altitude_m: p.altitude_m ?? null, speed_ms: p.speed_ms ?? null,
      heading: p.heading ?? null, ts_ms: p.ts_ms,
    })),
  };
}

export interface InterpPos { lat: number; lon: number; alt: number; }

// Replay edge behavior (spec §7.3): before first -> null; between -> linear;
// after last -> clamp to last (no dead reckoning).
export function positionAtTime(points: MilTrackPoint[], tMs: number): InterpPos | null {
  const first = points[0];
  if (!first || tMs < first.ts_ms) return null;
  const last = points[points.length - 1];
  if (!last) return null;
  if (tMs >= last.ts_ms) return { lat: last.lat, lon: last.lon, alt: last.altitude_m ?? 0 };
  for (let i = 0; i < points.length - 1; i++) {
    const a = points[i];
    const b = points[i + 1];
    if (!a || !b) continue;
    if (tMs >= a.ts_ms && tMs <= b.ts_ms) {
      const span = b.ts_ms - a.ts_ms || 1;
      const f = (tMs - a.ts_ms) / span;
      return {
        lat: a.lat + (b.lat - a.lat) * f,
        lon: a.lon + (b.lon - a.lon) * f,
        alt: (a.altitude_m ?? 0) + ((b.altitude_m ?? 0) - (a.altitude_m ?? 0)) * f,
      };
    }
  }
  return null;
}
