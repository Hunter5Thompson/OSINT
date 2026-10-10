import * as satellite from "satellite.js";
import type { Satellite } from "../types";
import type {
  OMMElements, OrbitElements, OrbitGroupCoverage, OrbitRejection, OrbitSatellite, OrbitSnapshot,
} from "../types/satelliteOrbit";

function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Expected an object");
  return value as Record<string, unknown>;
}

function text(value: unknown): string {
  if (typeof value !== "string") throw new Error("Expected a string");
  return value;
}

function finite(value: unknown, minimum = -Infinity, maximum = Infinity): number {
  if (typeof value !== "number" || !Number.isFinite(value) || value < minimum || value > maximum) {
    throw new Error("Expected a finite number in the supported range");
  }
  return value;
}

function integer(value: unknown, minimum = 0, maximum = 999999999): number {
  const result = finite(value, minimum, maximum);
  if (!Number.isSafeInteger(result)) throw new Error("Expected an integer");
  return result;
}

function choice<T extends string | number>(value: unknown, choices: readonly T[]): T {
  if (!choices.includes(value as T)) throw new Error("Unsupported value");
  return value as T;
}

function utcDate(value: unknown): string {
  const result = text(value);
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$/.test(result)) {
    throw new Error("Expected a UTC date and time");
  }
  const [time, fraction = ""] = result.slice(0, -1).split(".");
  const milliseconds = `${time}.${fraction.padEnd(3, "0").slice(0, 3)}Z`;
  const date = new Date(result);
  if (!Number.isFinite(date.getTime()) || date.toISOString() !== milliseconds) {
    throw new Error("Invalid UTC date and time");
  }
  return result;
}

function angle(value: unknown): number {
  const result = finite(value, 0, 360);
  if (result === 360) throw new Error("Orbital angle must be less than 360 degrees");
  return result;
}

function decodeOMM(value: unknown): OMMElements {
  const row = object(value);
  const meanMotion = finite(row.MEAN_MOTION);
  const eccentricity = finite(row.ECCENTRICITY, 0, 1);
  if (meanMotion <= 0 || !Number.isFinite(1440 / meanMotion) || eccentricity === 1) {
    throw new Error("Invalid mean motion/eccentricity");
  }
  return {
    OBJECT_NAME: text(row.OBJECT_NAME), OBJECT_ID: text(row.OBJECT_ID),
    NORAD_CAT_ID: integer(row.NORAD_CAT_ID, 1), EPOCH: utcDate(row.EPOCH),
    MEAN_MOTION: meanMotion, ECCENTRICITY: eccentricity,
    INCLINATION: finite(row.INCLINATION, 0, 180), RA_OF_ASC_NODE: angle(row.RA_OF_ASC_NODE),
    ARG_OF_PERICENTER: angle(row.ARG_OF_PERICENTER), MEAN_ANOMALY: angle(row.MEAN_ANOMALY),
    BSTAR: finite(row.BSTAR), MEAN_MOTION_DOT: finite(row.MEAN_MOTION_DOT),
    MEAN_MOTION_DDOT: finite(row.MEAN_MOTION_DDOT), EPHEMERIS_TYPE: choice(row.EPHEMERIS_TYPE, [0]),
    CLASSIFICATION_TYPE: choice(row.CLASSIFICATION_TYPE, ["U", "C", "S"]),
    ELEMENT_SET_NO: integer(row.ELEMENT_SET_NO), REV_AT_EPOCH: integer(row.REV_AT_EPOCH),
    CENTER_NAME: choice(row.CENTER_NAME, ["EARTH"]), REF_FRAME: choice(row.REF_FRAME, ["TEME"]),
    TIME_SYSTEM: choice(row.TIME_SYSTEM, ["UTC"]), MEAN_ELEMENT_THEORY: choice(row.MEAN_ELEMENT_THEORY, ["SGP4"]),
  };
}

