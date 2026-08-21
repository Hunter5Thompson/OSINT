declare const scopeKeyBrand: unique symbol;
declare const catalogRevisionBrand: unique symbol;

export type ScopeKey = string & {
  readonly [scopeKeyBrand]: "ScopeKey";
};

export type CatalogRevision = string & {
  readonly [catalogRevisionBrand]: "CatalogRevision";
};

export type ScopeKind = "world" | "country" | "admin1" | "admin2";

export type ScopeCause =
  | "country-click"
  | "child-click"
  | "breadcrumb"
  | "keyboard"
  | "search"
  | "browser-history"
  | "deep-link"
  | "programmatic";

export type EnterCause = Exclude<ScopeCause, "browser-history" | "deep-link">;

export interface ScopeSummary {
  readonly key: ScopeKey;
  readonly kind: ScopeKind;
  readonly label: string;
  readonly shortLabel: string;
  readonly parentKey: ScopeKey | null;
  readonly childrenAvailable: boolean;
  readonly presentation: "boundary" | "semantic-only";
}

export type ScopePath = readonly [ScopeSummary, ...ScopeSummary[]];

export interface SpatialQueryRef {
  readonly schemaVersion: 1;
  readonly scopeKey: ScopeKey;
  readonly catalogRevision: CatalogRevision;
  readonly boundaryPolicy: string;
}

export interface ScopeProblem {
  readonly severity: "warning" | "error";
  readonly code:
    | "INVALID_SCOPE_KEY"
    | "UNKNOWN_SCOPE"
    | "CATALOG_UNAVAILABLE"
    | "CATALOG_REVISION_UNAVAILABLE"
    | "INVALID_LINEAGE"
    | "GEOMETRY_UNAVAILABLE"
    | "ASSET_LIMIT_EXCEEDED"
    | "ASSET_BUSY"
    | "PRESENTATION_FAILED"
    | "URL_SYNC_FAILED";
  readonly target: string | null;
  readonly recoverable: boolean;
  readonly message: string;
}

export type ScopeVisualState =
  | { readonly phase: "none"; readonly stateRevision: null }
  | { readonly phase: "building"; readonly stateRevision: number }
  | { readonly phase: "ready"; readonly stateRevision: number }
  | {
      readonly phase: "unavailable";
      readonly stateRevision: number;
      readonly problem: ScopeProblem;
    };

export type SpatialScopeSnapshot =
  | {
      readonly phase: "hydrating";
      readonly stateRevision: 0;
      readonly current: null;
      readonly path: readonly [];
      readonly query: null;
      readonly pending: ScopeKey | null;
      readonly problem: ScopeProblem | null;
      readonly visual: { readonly phase: "none"; readonly stateRevision: null };
    }
  | {
      readonly phase: "ready" | "resolving";
      readonly stateRevision: number;
      readonly current: ScopeSummary;
      readonly path: ScopePath;
      readonly query: SpatialQueryRef;
      readonly pending: ScopeKey | null;
      readonly problem: ScopeProblem | null;
      readonly visual: ScopeVisualState;
    };

export type SpatialScopeCommand =
  | {
      readonly type: "enter";
      readonly target: ScopeKey;
      readonly cause: EnterCause;
    }
  | {
      readonly type: "ascend";
      readonly cause: "breadcrumb" | "keyboard";
    }
  | {
      readonly type: "hydrate";
      readonly target: ScopeKey | null;
      readonly catalogRevision: string | null;
      readonly cause: "browser-history" | "deep-link";
    }
  | {
      readonly type: "prefetch";
      readonly target: ScopeKey;
      readonly priority: "hover" | "anticipated";
    };

export type SpatialScopeResult =
  | { readonly outcome: "committed"; readonly snapshot: SpatialScopeSnapshot }
  | { readonly outcome: "unchanged"; readonly snapshot: SpatialScopeSnapshot }
  | { readonly outcome: "superseded" }
  | { readonly outcome: "cancelled" }
  | { readonly outcome: "prefetched"; readonly target: ScopeKey }
  | { readonly outcome: "failed"; readonly problem: ScopeProblem };

