import RBush from "rbush";
import { useEffect, useState } from "react";
import { feature as topojsonFeature } from "topojson-client";

import {
  minimalLongitudeSpans,
  type LongitudeSpan,
} from "../../../spatial/geometry";

type PreparedPosition = readonly [longitude: number, latitude: number];

interface PreparedRing {
  readonly meanLongitude: number;
  readonly positions: readonly PreparedPosition[];
}

interface PreparedPolygon {
  readonly outer: PreparedRing;
  readonly holes: readonly PreparedRing[];
}

interface PreparedLegacyGeometry {
  readonly polygons: readonly PreparedPolygon[];
}

interface PreparedCountryGeometry {
  readonly geometry: PreparedLegacyGeometry;
  readonly indexSpans: readonly PreparedIndexSpan[];
}

interface PreparedIndexSpan extends LongitudeSpan {
  readonly south: number;
  readonly north: number;
}

const COORDINATE_EPSILON = 1e-12;

export interface CountryFeature {
  m49: string;
  name: string;
  geometry: GeoJSON.Polygon | GeoJSON.MultiPolygon;
}

export const COUNTRY_INDEX_REJECTION_DIAGNOSTIC_LIMIT = 10;

export type CountryIndexDiagnostic =
  | {
      readonly code: "legacy_country_geometry_rejected";
      readonly featureIndex: number;
    }
  | {
      readonly code: "legacy_country_geometry_rejections_suppressed";
      readonly suppressedCount: number;
    };

export interface CountryIndexDiagnostics {
  report(event: CountryIndexDiagnostic): void;
}

const NOOP_COUNTRY_INDEX_DIAGNOSTICS: CountryIndexDiagnostics = {
  report: () => undefined,
};

const CONSOLE_COUNTRY_INDEX_DIAGNOSTICS: CountryIndexDiagnostics = {
  report: (event) => {
    console.warn("Legacy country geometry index diagnostic", event);
  },
};

interface BboxNode {
  minX: number;
  minY: number;
  maxX: number;
  maxY: number;
  index: number;
  geometry: PreparedLegacyGeometry;
}

export type CountryIndex = RBush<BboxNode>;

interface CountryDatum {
  iso3: string;
  m49: string;
  capital: { name: string; lat: number; lon: number } | null;
}

interface EndonymJson {
  _topoIndex: Record<string, string | null>;
  countries: Record<string, CountryDatum>;
}

export interface CountryHit {
  m49: string;
  iso3: string | null;
  name: string;
  geometry: GeoJSON.Polygon | GeoJSON.MultiPolygon;
  capital: { name: string; coords: { lon: number; lat: number } } | null;
}

function prepareRing(rawRing: readonly GeoJSON.Position[]): PreparedRing | null {
  if (rawRing.length < 4) return null;
  const positions: PreparedPosition[] = [];
  for (const rawPosition of rawRing) {
    const longitude = rawPosition[0];
    const latitude = rawPosition[1];
    if (
      typeof longitude !== "number"
      || typeof latitude !== "number"
      || !Number.isFinite(longitude)
      || longitude < -180
      || longitude > 180
      || !Number.isFinite(latitude)
      || latitude < -90
      || latitude > 90
    ) {
      return null;
    }
    const previous = positions.at(-1);
    let unwrappedLongitude = longitude;
    if (previous !== undefined) {
      while (unwrappedLongitude - previous[0] > 180) unwrappedLongitude -= 360;
      while (unwrappedLongitude - previous[0] < -180) unwrappedLongitude += 360;
    }
    positions.push([unwrappedLongitude, latitude]);
  }
  const first = positions[0];
  const last = positions.at(-1);
  if (first === undefined || last === undefined) return null;
  const meanPositions = Math.abs(first[0] - last[0]) <= COORDINATE_EPSILON
      && Math.abs(first[1] - last[1]) <= COORDINATE_EPSILON
    ? positions.slice(0, -1)
    : positions;
  if (meanPositions.length === 0) return null;
  return {
    meanLongitude: meanPositions.reduce(
      (total, [longitude]) => total + longitude,
      0,
    ) / meanPositions.length,
    positions,
  };
}