function tleCatalog(line1: string, line2: string): number {
  for (const [index, line] of [line1, line2].entries()) {
    if (line.length !== 69 || !line.startsWith(`${index + 1} `) || !/^[ 0-9]{5}$/.test(line.slice(2, 7))) {
      throw new Error("Unsupported or malformed fixed-column TLE");
    }
    const checksum = [...line.slice(0, 68)].reduce((sum, char) =>
      sum + (/^[0-9]$/.test(char) ? Number(char) : char === "-" ? 1 : 0), 0) % 10;
    if (!/^[0-9]$/.test(line[68]!) || Number(line[68]) !== checksum) throw new Error("TLE checksum mismatch");
  }
  const id = integer(Number(line1.slice(2, 7)), 1, 99999);
  if (id !== Number(line2.slice(2, 7))) throw new Error("TLE catalog identifiers disagree");
  return id;
}

function decodeOrbit(value: unknown, id: number): OrbitElements {
  const orbit = object(value);
  if (orbit.format === "omm") {
    const elements = decodeOMM(orbit.elements);
    if (elements.NORAD_CAT_ID !== id) throw new Error("Metadata/OMM catalog identifiers disagree");
    return { format: "omm", elements };
  }
  if (orbit.format === "tle") {
    const line1 = text(orbit.line1), line2 = text(orbit.line2);
    if (tleCatalog(line1, line2) !== id) throw new Error("Metadata/TLE catalog identifiers disagree");
    return { format: "tle", line1, line2 };
  }
  throw new Error("Unsupported orbit format");
}

function decodeRow(value: unknown): OrbitSatellite {
  const row = object(value), id = integer(row.norad_id, 1);
  const period = finite(row.period_min);
  if (period <= 0) throw new Error("Invalid orbital period");
  return {
    norad_id: id, name: text(row.name), orbit: decodeOrbit(row.orbit, id),
    category: text(row.category), inclination_deg: finite(row.inclination_deg, 0, 180),
    period_min: period, operator_country: row.operator_country === null ? null : text(row.operator_country),
    satellite_type: text(row.satellite_type),
  };
}

function decodeGroup(value: unknown): OrbitGroupCoverage {
  const row = object(value);
  if (!Array.isArray(row.rejections)) throw new Error("Missing group rejections");
  const rejections: OrbitRejection[] = row.rejections.map((value: unknown) => {
    const rejection = object(value);
    return { index: integer(rejection.index), code: choice(rejection.code, ["invalid", "unsupported"]), reason: text(rejection.reason) };
  });
  const result: OrbitGroupCoverage = {
    group: text(row.group), status: choice(row.status, ["ok", "partial", "failed"]),
    accepted_records: integer(row.accepted_records), rejected_invalid: integer(row.rejected_invalid),
    rejected_unsupported: integer(row.rejected_unsupported), rejections,
    failure_code: row.failure_code === null ? null : choice(row.failure_code, ["transport", "invalid_payload", "no_usable_records"] as const),
  };
  if (result.rejected_invalid !== rejections.filter(row => row.code === "invalid").length ||
      result.rejected_unsupported !== rejections.filter(row => row.code === "unsupported").length) {
    throw new Error("Group rejection counts disagree");
  }
  const expected = result.failure_code ? "failed" : rejections.length ? "partial" : "ok";
  if (expected !== result.status || (expected === "failed" && result.accepted_records > 0)) {
    throw new Error("Group status disagrees with diagnostics");
  }
  return result;
}

