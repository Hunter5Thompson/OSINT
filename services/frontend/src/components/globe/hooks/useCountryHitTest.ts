import RBush from "rbush";
import { useEffect, useState } from "react";
import { feature as topojsonFeature } from "topojson-client";
import { polygonContains } from "./pointInPolygon";

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

function bboxOf(geom: GeoJSON.Polygon | GeoJSON.MultiPolygon): [number, number, number, number] {
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  const polys = geom.type === "Polygon" ? [geom.coordinates] : geom.coordinates;
  for (const poly of polys) {
    for (const ring of poly as number[][][]) {
      for (const coord of ring) {
        const x = coord[0]!;
        const y = coord[1]!;
        if (x < minX) minX = x; if (y < minY) minY = y;
        if (x > maxX) maxX = x; if (y > maxY) maxY = y;
      }
    }
  }
  return [minX, minY, maxX, maxY];
}

export function buildCountryIndex(features: CountryFeature[]): CountryIndex {
  const tree: CountryIndex = new RBush<BboxNode>();
  const items: BboxNode[] = features.map((f, index) => {
    const [minX, minY, maxX, maxY] = bboxOf(f.geometry);
    return { minX, minY, maxX, maxY, index };
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
  const candidates = index.search({ minX: lon, minY: lat, maxX: lon, maxY: lat });
  for (const c of candidates) {
    const f = features[c.index]!;
    if (!polygonContains(f.geometry, lon, lat)) continue;
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

export function useCountryHitTest(): LoaderState {
  const [state, setState] = useState<LoaderState>({
    features: [], index: null, topoIndex: {}, countries: {},
  });

  useEffect(() => {
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
  }, []);

  return state;
}
