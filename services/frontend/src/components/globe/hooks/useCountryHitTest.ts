import RBush from "rbush";
import { useEffect, useState } from "react";
import { feature as topojsonFeature } from "topojson-client";

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
  readonly minX: number;
  readonly minY: number;
  readonly maxX: number;
  readonly maxY: number;
}

const COORDINATE_EPSILON = 1e-12;

export interface CountryFeature {
  m49: string;
  name: string;
  geometry: GeoJSON.Polygon | GeoJSON.MultiPolygon;
}

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
  let minX = Number.POSITIVE_INFINITY;
  let minY = Number.POSITIVE_INFINITY;
  let maxX = Number.NEGATIVE_INFINITY;
  let maxY = Number.NEGATIVE_INFINITY;
  let crossesDateline = false;

  for (const rawPolygon of rawPolygons) {
    const rings: PreparedRing[] = [];
    for (const rawRing of rawPolygon) {
      const prepared = prepareRing(rawRing);
      if (prepared === null) return null;
      rings.push(prepared);
      for (let index = 0; index < rawRing.length; index += 1) {
        const position = rawRing[index];
        if (position === undefined) return null;
        const longitude = position[0];
        const latitude = position[1];
        if (typeof longitude !== "number" || typeof latitude !== "number") return null;
        minX = Math.min(minX, longitude);
        minY = Math.min(minY, latitude);
        maxX = Math.max(maxX, longitude);
        maxY = Math.max(maxY, latitude);
        const next = rawRing[index + 1];
        if (
          next !== undefined
          && typeof next[0] === "number"
          && Math.abs(next[0] - longitude) > 180
        ) {
          crossesDateline = true;
        }
      }
    }
    const outer = rings[0];
    if (outer === undefined) return null;
    polygons.push({ outer, holes: rings.slice(1) });
  }
  if (
    polygons.length === 0
    || !Number.isFinite(minX)
    || !Number.isFinite(minY)
    || !Number.isFinite(maxX)
    || !Number.isFinite(maxY)
  ) {
    return null;
  }
  return {
    geometry: { polygons },
    minX: crossesDateline ? -180 : minX,
    minY,
    maxX: crossesDateline ? 180 : maxX,
    maxY,
  };
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

export function buildCountryIndex(features: CountryFeature[]): CountryIndex {
  const tree: CountryIndex = new RBush<BboxNode>();
  const items: BboxNode[] = [];
  features.forEach((feature, index) => {
    const prepared = prepareLegacyGeometry(feature.geometry);
    if (prepared === null) return;
    items.push({
      minX: prepared.minX,
      minY: prepared.minY,
      maxX: prepared.maxX,
      maxY: prepared.maxY,
      index,
      geometry: prepared.geometry,
    });
  });
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
  for (const c of candidates) {
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
        index: buildCountryIndex(features),
        topoIndex: endo._topoIndex,
        countries: endo.countries,
      });
    })().catch((e) => console.error("useCountryHitTest load failed:", e));
    return () => { cancelled = true; };
  }, [enabled]);

  return state;
}
