// Internal catalog implementation; consumers use ../catalog.ts.
import {
  type ScopeProblem,
  type CatalogRevision,
  type SpatialQueryRef,
  type ScopeKey,
  parseScopeKeyCandidate,
  type AssetDescriptor,
  type GeometryLod,
  type ScopeSummary,
  type ScopePath,
  type AssetLodSet,
  type ContainmentAssetDescriptor,
  type ResolvedScope,
} from "../contracts";
import {
  type BoundaryAssetStore,
} from "./assets";

type JsonRecord = Record<string, unknown>;

export const PROBLEM_CODES = new Set<ScopeProblem["code"]>([
  "INVALID_SCOPE_KEY",
  "UNKNOWN_SCOPE",
  "CATALOG_UNAVAILABLE",
  "CATALOG_REVISION_UNAVAILABLE",
  "INVALID_LINEAGE",
  "GEOMETRY_UNAVAILABLE",
  "ASSET_LIMIT_EXCEEDED",
  "ASSET_BUSY",
  "PRESENTATION_FAILED",
  "URL_SYNC_FAILED",
]);

export const LODS = ["overview", "regional", "local"] as const;

export const ASSET_ID = /^[a-f0-9]{64}$/;

export const POLICY_IDENTIFIER = /^[A-Za-z0-9._-]+$/;

export interface SpatialCatalogErrorInit {
  readonly code: ScopeProblem["code"];
  readonly target?: string | null;
  readonly recoverable?: boolean;
  readonly message: string;
  readonly activeCatalogRevision?: CatalogRevision | null;
  readonly cause?: unknown;
}

export class SpatialCatalogError extends Error {
  readonly code: ScopeProblem["code"];
  readonly target: string | null;
  readonly recoverable: boolean;
  readonly activeCatalogRevision: CatalogRevision | null;

  constructor(init: SpatialCatalogErrorInit) {
    super(init.message, { cause: init.cause });
    this.name = "SpatialCatalogError";
    this.code = init.code;
    this.target = init.target ?? null;
    this.recoverable = init.recoverable ?? false;
    this.activeCatalogRevision = init.activeCatalogRevision ?? null;
  }
}

export interface SpatialBoundaryAttributionSource {
  readonly sourceId: string;
  readonly release: string;
  readonly licenseId: string;
  readonly text: string;
}

export interface SpatialBoundaryProvenance {
  readonly boundaryPolicy: string;
  readonly catalogRevision: CatalogRevision;
  readonly representationNote: string;
  readonly sources: readonly SpatialBoundaryAttributionSource[];
}

export interface SpatialBoundaryProvenanceLoader {
  loadBoundaryProvenance(
    query: Pick<SpatialQueryRef, "catalogRevision" | "boundaryPolicy">,
    signal: AbortSignal,
  ): Promise<SpatialBoundaryProvenance>;
}

export function contractError(message: string, target: string | null = null): never {
  throw new SpatialCatalogError({
    code: "CATALOG_UNAVAILABLE",
    target,
    message,
    recoverable: false,
  });
}

export function lineageError(message: string, target: string | null = null): never {
  throw new SpatialCatalogError({
    code: "INVALID_LINEAGE",
    target,
    message: `INVALID_LINEAGE: ${message}`,
    recoverable: false,
  });
}

export function asRecord(value: unknown, context: string): JsonRecord {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    return contractError(`${context} must be an object`);
  }
  return value as JsonRecord;
}

export function assertExactKeys(
  record: JsonRecord,
  context: string,
  required: readonly string[],
  optional: readonly string[] = [],
): void {
  const allowed = new Set([...required, ...optional]);
  for (const key of Object.keys(record)) {
    if (!allowed.has(key)) contractError(`${context} has unexpected field: ${key}`);
  }
  for (const key of required) {
    if (!Object.hasOwn(record, key)) contractError(`${context} is missing field: ${key}`);
  }
}

export function parseString(value: unknown, context: string, maxLength: number): string {
  if (typeof value !== "string" || value.length === 0 || value.length > maxLength) {
    return contractError(`${context} must be a non-empty string of at most ${maxLength} characters`);
  }
  return value;
}

export function parsePositiveInteger(value: unknown, context: string): number {
  if (!Number.isSafeInteger(value) || (value as number) <= 0) {
    return contractError(`${context} must be a positive integer`);
  }
  return value as number;
}

export function parseFiniteNumber(value: unknown, context: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return contractError(`${context} must be finite`);
  }
  return value;
}