export interface DispatchOptions {
  readonly signal?: AbortSignal;
}

export interface SpatialScopeModule {
  getSnapshot(): SpatialScopeSnapshot;
  subscribe(listener: () => void): () => void;
  dispatch(
    command: SpatialScopeCommand,
    options?: DispatchOptions,
  ): Promise<SpatialScopeResult>;
}

export interface OwnedSpatialScopeModule extends SpatialScopeModule {
  start(): void;
  stop(): void;
}

export type SpatialScopeHandle = SpatialScopeSnapshot & {
  enter(target: ScopeKey, cause: EnterCause): Promise<SpatialScopeResult>;
  ascend(cause: "breadcrumb" | "keyboard"): Promise<SpatialScopeResult>;
  prefetch(target: ScopeKey): Promise<SpatialScopeResult>;
};

export interface LongitudeSpan {
  readonly west: number;
  readonly east: number;
}

export type GeoExtent =
  | { readonly kind: "world" }
  | {
      readonly kind: "segments";
      readonly south: number;
      readonly north: number;
      readonly longitude:
        | readonly [LongitudeSpan]
        | readonly [LongitudeSpan, LongitudeSpan];
    };

export interface BaseAssetDescriptor {
  readonly assetId: string;
  readonly mediaType: string;
  readonly byteLength: number;
  readonly vertexCount: number;
  readonly featureCount?: number;
}

export interface RenderAssetDescriptor extends BaseAssetDescriptor {
  readonly role: "render";
  readonly lod: "overview" | "regional" | "local";
}

export interface ContainmentAssetDescriptor extends BaseAssetDescriptor {
  readonly role: "containment";
  readonly maxErrorMeters: number;
}

export type AssetDescriptor = RenderAssetDescriptor | ContainmentAssetDescriptor;
export type GeometryLod = RenderAssetDescriptor["lod"];
export type AssetLodSet = Readonly<
  Partial<Record<GeometryLod, RenderAssetDescriptor>>
>;

export interface ResolvedPresentationInput {
  readonly mode: "boundary";
  readonly scopeKey: ScopeKey;
  readonly catalogRevision: CatalogRevision;
  readonly preferredLod: GeometryLod;
  readonly outlineLods: AssetLodSet;
  readonly childrenLods: AssetLodSet;
  readonly cameraExtent: GeoExtent;
}

export type ResolvedPresentation =
  | ResolvedPresentationInput
  | {
      readonly mode: "semantic-only";
      readonly scopeKey: ScopeKey;
      readonly catalogRevision: CatalogRevision;
      readonly problem: ScopeProblem;
    };

export interface ResolvedScope {
  readonly scope: ScopeSummary;
  readonly path: ScopePath;
  readonly query: SpatialQueryRef;
  readonly presentation: ResolvedPresentation;
  readonly containment: ContainmentAssetDescriptor | null;
}

export interface SpatialCatalogPort {
  resolve(
    scopeKey: ScopeKey,
    catalogRevision: string | null,
    signal: AbortSignal,
  ): Promise<ResolvedScope>;
  prefetch(
    scopeKey: ScopeKey,
    catalogRevision: string,
    priority: "hover" | "anticipated",
    signal: AbortSignal,
  ): Promise<void>;
  dispose(): void;
}

export interface ScopeNavigationWrite {
  readonly scopeKey: ScopeKey | null;
  readonly catalogRevision: string;
  readonly mode: "push" | "replace";
  readonly navigationId: string;
}

export interface ScopeLocationEvent {
  readonly scopeCandidate: string | null;
  readonly catalogRevisionCandidate: string | null;
  readonly navigationId: string | null;
}

export interface ScopeNavigationPort {
  readScopeCandidate(): string | null;
  writeScope(write: ScopeNavigationWrite): Promise<void>;
  subscribeLocation(listener: (event: ScopeLocationEvent) => void): () => void;
}

export class SpatialScopeContractError extends Error {
  readonly code: "INVALID_SCOPE_KEY" | "CATALOG_REVISION_UNAVAILABLE" | "INVALID_LINEAGE";
  readonly target: string | null;

