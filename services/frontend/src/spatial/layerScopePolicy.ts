import type {
  ContainmentSnapshot,
  ScopeKind,
} from "./contracts";
import type { LayerVisibility, SpatialApplicationV1 } from "../types";

export type SpatialRelation = "occurs-in" | "about" | "intersects" | "context";
export type ScopeBehavior =
  | "strict"
  | "dim-outside"
  | "global-context"
  | "scope-presentation"
  | "unsupported";
export type SpatialPrecision =
  | "semantic-key"
  | "point-in-boundary"
  | "bbox-approximate"
  | "global";
export type SpatialStalePolicy =
  | "invalidate-on-semantic-commit"
  | "response-scope-token"
  | "scope-presentation-generation"
  | "not-applicable";
export type SpatialUnsupportedBehavior =
  | "hide"
  | "label-global-context"
  | "label-scope-presentation";

export type LayerSpatialId = keyof LayerVisibility;

export interface LayerSpatialCapability {
  readonly layerId: LayerSpatialId;
  readonly relation: SpatialRelation;
  readonly behavior: ScopeBehavior;
  readonly supportedKinds: readonly ScopeKind[];
  readonly precision: SpatialPrecision;
  readonly stalePolicy: SpatialStalePolicy;
  readonly unsupportedBehavior: SpatialUnsupportedBehavior;
}

const ALL_SCOPE_KINDS = ["world", "country", "admin1", "admin2"] as const;
const WORLD_ONLY = ["world"] as const;

const unsupported = (
  layerId: LayerSpatialId,
  relation: SpatialRelation,
): LayerSpatialCapability => ({
  layerId,
  relation,
  behavior: "unsupported",
  supportedKinds: WORLD_ONLY,
  precision: "global",
  stalePolicy: "not-applicable",
  unsupportedBehavior: "hide",
});

export const LAYER_SPATIAL_CAPABILITIES: Readonly<
  Record<LayerSpatialId, LayerSpatialCapability>
> = {
  flights: unsupported("flights", "intersects"),
  satellites: {
    layerId: "satellites",
    relation: "context",
    behavior: "global-context",
    supportedKinds: ALL_SCOPE_KINDS,
    precision: "global",
    stalePolicy: "not-applicable",
    unsupportedBehavior: "label-global-context",
  },
  earthquakes: {
    layerId: "earthquakes",
    relation: "occurs-in",
    behavior: "strict",
    supportedKinds: ALL_SCOPE_KINDS,
    precision: "point-in-boundary",
    stalePolicy: "invalidate-on-semantic-commit",
    unsupportedBehavior: "hide",
  },
  vessels: unsupported("vessels", "intersects"),
  cctv: unsupported("cctv", "occurs-in"),
  events: {
    layerId: "events",
    relation: "occurs-in",
    behavior: "strict",
    supportedKinds: ALL_SCOPE_KINDS,
    precision: "bbox-approximate",
    stalePolicy: "response-scope-token",
    unsupportedBehavior: "hide",
  },
  cables: unsupported("cables", "intersects"),
  pipelines: unsupported("pipelines", "intersects"),
  countryBorders: {
    layerId: "countryBorders",
    relation: "context",
    behavior: "scope-presentation",
    supportedKinds: ALL_SCOPE_KINDS,
    precision: "global",
    stalePolicy: "scope-presentation-generation",
    unsupportedBehavior: "label-scope-presentation",
  },
  cityBuildings: {
    layerId: "cityBuildings",
    relation: "context",
    behavior: "global-context",
    supportedKinds: ALL_SCOPE_KINDS,
    precision: "global",
    stalePolicy: "not-applicable",
    unsupportedBehavior: "label-global-context",
  },
  firmsHotspots: unsupported("firmsHotspots", "occurs-in"),
  milAircraft: unsupported("milAircraft", "intersects"),
  datacenters: unsupported("datacenters", "occurs-in"),
  refineries: unsupported("refineries", "occurs-in"),
  eonet: unsupported("eonet", "occurs-in"),
  gdacs: unsupported("gdacs", "occurs-in"),
};

export function layerSpatialCapability(layerId: LayerSpatialId): LayerSpatialCapability {
  return LAYER_SPATIAL_CAPABILITIES[layerId];
}

export interface LayerSpatialStatus {
  readonly render: boolean;
  readonly label: string;
  readonly title: string;
  readonly tone:
    | "strict"
    | "approximate"
    | "global"
    | "presentation"
    | "loading"
    | "unavailable"
    | "unsupported";
}

export type LayerSpatialStatuses = Readonly<
  Record<LayerSpatialId, LayerSpatialStatus>
>;

export function layerSpatialStatus(
  layerId: LayerSpatialId,
  scopeKind: ScopeKind | null,
  containment: ContainmentSnapshot,
): LayerSpatialStatus {
  const capability = layerSpatialCapability(layerId);
  if (scopeKind === null) {
    if (capability.behavior === "global-context") {
      return {
        render: true,
        label: "global context",
        title: `${layerId} remains unfiltered global context`,
        tone: "global",
      };
    }
    return {
      render: false,
      label: "scope hydrating",
      title: `${layerId} is hidden until the initial scope commits`,
      tone: "loading",
    };
  }
  if (!capability.supportedKinds.includes(scopeKind)) {
    return {
      render: false,
      label: "unavailable in scope",
      title: `${layerId} is unavailable outside world scope`,
      tone: "unsupported",
    };
  }
  if (capability.behavior === "unsupported") {
    return {
      render: true,
      label: "world only",
      title: `${layerId} is available only at world scope`,
      tone: "global",
    };
  }
  if (capability.behavior === "global-context") {
    return {
      render: true,
      label: "global context",
      title: `${layerId} remains unfiltered global context`,
      tone: "global",
    };
  }
  if (capability.behavior === "scope-presentation") {
    return {
      render: true,
      label: "scope presentation",
      title: `${layerId} presents the committed scope boundary`,
      tone: "presentation",
    };
  }
  if (capability.precision === "point-in-boundary") {
    if (containment.phase === "building") {
      return {
        render: false,
        label: "scope building",
        title: `${layerId} is hidden while fixed containment is building`,
        tone: "loading",
      };
    }
    if (containment.phase === "unavailable") {
      return {
        render: false,
        label: "scope unavailable",
        title: `${layerId} is hidden because fixed containment is unavailable`,
        tone: "unavailable",
      };
    }
    return {
      render: true,
      label: "strict · point boundary",
      title: `${layerId} uses strict point-in-boundary containment`,
      tone: "strict",
    };
  }
  return {
    render: true,
    label: "strict · bbox approx",
    title: `${layerId} uses a scope-token response with bbox approximation`,
    tone: "approximate",
  };
}

export function layerSpatialStatuses(
  scopeKind: ScopeKind | null,
  containment: ContainmentSnapshot,
): LayerSpatialStatuses {
  return Object.fromEntries(
    (Object.keys(LAYER_SPATIAL_CAPABILITIES) as LayerSpatialId[]).map((layerId) => [
      layerId,
      layerSpatialStatus(layerId, scopeKind, containment),
    ]),
  ) as unknown as LayerSpatialStatuses;
}

export function applyLayerSpatialPolicy(
  layers: LayerVisibility,
  scopeKind: ScopeKind | null,
  containment: ContainmentSnapshot,
): LayerVisibility {
  const scoped = { ...layers };
  for (const layerId of Object.keys(LAYER_SPATIAL_CAPABILITIES) as LayerSpatialId[]) {
    scoped[layerId] = layers[layerId]
      && layerSpatialStatus(layerId, scopeKind, containment).render;
  }
  return scoped;
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
