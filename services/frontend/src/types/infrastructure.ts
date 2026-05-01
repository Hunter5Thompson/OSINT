export type DatacenterTier = "III" | "IV" | "hyperscaler";
export type RefineryStatus = "active" | "planned" | "shutdown";
export type FacilityType = "refinery" | "lng_terminal" | "chemical_plant";

export interface DatacenterProperties {
  name: string;
  operator: string;
  tier: DatacenterTier;
  capacity_mw: number | null;
  country: string;
  city: string;
  latitude?: number;
  longitude?: number;
}

export interface RefineryProperties {
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
  source_url?: string;
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
