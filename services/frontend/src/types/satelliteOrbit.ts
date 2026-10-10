import type { Satellite } from "./index";

/** GP fields retain their source units: degrees, revolutions/day, UTC, dimensionless drag. */
export interface OMMElements {
  OBJECT_NAME: string;
  OBJECT_ID: string;
  NORAD_CAT_ID: number;
  EPOCH: string;
  MEAN_MOTION: number;
  ECCENTRICITY: number;
  INCLINATION: number;
  RA_OF_ASC_NODE: number;
  ARG_OF_PERICENTER: number;
  MEAN_ANOMALY: number;
  BSTAR: number;
  MEAN_MOTION_DOT: number;
  MEAN_MOTION_DDOT: number;
  EPHEMERIS_TYPE: 0;
  CLASSIFICATION_TYPE: "U" | "C" | "S";
  ELEMENT_SET_NO: number;
  REV_AT_EPOCH: number;
  CENTER_NAME: "EARTH";
  REF_FRAME: "TEME";
  TIME_SYSTEM: "UTC";
  MEAN_ELEMENT_THEORY: "SGP4";
}

export type OrbitElements =
  | { format: "tle"; line1: string; line2: string }
  | { format: "omm"; elements: OMMElements };

export interface OrbitSatellite extends Omit<Satellite, "tle_line1" | "tle_line2"> {
  orbit: OrbitElements;
}

export interface OrbitRejection {
  index: number;
  code: "invalid" | "unsupported";
  reason: string;
}

export interface OrbitGroupCoverage {
  group: string;
  status: "ok" | "partial" | "failed";
  accepted_records: number;
  rejected_invalid: number;
  rejected_unsupported: number;
  rejections: OrbitRejection[];
  failure_code: "transport" | "invalid_payload" | "no_usable_records" | null;
}

export interface OrbitSnapshot {
  schema_version: 1;
  fetched_at: string;
  satellites: OrbitSatellite[];
  coverage: { completeness: "complete" | "partial"; groups: OrbitGroupCoverage[] };
  /** Local decoding failures are distinct from the server's source coverage. */
  client_rejections: { index: number; reason: string }[];
}
