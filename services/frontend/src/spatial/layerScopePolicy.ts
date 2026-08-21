import type { ScopeKind } from "./contracts";
import type { SpatialApplicationV1 } from "../types";

export type SpatialRelation = "occurs-in" | "about" | "intersects" | "context";
export type ScopeBehavior = "strict" | "dim-outside" | "global-context" | "unsupported";
export type SpatialPrecision =
  | "semantic-key"
  | "point-in-boundary"
  | "bbox-approximate"
  | "global";

export interface LayerSpatialCapability {
  readonly layerId: LayerSpatialId;
  readonly relation: SpatialRelation;
  readonly behavior: ScopeBehavior;
  readonly supportedKinds: readonly ScopeKind[];
  readonly precision: SpatialPrecision;
}

export type LayerSpatialId =
  | "chronik-events"
  | "geo-events-hotspots-earthquakes"
  | "aircraft-vessel-tracks"
  | "satellites"
  | "cables-pipelines"
  | "facilities"
  | "terrain-imagery-3d"
  | "country-admin-borders";

const ALL_SCOPE_KINDS = ["world", "country", "admin1", "admin2"] as const;

export const LAYER_SPATIAL_CAPABILITIES: Readonly<
  Record<LayerSpatialId, LayerSpatialCapability>
> = {
  "chronik-events": {
    layerId: "chronik-events",
    relation: "occurs-in",
    behavior: "strict",
    supportedKinds: ALL_SCOPE_KINDS,
    precision: "bbox-approximate",
  },
  "geo-events-hotspots-earthquakes": {
    layerId: "geo-events-hotspots-earthquakes",
    relation: "occurs-in",
    behavior: "strict",
    supportedKinds: ALL_SCOPE_KINDS,
    precision: "point-in-boundary",
  },
  "aircraft-vessel-tracks": {
    layerId: "aircraft-vessel-tracks",
    relation: "intersects",
    behavior: "dim-outside",
    supportedKinds: ALL_SCOPE_KINDS,
    precision: "bbox-approximate",
  },
  satellites: {
    layerId: "satellites",
    relation: "context",
    behavior: "global-context",
    supportedKinds: ALL_SCOPE_KINDS,
    precision: "global",
  },
  "cables-pipelines": {
    layerId: "cables-pipelines",
    relation: "intersects",
    behavior: "unsupported",
    supportedKinds: ["world"],
    precision: "global",
  },
  facilities: {
    layerId: "facilities",
    relation: "occurs-in",
    behavior: "strict",
    supportedKinds: ALL_SCOPE_KINDS,
    precision: "point-in-boundary",
  },
  "terrain-imagery-3d": {
    layerId: "terrain-imagery-3d",
    relation: "context",
    behavior: "global-context",
    supportedKinds: ALL_SCOPE_KINDS,
    precision: "global",
  },
  "country-admin-borders": {
    layerId: "country-admin-borders",
    relation: "context",
    behavior: "global-context",
    supportedKinds: ALL_SCOPE_KINDS,
    precision: "global",
  },
};

export function layerSpatialCapability(layerId: LayerSpatialId): LayerSpatialCapability {
  return LAYER_SPATIAL_CAPABILITIES[layerId];
}

export interface ChronikSpatialStatus {
  readonly label: string;
  readonly title: string;
  readonly tone: "global" | "loading" | "complete" | "partial" | "unavailable";
}

const PRECISION_LABEL: Readonly<Record<SpatialApplicationV1["mode"], string>> = {
  global: "global",
  semantic_key: "semantic key",
  point_in_boundary: "point boundary",
  bbox_approximate: "bbox approx",
};

export function chronikSpatialStatus(
  application: SpatialApplicationV1 | null,
  loading: boolean,
  error: Error | null,
): ChronikSpatialStatus {
  if (error !== null) {
    return {
      label: "scope unavailable",
      title: "Spatial timeline data is unavailable",
      tone: "unavailable",
    };
  }
  if (application === null) {
    return loading
      ? { label: "scope loading", title: "Loading spatial timeline data", tone: "loading" }
      : {
          label: "scope unavailable",
          title: "No spatial timeline response is available",
          tone: "unavailable",
        };
  }
  if (application.mode === "global") {
    return {
      label: `global · ${application.completeness}`,
      title: loading ? "Global timeline response; refreshing" : "Global timeline response",
      tone: "global",
    };
  }

  const excluded = application.excluded_unlocated_count
    + application.excluded_conflict_count
    + application.excluded_stale_revision_count
    + application.excluded_unsupported_count;
  const excludedLabel = excluded > 0 ? ` · excluded ${excluded}` : "";
  return {
    label: `${application.relation} · ${PRECISION_LABEL[application.mode]} · ${application.completeness}${excludedLabel}`,
    title: [
      `included ${application.included_count}`,
      `unlocated ${application.excluded_unlocated_count}`,
      `conflict ${application.excluded_conflict_count}`,
      `stale revision ${application.excluded_stale_revision_count}`,
      `unsupported ${application.excluded_unsupported_count}`,
      ...(loading ? ["refreshing"] : []),
    ].join(" · "),
    tone: application.completeness,
  };
}