function prepareLegacyGeometry(
  geometry: GeoJSON.Polygon | GeoJSON.MultiPolygon,
): PreparedCountryGeometry | null {
  const rawPolygons = geometry.type === "Polygon"
    ? [geometry.coordinates]
    : geometry.coordinates;
  const polygons: PreparedPolygon[] = [];
  const indexSpans: PreparedIndexSpan[] = [];

  for (const rawPolygon of rawPolygons) {
    const rings: PreparedRing[] = [];
    for (const rawRing of rawPolygon) {
      const prepared = prepareRing(rawRing);
      if (prepared === null) return null;
      rings.push(prepared);
    }
    const outer = rings[0];
    if (outer === undefined) return null;
    polygons.push({ outer, holes: rings.slice(1) });
    const positions = rings.flatMap((ring) => ring.positions);
    const latitudes = positions.map((position) => position[1]);
    const south = Math.min(...latitudes);
    const north = Math.max(...latitudes);
    for (const span of minimalLongitudeSpans(
      positions.map((position) => position[0]),
    )) {
      indexSpans.push({ ...span, south, north });
    }
  }
  if (polygons.length === 0 || indexSpans.length === 0) {
    return null;
  }
  return {
    geometry: { polygons },
    indexSpans,
  };
}

function prepareLegacyGeometryFailClosed(
  geometry: GeoJSON.Polygon | GeoJSON.MultiPolygon,
): PreparedCountryGeometry | null {
  try {
    return prepareLegacyGeometry(geometry);
  } catch {
    return null;
  }
}

function countryIndexNodes(
  prepared: PreparedCountryGeometry,
  index: number,
): BboxNode[] {
  return prepared.indexSpans.map((span) => ({
    minX: span.west,
    minY: span.south,
    maxX: span.east,
    maxY: span.north,
    index,
    geometry: prepared.geometry,
  }));
}

function pointOnSegment(
  longitude: number,
  latitude: number,
  left: PreparedPosition,
  right: PreparedPosition,
): boolean {
  const cross = (longitude - left[0]) * (right[1] - left[1])
    - (latitude - left[1]) * (right[0] - left[0]);
  if (Math.abs(cross) > COORDINATE_EPSILON) return false;
  return longitude >= Math.min(left[0], right[0]) - COORDINATE_EPSILON
    && longitude <= Math.max(left[0], right[0]) + COORDINATE_EPSILON
    && latitude >= Math.min(left[1], right[1]) - COORDINATE_EPSILON
    && latitude <= Math.max(left[1], right[1]) + COORDINATE_EPSILON;
}

type PreparedRingContainment = "boundary" | "inside" | "outside";

function classifyPreparedRing(
  ring: PreparedRing,
  longitude: number,
  latitude: number,
): PreparedRingContainment {
  const queryLongitude = longitude
    + Math.round((ring.meanLongitude - longitude) / 360) * 360;
  let inside = false;
  for (let index = 0, previousIndex = ring.positions.length - 1;
    index < ring.positions.length;
    previousIndex = index, index += 1) {
    const left = ring.positions[index];
    const right = ring.positions[previousIndex];
    if (left === undefined || right === undefined) continue;
    if (pointOnSegment(queryLongitude, latitude, left, right)) return "boundary";
    const crosses = (left[1] > latitude) !== (right[1] > latitude);
    if (!crosses) continue;
    const crossingLongitude = left[0]
      + (latitude - left[1]) * (right[0] - left[0])
        / (right[1] - left[1]);
    if (queryLongitude < crossingLongitude) inside = !inside;
  }
  return inside ? "inside" : "outside";
}

function legacyGeometryContains(
  geometry: PreparedLegacyGeometry,
  longitude: number,
  latitude: number,
): boolean {
  for (const polygon of geometry.polygons) {
    const outer = classifyPreparedRing(polygon.outer, longitude, latitude);
    if (outer === "outside") continue;
    if (outer === "boundary") return true;
    let insideHole = false;
    for (const hole of polygon.holes) {
      const containment = classifyPreparedRing(hole, longitude, latitude);
      if (containment === "boundary") return true;
      if (containment === "inside") {
        insideHole = true;
        break;
      }
    }
    if (!insideHole) return true;
  }
  return false;
}

