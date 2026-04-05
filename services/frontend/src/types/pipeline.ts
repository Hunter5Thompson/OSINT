/** GeoJSON Feature properties for a pipeline segment. */
export interface PipelineProperties {
  name: string;
  tier: "major" | "regional" | "local";
  type: "oil" | "gas" | "lng" | "mixed";
  status: "active" | "planned" | "under_construction";
  operator: string | null;
  capacity_bcm: number | null;
  length_km: number | null;
  countries: string[];
}

/** A single GeoJSON Feature for a pipeline. */
export interface PipelineFeature {
  type: "Feature";
  properties: PipelineProperties;
  geometry: {
    type: "LineString" | "MultiLineString";
    coordinates: number[][] | number[][][];
  };
}

/** Root GeoJSON FeatureCollection for pipelines. */
export interface PipelineGeoJSON {
  type: "FeatureCollection";
  features: PipelineFeature[];
}

/** Color mapping for pipeline types. */
export const PIPELINE_COLORS: Record<PipelineProperties["type"], string> = {
  oil: "#eab308",
  gas: "#f97316",
  lng: "#a855f7",
  mixed: "#d4cdc0",
};

/** Camera altitude thresholds for LOD tiers (meters). */
export const PIPELINE_LOD_THRESHOLDS = {
  major: Infinity,
  regional: 5_000_000,
  local: 1_000_000,
} as const;