export function decodeOrbitSnapshot(value: unknown): OrbitSnapshot {
  const body = object(value), coverage = object(body.coverage);
  if (body.schema_version !== 1 || !Array.isArray(body.satellites) || !Array.isArray(coverage.groups)) {
    throw new Error("Unsupported orbit snapshot contract");
  }
  const groups = coverage.groups.map((value: unknown) => decodeGroup(value));
  const completeness = choice(coverage.completeness, ["complete", "partial"]);
  if (!groups.length || groups.every(row => row.status === "failed") ||
      (completeness === "complete") !== groups.every(row => row.status === "ok") ||
      new Set(groups.map(row => row.group)).size !== groups.length) {
    throw new Error("Contradictory orbit coverage");
  }
  const fetchedAt = utcDate(body.fetched_at);
  const accepted = groups.reduce((sum, group) => sum + group.accepted_records, 0);
  if (body.satellites.length > accepted || Boolean(body.satellites.length) !== Boolean(accepted)) {
    throw new Error("Snapshot satellites disagree with source record counts");
  }
  const satellites: OrbitSatellite[] = [], clientRejections: OrbitSnapshot["client_rejections"] = [];
  const ids = new Set<number>();
  body.satellites.forEach((value: unknown, index: number) => {
    try {
      const row = decodeRow(value);
      if (ids.has(row.norad_id)) throw new Error("Duplicate NORAD identifier");
      ids.add(row.norad_id);
      satellites.push(row);
    } catch (error: unknown) {
      clientRejections.push({ index, reason: error instanceof Error ? error.message : "Invalid orbit row" });
    }
  });
  if (body.satellites.length && !satellites.length) throw new Error("No usable orbit row");
  return { schema_version: 1, fetched_at: fetchedAt, satellites,
    coverage: { completeness, groups }, client_rejections: clientRejections };
}

export function createSatelliteRecord(value: Satellite | OrbitSatellite): satellite.SatRec | null {
  try {
    const orbit = "orbit" in value ? decodeOrbit(value.orbit, value.norad_id)
      : decodeOrbit({ format: "tle", line1: value.tle_line1, line2: value.tle_line2 }, value.norad_id);
    const record = orbit.format === "tle"
      ? satellite.twoline2satrec(orbit.line1, orbit.line2)
      // Classification stays in our domain record. The propagator ignores it;
      // its current type omits the valid "S" classification.
      : satellite.json2satrec({ ...orbit.elements, CLASSIFICATION_TYPE: undefined });
    return record.error === 0 && record.satnum === String(value.norad_id) ? record : null;
  } catch {
    return null;
  }
}

export interface SatellitePosition {
  position_teme_km: { x: number; y: number; z: number };
  velocity_teme_km_s: { x: number; y: number; z: number };
  longitude_deg: number;
  latitude_deg: number;
  altitude_m: number;
}

export function propagateSatellite(record: satellite.SatRec, date: Date): SatellitePosition | null {
  if (!Number.isFinite(date.getTime())) return null;
  try {
    const result = satellite.propagate(record, date);
    if (!result || !result.position || !result.velocity) return null;
    const position = result.position, velocity = result.velocity;
    if (![position.x, position.y, position.z, velocity.x, velocity.y, velocity.z].every(Number.isFinite)) {
      return null;
    }
    const geo = satellite.eciToGeodetic(position, satellite.gstime(date));
    const longitude = satellite.degreesLong(geo.longitude), latitude = satellite.degreesLat(geo.latitude);
    const altitudeM = geo.height * 1000;
    if (![longitude, latitude, altitudeM].every(Number.isFinite) || altitudeM < 0) return null;
    return { position_teme_km: position, velocity_teme_km_s: velocity,
      longitude_deg: longitude, latitude_deg: latitude, altitude_m: altitudeM };
  } catch {
    return null;
  }
}

function elementKey(value: Satellite | OrbitSatellite): string {
  const orbit = "orbit" in value ? value.orbit : { format: "tle", line1: value.tle_line1, line2: value.tle_line2 };
  return `${value.norad_id}:${JSON.stringify(orbit)}`;
}

/** Parsing follows element changes, never time ticks or display metadata updates. */
export class SatelliteRecordCache {
  private readonly records = new Map<string, satellite.SatRec | null>();

  get(value: Satellite | OrbitSatellite): satellite.SatRec | null {
    const key = elementKey(value);
    if (!this.records.has(key)) this.records.set(key, createSatelliteRecord(value));
    return this.records.get(key) ?? null;
  }

  retain(values: readonly (Satellite | OrbitSatellite)[]): void {
    const retained = new Set(values.map(elementKey));
    for (const key of this.records.keys()) {
      if (!retained.has(key)) this.records.delete(key);
    }
  }
}