export function parseCanonicalScopeKey(value: unknown, context: string): ScopeKey {
  let parsed: ScopeKey;
  try {
    parsed = parseScopeKeyCandidate(value);
  } catch (error: unknown) {
    throw new SpatialCatalogError({
      code: "INVALID_LINEAGE",
      target: typeof value === "string" ? value : null,
      message: `INVALID_LINEAGE: ${context} is not a valid scope key`,
      cause: error,
    });
  }
  if (parsed !== value) lineageError(`${context} must already be canonical`, String(value));
  return parsed;
}

export interface DeferredGate {
  readonly promise: Promise<void>;
  resolve(): void;
  reject(error?: unknown): void;
}

export function abortError(): DOMException {
  return new DOMException("The operation was aborted.", "AbortError");
}

export interface MemorySpatialCatalogOptions {
  readonly activeCatalogRevision: string;
  readonly resolvedScopes: readonly unknown[];
}

export interface MemoryResolveCall {
  readonly scopeKey: ScopeKey;
  readonly catalogRevision: CatalogRevision;
}

export interface MemoryPrefetchCall extends MemoryResolveCall {
  readonly priority: "hover" | "anticipated";
}

export type Position2D = readonly [longitude: number, latitude: number];

export type LinearRing = readonly Position2D[];

export type PolygonCoordinates = readonly LinearRing[];

export interface BoundaryGeometryV1 {
  readonly schemaVersion: 1;
  readonly geometryType: "MultiPolygon";
  readonly polygons: readonly PolygonCoordinates[];
}

export type BoundaryPackFeatureV1 =
  | {
      readonly kind: "scope";
      readonly scopeKey: ScopeKey;
      readonly label: string;
      readonly geometry: BoundaryGeometryV1;
    }
  | {
      readonly kind: "context";
      readonly featureId: string;
      readonly label: string;
      readonly nonScopeReason: "disputed-territory-context";
      readonly geometry: BoundaryGeometryV1;
    };

export interface BoundaryPackV1 {
  readonly schemaVersion: 1;
  readonly parentScopeKey: ScopeKey;
  readonly features: readonly BoundaryPackFeatureV1[];
}

export type BoundaryAsset = BoundaryGeometryV1 | BoundaryPackV1;

export interface BoundaryAssetLease {
  readonly asset: BoundaryAsset;
  release(): void;
}

export interface SpatialCatalogClock {
  now(): number;
  sleep(milliseconds: number, signal: AbortSignal): Promise<void>;
}

export type SpatialFetch = typeof fetch;

export type AssetHasher = (bytes: Uint8Array) => Promise<string>;

export interface BoundaryAssetStoreOptions {
  readonly fetch?: SpatialFetch;
  readonly clock?: SpatialCatalogClock;
  readonly sha256?: AssetHasher;
  readonly random?: () => number;
  readonly maxEntries?: number;
  readonly maxDecodedBytes?: number;
}

export interface BoundaryAssetStoreDiagnostics {
  readonly activeLeases: number;
  readonly cacheHits: number;
  readonly cacheMisses: number;
  readonly decodedBytes: number;
  readonly decodedEntries: number;
  readonly disposed: boolean;
  readonly evictions: number;
  readonly highWaterDecodedBytes: number;
  readonly highWaterDecodedEntries: number;
  readonly inflightLoads: number;
  readonly maxDecodedBytes: number;
  readonly maxEntries: number;
  readonly prefetchedEntries: number;
}

export interface DecodedAsset {
  readonly asset: BoundaryAsset;
  readonly estimatedHeapBytes: number;
}

export interface AssetCacheEntry extends DecodedAsset {
  readonly descriptor: AssetDescriptor;
  leases: number;
  lastUsed: number;
  prefetched: boolean;
}

export interface InflightAsset {
  readonly descriptor: AssetDescriptor;
  readonly controller: AbortController;
  readonly retryPolicy: AssetRetryPolicy;
  readonly promise: Promise<DecodedAsset>;
  consumers: number;
  settled: boolean;
}

export interface AssetRetryPolicy {
  network: boolean;
  busy: boolean;
  foreground: boolean;
}

export interface GeometryCounts {
  featureCount: number;
  polygonCount: number;
  ringCount: number;
  vertexCount: number;
  maxRingVertices: number;
}

export const MAX_ASSET_WIRE_BYTES = 4 * 1024 * 1024;

export const MAX_ASSET_HEAP_BYTES = 16 * 1024 * 1024;

export const MAX_ASSET_FEATURES = 256;

export const MAX_ASSET_RINGS = 2_048;

export const MAX_RING_VERTICES = 16_384;

export const MAX_SCOPE_METADATA_BYTES = 512 * 1024;

export const MAX_CATALOG_METADATA_BYTES = 64 * 1024;

export const LOD_VERTEX_BUDGET: Readonly<Record<GeometryLod, number>> = {
  overview: 12_000,
  regional: 50_000,
  local: 120_000,
};

