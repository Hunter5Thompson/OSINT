import { useEffect, useState } from "react";

export type StrategicKind = "nuclearPlants" | "icbmBases" | "militaryBases";
export interface StrategicSite {
  id: string; name: string; country: string; kind: StrategicKind;
  latitude: number; longitude: number; capacityMw?: number | null;
  source: string; sourceLabel: string; coordinateSource?: string; note: string;
}
export interface RegionProfile {
  key: string; country: string; name: string; division: string;
  source: string; sourceLabel: string;
  capital: null | { name: string; latitude: number; longitude: number; population: number | null; timezone: string | null };
}
export function regionsInScope(regions: RegionProfile[], scopeKey: string): RegionProfile[] {
  if (scopeKey.startsWith("country:")) return regions.filter((region) => region.country === scopeKey.slice(8));
  return regions.filter((region) => region.key === scopeKey);
}
export const STRATEGIC_LABELS: Record<StrategicKind, string> = {
  nuclearPlants: "Nuclear Power Plants", icbmBases: "ICBM Bases", militaryBases: "Major Military Bases",
};
const record = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null;
const https = (value: unknown): value is string => typeof value === "string" && /^https:\/\//.test(value);
const coordinate = (value: unknown, limit: number): value is number => typeof value === "number" && Number.isFinite(value) && Math.abs(value) <= limit;

export function decodeSites(value: unknown): StrategicSite[] {
  if (!Array.isArray(value) || !value.every((s: unknown) => record(s)
    && ["id", "name", "country", "sourceLabel", "note"].every((k) => typeof s[k] === "string")
    && typeof s.kind === "string" && Object.hasOwn(STRATEGIC_LABELS, s.kind)
    && https(s.source) && (s.coordinateSource === undefined || https(s.coordinateSource))
    && coordinate(s.latitude, 90) && coordinate(s.longitude, 180)
    && (s.capacityMw == null || (typeof s.capacityMw === "number" && Number.isFinite(s.capacityMw) && s.capacityMw >= 0)))) {
    throw new Error("Invalid strategic reference data");
  }
  return value as StrategicSite[];
}
export function decodeRegions(value: unknown): RegionProfile[] {
  if (!Array.isArray(value) || !value.every((r: unknown) => record(r)
    && ["key", "country", "name", "division", "sourceLabel"].every((k) => typeof r[k] === "string")
    && https(r.source) && (r.capital === null || (record(r.capital)
      && typeof r.capital.name === "string" && coordinate(r.capital.latitude, 90)
      && coordinate(r.capital.longitude, 180)
      && (r.capital.population === null || (typeof r.capital.population === "number" && Number.isFinite(r.capital.population)))
      && (r.capital.timezone === null || typeof r.capital.timezone === "string"))))) {
    throw new Error("Invalid regional reference data");
  }
  return value as RegionProfile[];
}

/** One abortable request per mounted layer, with an explicit retry/error state. */
export function useReferenceData<T>(path: string, enabled: boolean, decode: (value: unknown) => T) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState(false);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    setError(false);
    void fetch(path, { signal: controller.signal }).then(async (response) => {
      if (!response.ok) throw new Error(`Reference data: HTTP ${response.status}`);
      const result = decode(await response.json());
      if (!controller.signal.aborted) setData(result);
    }).catch(() => { if (!controller.signal.aborted) setError(true); });
    return () => controller.abort();
  }, [path, enabled, decode, attempt]);
  return { data, error, retry: () => setAttempt((value) => value + 1) };
}
