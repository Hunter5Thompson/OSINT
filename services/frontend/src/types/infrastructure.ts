export type DatacenterTier = "III" | "IV" | "hyperscaler";
export type RefineryStatus = "active" | "planned" | "shutdown";
export type FacilityType = "refinery" | "lng_terminal" | "chemical_plant";

/**
 * coord_quality records how a feature's coordinates were sourced and validated.
 *  - "campus_verified"   — manually researched against an authoritative source
 *                          (operator press release, baxtel.com, DCD article);
 *                          source_url MUST be set.
 *  - "wikidata_verified" — coords match a live Wikidata wdt:P625 value within
 *                          5 km of the existing dataset's value (or replaced it).
 *  - "legacy"            — coords from the original hand-curated dataset, not
 *                          re-verified yet.
 */
export type CoordQuality = "campus_verified" | "wikidata_verified" | "legacy";

interface InfraProvenance {
  qid?: string;            // Wikidata Q-ID (e.g. "Q3417395")
  source_url?: string;     // canonical citation URL
  coord_quality?: CoordQuality;
  coord_source?: string;   // free-text describing where the coord came from
                           // (e.g. "wikidata", "https://baxtel.com/...")
}

export interface DatacenterProperties extends InfraProvenance {
  name: string;
  operator: string;
  tier: DatacenterTier;
  capacity_mw: number | null;
  country: string;
  city: string;
  latitude?: number;
  longitude?: number;
}

export interface RefineryProperties extends InfraProvenance {
  name: string;
  operator: string;
  capacity_bpd: number;
  country: string;
  status: RefineryStatus;
  facility_type?: FacilityType;
  capacity_text?: string;
  latitude?: number;
  longitude?: number;
  image_url?: string;
  specs?: string[];
}

export interface InfraFeature<T> {
  type: "Feature";
  geometry: {
    type: "Point";
    coordinates: [number, number]; // [lon, lat]
  };
  properties: T;
}

export interface InfraGeoJSON<T> {
  type: "FeatureCollection";
  features: InfraFeature<T>[];
}

export type DatacenterGeoJSON = InfraGeoJSON<DatacenterProperties>;
export type RefineryGeoJSON = InfraGeoJSON<RefineryProperties>;