  constructor(
    code: SpatialScopeContractError["code"],
    target: string | null,
    detail?: string,
  ) {
    super(detail === undefined ? `${code}: ${String(target)}` : `${code}: ${detail}`);
    this.name = "SpatialScopeContractError";
    this.code = code;
    this.target = target;
  }
}

const LEXICAL_SCOPE_KEY = /^[A-Za-z0-9:._-]+$/;
const ISO3_CANDIDATE = /^country:([A-Za-z]{3})$/;
const ISO3166_2_CANDIDATE =
  /^admin1:iso3166-2:([A-Za-z]{2})-([A-Za-z0-9]{1,3})$/;
const CATALOG_REVISION = /^spatial-v[0-9]+-[a-f0-9]{12,64}$/;

function invalidScopeKey(candidate: unknown): never {
  throw new SpatialScopeContractError(
    "INVALID_SCOPE_KEY",
    typeof candidate === "string" ? candidate : null,
    JSON.stringify(candidate),
  );
}

export function parseScopeKeyCandidate(candidate: unknown): ScopeKey {
  if (
    typeof candidate !== "string" ||
    candidate.length === 0 ||
    new TextEncoder().encode(candidate).byteLength > 128 ||
    !LEXICAL_SCOPE_KEY.test(candidate)
  ) {
    return invalidScopeKey(candidate);
  }

  const iso3 = ISO3_CANDIDATE.exec(candidate);
  const iso3166 = ISO3166_2_CANDIDATE.exec(candidate);
  const canonical = iso3
    ? `country:${iso3[1]?.toUpperCase()}`
    : iso3166
      ? `admin1:iso3166-2:${iso3166[1]?.toUpperCase()}-${iso3166[2]?.toUpperCase()}`
      : candidate;

  const valid =
    canonical === "world" ||
    (/^country:[A-Z]{3}$/.test(canonical) && canonical !== "country:XKX") ||
    /^country:m49:[0-9]{3}$/.test(canonical) ||
    /^country:odin:[a-z0-9][a-z0-9._-]{0,79}$/.test(canonical) ||
    /^admin1:iso3166-2:[A-Z]{2}-[A-Z0-9]{1,3}$/.test(canonical) ||
    /^admin1:gbopen:[A-Za-z0-9._-]{1,80}$/.test(canonical) ||
    /^admin2:[A-Za-z0-9._-]{1,24}:[A-Za-z0-9._-]{1,80}$/.test(canonical);

  if (!valid) return invalidScopeKey(candidate);
  return canonical as ScopeKey;
}

export function scopeKindForKey(scopeKey: ScopeKey): ScopeKind {
  if (scopeKey === "world") return "world";
  if (scopeKey.startsWith("country:")) return "country";
  if (scopeKey.startsWith("admin1:")) return "admin1";
  return "admin2";
}

export function parseCatalogRevision(candidate: unknown): CatalogRevision {
  if (
    typeof candidate !== "string" ||
    candidate.length < 23 ||
    candidate.length > 79 ||
    !CATALOG_REVISION.test(candidate)
  ) {
    throw new SpatialScopeContractError(
      "CATALOG_REVISION_UNAVAILABLE",
      typeof candidate === "string" ? candidate : null,
      JSON.stringify(candidate),
    );
  }
  return candidate as CatalogRevision;
}

export function freezeSpatialValue<T>(value: T): T {
  if (value === null || typeof value !== "object" || Object.isFrozen(value)) {
    return value;
  }
  for (const child of Object.values(value)) freezeSpatialValue(child);
  return Object.freeze(value);
}

export function freezeSpatialScopeSnapshot<T extends SpatialScopeSnapshot>(snapshot: T): T {
  return freezeSpatialValue(snapshot);
}

export const WORLD_SCOPE_KEY = parseScopeKeyCandidate("world");

export const HYDRATING_SPATIAL_SCOPE_SNAPSHOT = freezeSpatialScopeSnapshot({
  phase: "hydrating",
  stateRevision: 0,
  current: null,
  path: [],
  query: null,
  pending: null,
  problem: null,
  visual: { phase: "none", stateRevision: null },
} satisfies SpatialScopeSnapshot);