export const DEFAULT_DECODED_CACHE_BYTES = 64 * 1024 * 1024;

export const DEFAULT_DECODED_CACHE_ENTRIES = 8;

export const browserClock: SpatialCatalogClock = {
  now: () => Date.now(),
  sleep: (milliseconds, signal) => {
    if (signal.aborted) return Promise.reject(abortError());
    return new Promise<void>((resolve, reject) => {
      let settled = false;
      const finish = (callback: () => void) => {
        if (settled) return;
        settled = true;
        signal.removeEventListener("abort", onAbort);
        callback();
      };
      const timer = globalThis.setTimeout(() => finish(resolve), milliseconds);
      const onAbort = () => {
        globalThis.clearTimeout(timer);
        finish(() => reject(abortError()));
      };
      signal.addEventListener("abort", onAbort, { once: true });
      Promise.resolve().then(() => {
        if (signal.aborted) onAbort();
      });
    });
  },
};

export function defaultFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  return globalThis.fetch(input, init);
}

export function assetLimitError(message: string, target: string | null): SpatialCatalogError {
  return new SpatialCatalogError({
    code: "ASSET_LIMIT_EXCEEDED",
    target,
    message,
    recoverable: false,
  });
}

export function geometryError(message: string, target: string | null): SpatialCatalogError {
  return new SpatialCatalogError({
    code: "GEOMETRY_UNAVAILABLE",
    target,
    message,
    recoverable: true,
  });
}

export function waitForPromise<T>(promise: Promise<T>, signal: AbortSignal): Promise<T> {
  if (signal.aborted) return Promise.reject(abortError());
  return new Promise<T>((resolve, reject) => {
    const onAbort = () => reject(abortError());
    signal.addEventListener("abort", onAbort, { once: true });
    promise.then(resolve, reject).finally(() => signal.removeEventListener("abort", onAbort));
  });
}

export function isAbortFailure(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

export function parseRetryAfter(value: string | null): number {
  if (value === null) return 1_000;
  const seconds = Number(value);
  if (!Number.isFinite(seconds) || seconds < 0 || seconds > 5) return 1_000;
  return seconds * 1_000;
}

export interface DecodedScopeJson {
  readonly byteLength: number;
  readonly value: unknown;
}

export interface HttpSpatialCatalogOptions {
  readonly fetch?: SpatialFetch;
  readonly assetStore?: BoundaryAssetStore;
  readonly clock?: SpatialCatalogClock;
  readonly maxScopeBytes?: number;
  readonly maxScopeEntries?: number;
  readonly random?: () => number;
}

export interface HttpSpatialCatalogDiagnostics {
  readonly disposed: boolean;
  readonly inflightMetadataLoads: number;
  readonly maxScopeBytes: number;
  readonly maxScopeEntries: number;
  readonly metadataBytes: number;
  readonly metadataEntries: number;
  readonly metadataEvictions: number;
  readonly metadataHighWaterBytes: number;
  readonly metadataHighWater: number;
  readonly metadataHits: number;
  readonly metadataMisses: number;
  readonly metadataRevalidations: number;
  readonly negativeEntries: number;
}

export interface DecodedScopeBundle {
  readonly catalogRevision: CatalogRevision;
  readonly boundaryPolicy: string;
  readonly canonicalizedFrom: string | null;
  readonly scope: ScopeSummary;
  readonly path: ScopePath;
  readonly children: readonly ScopeSummary[];
  readonly preferredLod: GeometryLod | null;
  readonly outlineLods: AssetLodSet;
  readonly childrenLods: AssetLodSet;
  readonly containment: ContainmentAssetDescriptor | null;
}

export interface ScopeCacheEntry {
  readonly byteLength: number;
  readonly etag: string;
  readonly resolved: ResolvedScope;
  readonly extentAssetId: string | null;
  readonly prefetchDescriptors: readonly AssetDescriptor[];
  lastUsed: number;
  validatedAt: number;
}

export interface NegativeScopeEntry {
  readonly expiresAt: number;
  readonly error: SpatialCatalogError;
  lastUsed: number;
}

export interface ScopeLoadPolicy {
  allowRetry: boolean;
  readonly asset: AssetRetryPolicy;
}

export interface InflightScopeLoad {
  readonly controller: AbortController;
  readonly policy: ScopeLoadPolicy;
  readonly promise: Promise<ResolvedScope>;
  consumers: number;
  settled: boolean;
}

export const DEFAULT_SCOPE_CACHE_ENTRIES = 256;

export const DEFAULT_SCOPE_CACHE_BYTES = DEFAULT_SCOPE_CACHE_ENTRIES * MAX_SCOPE_METADATA_BYTES;

export const SCOPE_METADATA_FRESH_MILLISECONDS = 60_000;
