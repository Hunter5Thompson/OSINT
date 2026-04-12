export type DatacenterTier = "III" | "IV" | "hyperscaler";
export type RefineryStatus = "active" | "planned" | "shutdown";

export interface DatacenterProperties {
  name: string;
  operator: string;
  tier: DatacenterTier;
  capacity_mw: number | null;
  country: string;
  city: string;
}

export interface RefineryProperties {
  name: string;
  operator: string;
  capacity_bpd: number;
  country: string;
  status: RefineryStatus;
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