export function buildCountryIndex(
  features: CountryFeature[],
  diagnostics: CountryIndexDiagnostics = NOOP_COUNTRY_INDEX_DIAGNOSTICS,
): CountryIndex {
  const tree: CountryIndex = new RBush<BboxNode>();
  const items: BboxNode[] = [];
  let rejectedCount = 0;
  features.forEach((feature, index) => {
    const prepared = prepareLegacyGeometryFailClosed(feature.geometry);
    if (prepared === null) {
      if (rejectedCount < COUNTRY_INDEX_REJECTION_DIAGNOSTIC_LIMIT) {
        diagnostics.report({
          code: "legacy_country_geometry_rejected",
          featureIndex: index,
        });
      }
      rejectedCount += 1;
      return;
    }
    items.push(...countryIndexNodes(prepared, index));
  });
  if (rejectedCount > COUNTRY_INDEX_REJECTION_DIAGNOSTIC_LIMIT) {
    diagnostics.report({
      code: "legacy_country_geometry_rejections_suppressed",
      suppressedCount: rejectedCount - COUNTRY_INDEX_REJECTION_DIAGNOSTIC_LIMIT,
    });
  }
  tree.load(items);
  return tree;
}

export function hitTestCountry(
  index: CountryIndex,
  features: CountryFeature[],
  topoIndex: Record<string, string | null>,
  countries: Record<string, CountryDatum>,
  lon: number,
  lat: number
): CountryHit | null {
  if (
    !Number.isFinite(lon)
    || lon < -180
    || lon > 180
    || !Number.isFinite(lat)
    || lat < -90
    || lat > 90
  ) {
    return null;
  }
  const candidates = index.search({ minX: lon, minY: lat, maxX: lon, maxY: lat });
  const visitedFeatureIndexes = new Set<number>();
  for (const c of candidates) {
    if (visitedFeatureIndexes.has(c.index)) continue;
    visitedFeatureIndexes.add(c.index);
    const f = features[c.index];
    if (f === undefined || !legacyGeometryContains(c.geometry, lon, lat)) continue;
    const iso3 = topoIndex[f.m49] ?? null;
    const datum = iso3 ? countries[iso3] : null;
    return {
      m49: f.m49,
      iso3,
      name: f.name,
      geometry: f.geometry,
      capital: datum?.capital
        ? { name: datum.capital.name, coords: { lon: datum.capital.lon, lat: datum.capital.lat } }
        : null,
    };
  }
  return null;
}

interface LoaderState {
  features: CountryFeature[];
  index: CountryIndex | null;
  topoIndex: Record<string, string | null>;
  countries: Record<string, CountryDatum>;
}

const EMPTY_LOADER_STATE: LoaderState = {
    features: [], index: null, topoIndex: {}, countries: {},
};

export function useCountryHitTest(enabled = true): LoaderState {
  const [state, setState] = useState<LoaderState>(EMPTY_LOADER_STATE);

  useEffect(() => {
    if (!enabled) {
      setState(EMPTY_LOADER_STATE);
      return;
    }
    let cancelled = false;
    (async () => {
      const [topoRes, endoRes] = await Promise.all([
        fetch("/countries-110m.json"),
        fetch("/country-endonyms.json"),
      ]);
      const topo = await topoRes.json();
      const endo = (await endoRes.json()) as EndonymJson;
      const fc = topojsonFeature(topo, topo.objects.countries) as unknown as GeoJSON.FeatureCollection;
      const features: CountryFeature[] = fc.features.map((f) => {
        const props = (f.properties as { name?: string } | null) ?? {};
        const name = props.name ?? "";
        // PLAN-FIX: 3 features in countries-110m.json (N. Cyprus, Somaliland, Kosovo)
        // have no UN M.49 id. Fall back to properties.name as the key, matching
        // what Task 2 seeded into _topoIndex. Without this, String(undefined)
        // produces the literal "undefined" and breaks the lookup.
        const key = f.id != null ? String(f.id) : name;
        return {
          m49: key,
          name,
          geometry: f.geometry as GeoJSON.Polygon | GeoJSON.MultiPolygon,
        };
      });
      if (cancelled) return;
      setState({
        features,
        index: buildCountryIndex(features, CONSOLE_COUNTRY_INDEX_DIAGNOSTICS),
        topoIndex: endo._topoIndex,
        countries: endo.countries,
      });
    })().catch((e) => console.error("useCountryHitTest load failed:", e));
    return () => { cancelled = true; };
  }, [enabled]);

  return state;
}
