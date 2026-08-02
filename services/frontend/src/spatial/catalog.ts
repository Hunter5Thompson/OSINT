import {
  freezeSpatialValue,
  parseCatalogRevision,
  parseScopeKeyCandidate,
  scopeKindForKey,
  type AssetDescriptor,
  type AssetLodSet,
  type CatalogRevision,
  type ContainmentAssetDescriptor,
  type GeoExtent,
  type GeometryLod,
  type RenderAssetDescriptor,
  type ResolvedPresentation,
  type ResolvedScope,
  type ScopeKey,
  type ScopePath,
  type ScopeProblem,
  type ScopeSummary,
  type SpatialCatalogPort,
} from "./contracts";

type JsonRecord = Record<string, unknown>;

const PROBLEM_CODES = new Set<ScopeProblem["code"]>([
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

const LODS = ["overview", "regional", "local"] as const;
const ASSET_ID = /^[a-f0-9]{64}$/;
const POLICY_IDENTIFIER = /^[A-Za-z0-9._-]+$/;

export interface SpatialCatalogErrorInit {
  readonly code: ScopeProblem["code"];
  readonly target?: string | null;
  readonly recoverable?: boolean;
  readonly message: string;
  readonly activeCatalogRevision?: string | null;
  readonly cause?: unknown;
}

export class SpatialCatalogError extends Error {
  readonly code: ScopeProblem["code"];
  readonly target: string | null;
  readonly recoverable: boolean;
  readonly activeCatalogRevision: string | null;

  constructor(init: SpatialCatalogErrorInit) {
    super(init.message, { cause: init.cause });
    this.name = "SpatialCatalogError";
    this.code = init.code;
    this.target = init.target ?? null;
    this.recoverable = init.recoverable ?? false;
    this.activeCatalogRevision = init.activeCatalogRevision ?? null;
  }
}

function contractError(message: string, target: string | null = null): never {
  throw new SpatialCatalogError({
    code: "CATALOG_UNAVAILABLE",
    target,
    message,
    recoverable: false,
  });
}

function lineageError(message: string, target: string | null = null): never {
  throw new SpatialCatalogError({
    code: "INVALID_LINEAGE",
    target,
    message: `INVALID_LINEAGE: ${message}`,
    recoverable: false,
  });
}

function asRecord(value: unknown, context: string): JsonRecord {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    return contractError(`${context} must be an object`);
  }
  return value as JsonRecord;
}

function assertExactKeys(
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

function parseString(value: unknown, context: string, maxLength: number): string {
  if (typeof value !== "string" || value.length === 0 || value.length > maxLength) {
    return contractError(`${context} must be a non-empty string of at most ${maxLength} characters`);
  }
  return value;
}

function parsePositiveInteger(value: unknown, context: string): number {
  if (!Number.isSafeInteger(value) || (value as number) <= 0) {
    return contractError(`${context} must be a positive integer`);
  }
  return value as number;
}

function parseFiniteNumber(value: unknown, context: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return contractError(`${context} must be finite`);
  }
  return value;
}

function parseCanonicalScopeKey(value: unknown, context: string): ScopeKey {
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

function parseScopeSummary(value: unknown, context: string): ScopeSummary {
  const record = asRecord(value, context);
  assertExactKeys(record, context, [
    "key",
    "kind",
    "label",
    "shortLabel",
    "parentKey",
    "childrenAvailable",
    "presentation",
  ]);

  const key = parseCanonicalScopeKey(record.key, `${context}.key`);
  const kind = record.kind;
  if (kind !== "world" && kind !== "country" && kind !== "admin1" && kind !== "admin2") {
    contractError(`${context}.kind is invalid`, key);
  }
  if (kind !== scopeKindForKey(key)) lineageError(`${context}.kind does not match its key`, key);
  const parentKey = record.parentKey === null
    ? null
    : parseCanonicalScopeKey(record.parentKey, `${context}.parentKey`);
  const expectedParentKind = {
    world: null,
    country: "world",
    admin1: "country",
    admin2: "admin1",
  } as const;
  const parentKind = parentKey === null ? null : scopeKindForKey(parentKey);
  if (parentKind !== expectedParentKind[kind]) {
    lineageError(`${context} has an invalid parent kind`, key);
  }
  if (typeof record.childrenAvailable !== "boolean") {
    contractError(`${context}.childrenAvailable must be boolean`, key);
  }
  if (record.presentation !== "boundary" && record.presentation !== "semantic-only") {
    contractError(`${context}.presentation is invalid`, key);
  }

  return {
    key,
    kind,
    label: parseString(record.label, `${context}.label`, 120),
    shortLabel: parseString(record.shortLabel, `${context}.shortLabel`, 120),
    parentKey,
    childrenAvailable: record.childrenAvailable,
    presentation: record.presentation,
  };
}

function parseScopePath(value: unknown, current: ScopeSummary): ScopePath {
  if (!Array.isArray(value) || value.length < 1 || value.length > 4) {
    return lineageError("path must contain one to four summaries", current.key);
  }
  const path = value.map((item, index) => parseScopeSummary(item, `path[${index}]`));
  if (path[0]?.key !== "world") lineageError("path must start at world", current.key);
  if (path.at(-1)?.key !== current.key) lineageError("path must end at current", current.key);
  if (new Set(path.map((item) => item.key)).size !== path.length) {
    lineageError("path contains a cycle", current.key);
  }
  for (let index = 1; index < path.length; index += 1) {
    if (path[index]?.parentKey !== path[index - 1]?.key) {
      lineageError("path is not contiguous", current.key);
    }
  }
  const expectedLength = { world: 1, country: 2, admin1: 3, admin2: 4 }[current.kind];
  if (path.length !== expectedLength) lineageError("path is incomplete", current.key);
  return path as unknown as ScopePath;
}

export function parseScopeProblem(value: unknown): ScopeProblem {
  const record = asRecord(value, "problem");
  assertExactKeys(record, "problem", [
    "severity",
    "code",
    "target",
    "recoverable",
    "message",
  ]);
  if (record.severity !== "warning" && record.severity !== "error") {
    contractError("problem.severity is invalid");
  }
  if (typeof record.code !== "string" || !PROBLEM_CODES.has(record.code as ScopeProblem["code"])) {
    contractError("problem.code is invalid");
  }
  if (record.target !== null && typeof record.target !== "string") {
    contractError("problem.target must be a string or null");
  }
  if (typeof record.recoverable !== "boolean") {
    contractError("problem.recoverable must be boolean");
  }
  return freezeSpatialValue({
    severity: record.severity,
    code: record.code as ScopeProblem["code"],
    target: record.target,
    recoverable: record.recoverable,
    message: parseString(record.message, "problem.message", 500),
  });
}

function parseRenderAsset(value: unknown, context: string, expectedLod: GeometryLod): RenderAssetDescriptor {
  const record = asRecord(value, context);
  assertExactKeys(
    record,
    context,
    ["assetId", "mediaType", "byteLength", "vertexCount", "role", "lod"],
    ["featureCount"],
  );
  if (typeof record.assetId !== "string" || !ASSET_ID.test(record.assetId)) {
    contractError(`${context}.assetId is invalid`);
  }
  if (
    record.mediaType !== "application/vnd.odin.boundary+json;v=1" &&
    record.mediaType !== "application/vnd.odin.boundary-pack+json;v=1"
  ) {
    contractError(`${context}.mediaType is invalid`);
  }
  if (record.role !== "render" || record.lod !== expectedLod) {
    contractError(`${context} role/LOD does not match its map key`);
  }
  const featureCount = record.featureCount === undefined
    ? undefined
    : parsePositiveInteger(record.featureCount, `${context}.featureCount`);
  const isPack = record.mediaType === "application/vnd.odin.boundary-pack+json;v=1";
  if (isPack !== (featureCount !== undefined)) {
    contractError(`${context}.featureCount does not match its media type`);
  }
  return {
    assetId: record.assetId,
    mediaType: record.mediaType,
    byteLength: parsePositiveInteger(record.byteLength, `${context}.byteLength`),
    vertexCount: parsePositiveInteger(record.vertexCount, `${context}.vertexCount`),
    ...(featureCount === undefined ? {} : { featureCount }),
    role: "render",
    lod: expectedLod,
  };
}

function parseLodSet(value: unknown, context: string): AssetLodSet {
  const record = asRecord(value, context);
  assertExactKeys(record, context, [], LODS);
  const result: Partial<Record<GeometryLod, RenderAssetDescriptor>> = {};
  for (const lod of LODS) {
    if (record[lod] !== undefined) result[lod] = parseRenderAsset(record[lod], `${context}.${lod}`, lod);
  }
  return result;
}

function parseContainment(value: unknown): ContainmentAssetDescriptor | null {
  if (value === null) return null;
  const record = asRecord(value, "containment");
  assertExactKeys(record, "containment", [
    "assetId",
    "mediaType",
    "byteLength",
    "vertexCount",
    "role",
    "maxErrorMeters",
  ]);
  if (typeof record.assetId !== "string" || !ASSET_ID.test(record.assetId)) {
    contractError("containment.assetId is invalid");
  }
  if (record.mediaType !== "application/vnd.odin.boundary+json;v=1") {
    contractError("containment.mediaType is invalid");
  }
  if (record.role !== "containment") contractError("containment.role is invalid");
  const maxErrorMeters = parseFiniteNumber(record.maxErrorMeters, "containment.maxErrorMeters");
  if (maxErrorMeters < 0 || maxErrorMeters > 50) {
    contractError("containment.maxErrorMeters is outside the contract budget");
  }
  return {
    assetId: record.assetId,
    mediaType: record.mediaType,
    byteLength: parsePositiveInteger(record.byteLength, "containment.byteLength"),
    vertexCount: parsePositiveInteger(record.vertexCount, "containment.vertexCount"),
    role: "containment",
    maxErrorMeters,
  };
}

function parseGeoExtent(value: unknown): GeoExtent {
  const record = asRecord(value, "cameraExtent");
  if (record.kind === "world") {
    assertExactKeys(record, "cameraExtent", ["kind"]);
    return { kind: "world" };
  }
  assertExactKeys(record, "cameraExtent", ["kind", "south", "north", "longitude"]);
  if (record.kind !== "segments") contractError("cameraExtent.kind is invalid");
  const south = parseFiniteNumber(record.south, "cameraExtent.south");
  const north = parseFiniteNumber(record.north, "cameraExtent.north");
  if (south < -90 || north > 90 || south > north) contractError("cameraExtent latitude is invalid");
  if (!Array.isArray(record.longitude) || record.longitude.length < 1 || record.longitude.length > 2) {
    contractError("cameraExtent.longitude must contain one or two spans");
  }
  const longitude = record.longitude.map((item, index) => {
    const span = asRecord(item, `cameraExtent.longitude[${index}]`);
    assertExactKeys(span, `cameraExtent.longitude[${index}]`, ["west", "east"]);
    const west = parseFiniteNumber(span.west, `cameraExtent.longitude[${index}].west`);
    const east = parseFiniteNumber(span.east, `cameraExtent.longitude[${index}].east`);
    if (west < -180 || east > 180 || west > east) contractError("cameraExtent longitude span is invalid");
    return { west, east };
  });
  return {
    kind: "segments",
    south,
    north,
    longitude: longitude as [{ west: number; east: number }],
  };
}

function parsePresentation(
  value: unknown,
  scopeKey: ScopeKey,
  catalogRevision: CatalogRevision,
): ResolvedPresentation {
  const record = asRecord(value, "presentation");
  if (record.mode === "semantic-only") {
    assertExactKeys(record, "presentation", ["mode", "scopeKey", "catalogRevision", "problem"]);
    const result: ResolvedPresentation = {
      mode: "semantic-only",
      scopeKey: parseCanonicalScopeKey(record.scopeKey, "presentation.scopeKey"),
      catalogRevision: parseCatalogRevision(record.catalogRevision),
      problem: parseScopeProblem(record.problem),
    };
    if (result.scopeKey !== scopeKey || result.catalogRevision !== catalogRevision) {
      lineageError("presentation identity does not match query", scopeKey);
    }
    return result;
  }
  assertExactKeys(record, "presentation", [
    "mode",
    "scopeKey",
    "catalogRevision",
    "preferredLod",
    "outlineLods",
    "childrenLods",
    "cameraExtent",
  ]);
  if (record.mode !== "boundary" || !LODS.includes(record.preferredLod as GeometryLod)) {
    contractError("presentation boundary mode or preferredLod is invalid", scopeKey);
  }
  const preferredLod = record.preferredLod as GeometryLod;
  const outlineLods = parseLodSet(record.outlineLods, "presentation.outlineLods");
  const childrenLods = parseLodSet(record.childrenLods, "presentation.childrenLods");
  if (outlineLods[preferredLod] === undefined && childrenLods[preferredLod] === undefined) {
    contractError("presentation preferredLod is unavailable", scopeKey);
  }
  const result: ResolvedPresentation = {
    mode: "boundary",
    scopeKey: parseCanonicalScopeKey(record.scopeKey, "presentation.scopeKey"),
    catalogRevision: parseCatalogRevision(record.catalogRevision),
    preferredLod,
    outlineLods,
    childrenLods,
    cameraExtent: parseGeoExtent(record.cameraExtent),
  };
  if (result.scopeKey !== scopeKey || result.catalogRevision !== catalogRevision) {
    lineageError("presentation identity does not match query", scopeKey);
  }
  return result;
}

export function parseResolvedScope(value: unknown): ResolvedScope {
  const record = asRecord(value, "resolvedScope");
  assertExactKeys(record, "resolvedScope", ["scope", "path", "query", "presentation", "containment"]);
  const scope = parseScopeSummary(record.scope, "scope");
  const path = parseScopePath(record.path, scope);
  const queryRecord = asRecord(record.query, "query");
  assertExactKeys(queryRecord, "query", [
    "schemaVersion",
    "scopeKey",
    "catalogRevision",
    "boundaryPolicy",
  ]);
  if (queryRecord.schemaVersion !== 1) contractError("query.schemaVersion must be 1", scope.key);
  const queryScopeKey = parseCanonicalScopeKey(queryRecord.scopeKey, "query.scopeKey");
  if (queryScopeKey !== scope.key) lineageError("query scope does not match current", scope.key);
  const catalogRevision = parseCatalogRevision(queryRecord.catalogRevision);
  const boundaryPolicy = parseString(queryRecord.boundaryPolicy, "query.boundaryPolicy", 96);
  if (!POLICY_IDENTIFIER.test(boundaryPolicy)) contractError("query.boundaryPolicy is invalid", scope.key);

  return freezeSpatialValue({
    scope,
    path,
    query: {
      schemaVersion: 1,
      scopeKey: queryScopeKey,
      catalogRevision,
      boundaryPolicy,
    },
    presentation: parsePresentation(record.presentation, scope.key, catalogRevision),
    containment: parseContainment(record.containment),
  });
}

export function mapSpatialCatalogProblem(error: unknown): ScopeProblem {
  const catalogError = error instanceof SpatialCatalogError
    ? error
    : new SpatialCatalogError({
        code: "CATALOG_UNAVAILABLE",
        message: error instanceof Error ? error.message : "Spatial catalog is unavailable.",
        recoverable: true,
        cause: error,
      });
  const warningCodes = new Set<ScopeProblem["code"]>([
    "GEOMETRY_UNAVAILABLE",
    "ASSET_LIMIT_EXCEEDED",
    "ASSET_BUSY",
    "PRESENTATION_FAILED",
  ]);
  return freezeSpatialValue({
    severity: warningCodes.has(catalogError.code) ? "warning" : "error",
    code: catalogError.code,
    target: catalogError.target,
    recoverable: catalogError.recoverable,
    message: catalogError.message,
  });
}

interface DeferredGate {
  readonly promise: Promise<void>;
  resolve(): void;
  reject(error?: unknown): void;
}

function createDeferredGate(): DeferredGate {
  let resolvePromise: () => void = () => undefined;
  let rejectPromise: (error?: unknown) => void = () => undefined;
  const promise = new Promise<void>((resolve, reject) => {
    resolvePromise = resolve;
    rejectPromise = reject;
  });
  return { promise, resolve: resolvePromise, reject: rejectPromise };
}

function abortError(): DOMException {
  return new DOMException("The operation was aborted.", "AbortError");
}

async function waitForGate(gate: DeferredGate | undefined, signal: AbortSignal): Promise<void> {
  if (signal.aborted) throw abortError();
  if (gate === undefined) return;
  await new Promise<void>((resolve, reject) => {
    const onAbort = () => reject(abortError());
    signal.addEventListener("abort", onAbort, { once: true });
    gate.promise.then(resolve, reject).finally(() => signal.removeEventListener("abort", onAbort));
  });
  if (signal.aborted) throw abortError();
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

export class MemorySpatialCatalog implements SpatialCatalogPort {
  private readonly activeCatalogRevision: CatalogRevision;
  private readonly entries = new Map<string, ResolvedScope>();
  private readonly revisions = new Set<CatalogRevision>();
  private readonly resolveGates = new Map<ScopeKey, DeferredGate[]>();
  private readonly resolveCallLog: MemoryResolveCall[] = [];
  private readonly prefetchCallLog: MemoryPrefetchCall[] = [];
  private disposed = false;

  constructor(options: MemorySpatialCatalogOptions) {
    this.activeCatalogRevision = parseCatalogRevision(options.activeCatalogRevision);
    for (const candidate of options.resolvedScopes) {
      const resolved = parseResolvedScope(candidate);
      const mapKey = this.entryKey(resolved.scope.key, resolved.query.catalogRevision);
      if (this.entries.has(mapKey)) contractError(`duplicate memory catalog entry: ${mapKey}`);
      this.entries.set(mapKey, resolved);
      this.revisions.add(resolved.query.catalogRevision);
    }
    if (!this.revisions.has(this.activeCatalogRevision)) {
      contractError("active catalog revision has no resolved scopes", this.activeCatalogRevision);
    }
  }

  get resolveCalls(): readonly MemoryResolveCall[] {
    return this.resolveCallLog;
  }

  get prefetchCalls(): readonly MemoryPrefetchCall[] {
    return this.prefetchCallLog;
  }

  deferNextResolve(scopeKey: ScopeKey): DeferredGate {
    const gate = createDeferredGate();
    const gates = this.resolveGates.get(scopeKey) ?? [];
    gates.push(gate);
    this.resolveGates.set(scopeKey, gates);
    return gate;
  }

  async resolve(
    scopeKey: ScopeKey,
    catalogRevision: string | null,
    signal: AbortSignal,
  ): Promise<ResolvedScope> {
    this.assertAvailable();
    const revision = this.requestedRevision(catalogRevision);
    this.resolveCallLog.push(freezeSpatialValue({ scopeKey, catalogRevision: revision }));
    const gates = this.resolveGates.get(scopeKey);
    const gate = gates?.shift();
    if (gates?.length === 0) this.resolveGates.delete(scopeKey);
    await waitForGate(gate, signal);
    this.assertAvailable();
    const result = this.entries.get(this.entryKey(scopeKey, revision));
    if (result === undefined) {
      throw new SpatialCatalogError({
        code: "UNKNOWN_SCOPE",
        target: scopeKey,
        message: "Scope is not present in the catalog.",
      });
    }
    return result;
  }

  async prefetch(
    scopeKey: ScopeKey,
    catalogRevision: string,
    priority: "hover" | "anticipated",
    signal: AbortSignal,
  ): Promise<void> {
    this.assertAvailable();
    if (signal.aborted) throw abortError();
    const revision = this.requestedRevision(catalogRevision);
    this.prefetchCallLog.push(freezeSpatialValue({ scopeKey, catalogRevision: revision, priority }));
    if (!this.entries.has(this.entryKey(scopeKey, revision))) {
      throw new SpatialCatalogError({
        code: "UNKNOWN_SCOPE",
        target: scopeKey,
        message: "Scope is not present in the catalog.",
      });
    }
    await Promise.resolve();
    if (signal.aborted) throw abortError();
  }

  dispose(): void {
    this.disposed = true;
    for (const gates of this.resolveGates.values()) {
      gates.forEach((gate) => gate.reject(abortError()));
    }
    this.resolveGates.clear();
  }

  private requestedRevision(candidate: string | null): CatalogRevision {
    let revision: CatalogRevision;
    try {
      revision = candidate === null ? this.activeCatalogRevision : parseCatalogRevision(candidate);
    } catch (error: unknown) {
      throw new SpatialCatalogError({
        code: "CATALOG_REVISION_UNAVAILABLE",
        target: candidate,
        message: "Catalog revision is invalid or unavailable.",
        cause: error,
      });
    }
    if (!this.revisions.has(revision)) {
      throw new SpatialCatalogError({
        code: "CATALOG_REVISION_UNAVAILABLE",
        target: revision,
        message: "Catalog revision is invalid or unavailable.",
      });
    }
    return revision;
  }

  private entryKey(scopeKey: ScopeKey, revision: CatalogRevision): string {
    return `${revision}\u0000${scopeKey}`;
  }

  private assertAvailable(): void {
    if (this.disposed) {
      throw new SpatialCatalogError({
        code: "CATALOG_UNAVAILABLE",
        message: "Memory spatial catalog has been disposed.",
      });
    }
  }
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

type SpatialFetch = typeof fetch;
type AssetHasher = (bytes: Uint8Array) => Promise<string>;

export interface BoundaryAssetStoreOptions {
  readonly fetch?: SpatialFetch;
  readonly clock?: SpatialCatalogClock;
  readonly sha256?: AssetHasher;
  readonly random?: () => number;
  readonly maxEntries?: number;
  readonly maxDecodedBytes?: number;
}

interface DecodedAsset {
  readonly asset: BoundaryAsset;
  readonly estimatedHeapBytes: number;
}

interface AssetCacheEntry extends DecodedAsset {
  readonly descriptor: AssetDescriptor;
  leases: number;
  lastUsed: number;
}

interface InflightAsset {
  readonly descriptor: AssetDescriptor;
  readonly controller: AbortController;
  readonly promise: Promise<DecodedAsset>;
  consumers: number;
  settled: boolean;
}

interface AssetRetryPolicy {
  readonly network: boolean;
  readonly busy: boolean;
}

interface GeometryCounts {
  featureCount: number;
  polygonCount: number;
  ringCount: number;
  vertexCount: number;
  maxRingVertices: number;
}

const MAX_ASSET_WIRE_BYTES = 4 * 1024 * 1024;
const MAX_ASSET_HEAP_BYTES = 16 * 1024 * 1024;
const MAX_ASSET_FEATURES = 256;
const MAX_ASSET_RINGS = 2_048;
const MAX_RING_VERTICES = 16_384;
const MAX_SCOPE_METADATA_BYTES = 512 * 1024;
const LOD_VERTEX_BUDGET: Readonly<Record<GeometryLod, number>> = {
  overview: 12_000,
  regional: 50_000,
  local: 120_000,
};
const DEFAULT_DECODED_CACHE_BYTES = 32 * 1024 * 1024;
const DEFAULT_DECODED_CACHE_ENTRIES = 32;

const browserClock: SpatialCatalogClock = {
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

async function defaultSha256(bytes: Uint8Array): Promise<string> {
  if (globalThis.crypto?.subtle === undefined) {
    throw new SpatialCatalogError({
      code: "GEOMETRY_UNAVAILABLE",
      message: "SHA-256 is unavailable in this browser.",
      recoverable: false,
    });
  }
  const copy = new Uint8Array(bytes);
  const digest = await globalThis.crypto.subtle.digest("SHA-256", copy.buffer);
  return [...new Uint8Array(digest)]
    .map((value) => value.toString(16).padStart(2, "0"))
    .join("");
}

function defaultFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  return globalThis.fetch(input, init);
}

function assetLimitError(message: string, target: string | null): SpatialCatalogError {
  return new SpatialCatalogError({
    code: "ASSET_LIMIT_EXCEEDED",
    target,
    message,
    recoverable: false,
  });
}

function geometryError(message: string, target: string | null): SpatialCatalogError {
  return new SpatialCatalogError({
    code: "GEOMETRY_UNAVAILABLE",
    target,
    message,
    recoverable: true,
  });
}

function assertDescriptorMatch(left: AssetDescriptor, right: AssetDescriptor): void {
  if (
    left.assetId !== right.assetId ||
    left.mediaType !== right.mediaType ||
    left.byteLength !== right.byteLength ||
    left.vertexCount !== right.vertexCount ||
    left.featureCount !== right.featureCount ||
    left.role !== right.role ||
    (left.role === "render" && right.role === "render" && left.lod !== right.lod) ||
    (
      left.role === "containment" &&
      right.role === "containment" &&
      left.maxErrorMeters !== right.maxErrorMeters
    )
  ) {
    throw geometryError("Asset descriptor changed for one content address.", left.assetId);
  }
}

function validateDescriptorBudget(descriptor: AssetDescriptor): void {
  if (descriptor.byteLength > MAX_ASSET_WIRE_BYTES) {
    throw assetLimitError("Asset exceeds the wire-byte budget.", descriptor.assetId);
  }
  const vertexBudget = descriptor.role === "render"
    ? LOD_VERTEX_BUDGET[descriptor.lod]
    : LOD_VERTEX_BUDGET.local;
  if (descriptor.vertexCount > vertexBudget) {
    throw assetLimitError("Asset exceeds its vertex budget.", descriptor.assetId);
  }
  if (
    descriptor.featureCount !== undefined &&
    descriptor.featureCount > MAX_ASSET_FEATURES
  ) {
    throw assetLimitError("Asset exceeds the feature budget.", descriptor.assetId);
  }
}

function waitForPromise<T>(promise: Promise<T>, signal: AbortSignal): Promise<T> {
  if (signal.aborted) return Promise.reject(abortError());
  return new Promise<T>((resolve, reject) => {
    const onAbort = () => reject(abortError());
    signal.addEventListener("abort", onAbort, { once: true });
    promise.then(resolve, reject).finally(() => signal.removeEventListener("abort", onAbort));
  });
}

export class BoundaryAssetStore {
  private readonly fetcher: SpatialFetch;
  private readonly clock: SpatialCatalogClock;
  private readonly sha256: AssetHasher;
  private readonly random: () => number;
  private readonly maxEntries: number;
  private readonly maxDecodedBytes: number;
  private readonly cache = new Map<string, AssetCacheEntry>();
  private readonly inflight = new Map<string, InflightAsset>();
  private disposed = false;

  constructor(options: BoundaryAssetStoreOptions = {}) {
    this.fetcher = options.fetch ?? defaultFetch;
    this.clock = options.clock ?? browserClock;
    this.sha256 = options.sha256 ?? defaultSha256;
    this.random = options.random ?? Math.random;
    this.maxEntries = options.maxEntries ?? DEFAULT_DECODED_CACHE_ENTRIES;
    this.maxDecodedBytes = options.maxDecodedBytes ?? DEFAULT_DECODED_CACHE_BYTES;
    if (!Number.isSafeInteger(this.maxEntries) || this.maxEntries < 1 || this.maxEntries > 256) {
      throw new RangeError("maxEntries must be an integer between 1 and 256");
    }
    if (
      !Number.isSafeInteger(this.maxDecodedBytes) ||
      this.maxDecodedBytes < 1 ||
      this.maxDecodedBytes > 256 * 1024 * 1024
    ) {
      throw new RangeError("maxDecodedBytes is outside the supported cache bound");
    }
  }

  async acquire(
    descriptor: AssetDescriptor,
    signal: AbortSignal,
  ): Promise<BoundaryAssetLease> {
    return this.acquireWithPolicy(descriptor, signal, { network: true, busy: true });
  }

  async prefetch(descriptor: AssetDescriptor, signal: AbortSignal): Promise<void> {
    const lease = await this.acquireWithPolicy(
      descriptor,
      signal,
      { network: false, busy: false },
    );
    lease.release();
  }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    for (const load of this.inflight.values()) load.controller.abort();
    this.inflight.clear();
    this.cache.clear();
  }

  private async acquireWithPolicy(
    descriptor: AssetDescriptor,
    signal: AbortSignal,
    policy: AssetRetryPolicy,
  ): Promise<BoundaryAssetLease> {
    this.assertAvailable();
    validateDescriptorBudget(descriptor);
    if (signal.aborted) throw abortError();
    const cached = this.cache.get(descriptor.assetId);
    if (cached !== undefined) {
      assertDescriptorMatch(cached.descriptor, descriptor);
      return this.lease(cached);
    }

    let load = this.inflight.get(descriptor.assetId);
    if (load === undefined) {
      const controller = new AbortController();
      load = {
        descriptor,
        controller,
        promise: this.loadAsset(descriptor, controller.signal, policy),
        consumers: 0,
        settled: false,
      };
      this.inflight.set(descriptor.assetId, load);
      const ownedLoad = load;
      ownedLoad.promise.then(
        (decoded) => this.finishLoad(ownedLoad, decoded),
        () => this.finishLoad(ownedLoad),
      );
    } else {
      assertDescriptorMatch(load.descriptor, descriptor);
    }

    load.consumers += 1;
    try {
      await waitForPromise(load.promise, signal);
      if (signal.aborted) throw abortError();
      const entry = this.cache.get(descriptor.assetId);
      if (entry === undefined) throw geometryError("Decoded asset was not cached.", descriptor.assetId);
      return this.lease(entry);
    } finally {
      load.consumers -= 1;
      if (load.consumers === 0 && !load.settled) load.controller.abort();
    }
  }

  private finishLoad(load: InflightAsset, decoded?: DecodedAsset): void {
    load.settled = true;
    if (this.inflight.get(load.descriptor.assetId) === load) {
      this.inflight.delete(load.descriptor.assetId);
    }
    if (decoded === undefined || this.disposed) return;
    this.cache.set(load.descriptor.assetId, {
      ...decoded,
      descriptor: freezeSpatialValue({ ...load.descriptor }),
      leases: 0,
      lastUsed: this.clock.now(),
    });
  }

  private lease(entry: AssetCacheEntry): BoundaryAssetLease {
    entry.leases += 1;
    entry.lastUsed = this.clock.now();
    this.evict();
    let released = false;
    return freezeSpatialValue({
      asset: entry.asset,
      release: () => {
        if (released) return;
        released = true;
        entry.leases -= 1;
        entry.lastUsed = this.clock.now();
        this.evict();
      },
    });
  }

  private evict(): void {
    let decodedBytes = [...this.cache.values()]
      .reduce((total, entry) => total + entry.estimatedHeapBytes, 0);
    while (this.cache.size > this.maxEntries || decodedBytes > this.maxDecodedBytes) {
      const candidate = [...this.cache.entries()]
        .filter(([, entry]) => entry.leases === 0)
        .sort((left, right) => left[1].lastUsed - right[1].lastUsed)[0];
      if (candidate === undefined) return;
      this.cache.delete(candidate[0]);
      decodedBytes -= candidate[1].estimatedHeapBytes;
    }
  }

  private async loadAsset(
    descriptor: AssetDescriptor,
    signal: AbortSignal,
    policy: AssetRetryPolicy,
  ): Promise<DecodedAsset> {
    const response = await this.fetchAssetResponse(descriptor, signal, policy);
    const bytes = await readBoundedAssetBytes(response, descriptor, signal);
    const digest = await this.sha256(bytes);
    if (signal.aborted) throw abortError();
    if (digest !== descriptor.assetId) {
      throw geometryError("Asset SHA-256 does not match its descriptor.", descriptor.assetId);
    }
    return decodeBoundaryAsset(bytes, descriptor);
  }

  private async fetchAssetResponse(
    descriptor: AssetDescriptor,
    signal: AbortSignal,
    policy: AssetRetryPolicy,
  ): Promise<Response> {
    let networkRetries = 0;
    let busyRetries = 0;
    while (true) {
      if (signal.aborted) throw abortError();
      let response: Response;
      try {
        response = await this.fetcher(`/api/spatial/assets/${descriptor.assetId}`, {
          method: "GET",
          signal,
          headers: { Accept: descriptor.mediaType },
        });
      } catch (error: unknown) {
        if (signal.aborted || isAbortFailure(error)) throw abortError();
        if (!policy.network || networkRetries >= 1) {
          throw geometryError("Spatial asset request failed.", descriptor.assetId);
        }
        networkRetries += 1;
        await this.clock.sleep(this.jitterDelay(), signal);
        continue;
      }
      if (response.status === 429) {
        if (!policy.busy || busyRetries >= 1) throw await errorFromResponse(response);
        busyRetries += 1;
        const delay = parseRetryAfter(response.headers.get("Retry-After"));
        await this.clock.sleep(delay, signal);
        continue;
      }
      if (response.status >= 500 && response.status <= 599 && policy.network && networkRetries < 1) {
        networkRetries += 1;
        await this.clock.sleep(this.jitterDelay(), signal);
        continue;
      }
      if (!response.ok) throw await errorFromResponse(response);
      return response;
    }
  }

  private assertAvailable(): void {
    if (this.disposed) {
      throw new SpatialCatalogError({
        code: "CATALOG_UNAVAILABLE",
        message: "Boundary asset store has been disposed.",
      });
    }
  }

  private jitterDelay(): number {
    return 100 + Math.floor(Math.min(1, Math.max(0, this.random())) * 100);
  }
}

function isAbortFailure(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

function parseRetryAfter(value: string | null): number {
  if (value === null) return 1_000;
  const seconds = Number(value);
  if (!Number.isFinite(seconds) || seconds < 0 || seconds > 5) return 1_000;
  return seconds * 1_000;
}

async function readBoundedAssetBytes(
  response: Response,
  descriptor: AssetDescriptor,
  signal: AbortSignal,
): Promise<Uint8Array> {
  const contentLength = response.headers.get("Content-Length");
  if (
    contentLength === null ||
    !/^[0-9]+$/.test(contentLength) ||
    Number(contentLength) !== descriptor.byteLength
  ) {
    throw geometryError("Asset Content-Length does not match its descriptor.", descriptor.assetId);
  }
  if (descriptor.byteLength > MAX_ASSET_WIRE_BYTES) {
    throw assetLimitError("Asset exceeds the wire-byte budget.", descriptor.assetId);
  }
  if (response.headers.get("Content-Type") !== descriptor.mediaType) {
    throw geometryError("Asset Content-Type does not match its descriptor.", descriptor.assetId);
  }
  const contentEncoding = response.headers.get("Content-Encoding");
  if (contentEncoding !== null && contentEncoding !== "identity") {
    throw geometryError("Compressed spatial assets require a separate descriptor.", descriptor.assetId);
  }
  if (response.headers.get("ETag") !== `"${descriptor.assetId}"`) {
    throw geometryError("Asset ETag does not match its content address.", descriptor.assetId);
  }
  if (response.body === null) {
    throw geometryError("Spatial asset response has no body.", descriptor.assetId);
  }

  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let received = 0;
  const onAbort = () => {
    void reader.cancel(abortError());
  };
  signal.addEventListener("abort", onAbort, { once: true });
  try {
    while (true) {
      if (signal.aborted) throw abortError();
      const result = await reader.read();
      if (result.done) break;
      received += result.value.byteLength;
      if (received > descriptor.byteLength || received > MAX_ASSET_WIRE_BYTES) {
        throw assetLimitError("Spatial asset exceeded its streaming byte cap.", descriptor.assetId);
      }
      chunks.push(result.value);
    }
  } finally {
    signal.removeEventListener("abort", onAbort);
    reader.releaseLock();
  }
  if (signal.aborted) throw abortError();
  if (received !== descriptor.byteLength) {
    throw geometryError("Spatial asset body length does not match its descriptor.", descriptor.assetId);
  }
  const bytes = new Uint8Array(received);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return bytes;
}

function emptyGeometryCounts(featureCount: number): GeometryCounts {
  return {
    featureCount,
    polygonCount: 0,
    ringCount: 0,
    vertexCount: 0,
    maxRingVertices: 0,
  };
}

function parsePosition(value: unknown, context: string): Position2D {
  if (!Array.isArray(value) || value.length !== 2) {
    throw assetLimitError(`${context} must be a longitude/latitude pair.`, null);
  }
  const longitude = parseFiniteNumber(value[0], `${context}[0]`);
  const latitude = parseFiniteNumber(value[1], `${context}[1]`);
  if (longitude < -180 || longitude > 180 || latitude < -90 || latitude > 90) {
    throw assetLimitError(`${context} is outside WGS84 bounds.`, null);
  }
  return [longitude, latitude];
}

function decodeGeometry(
  value: unknown,
  context: string,
  counts: GeometryCounts,
): BoundaryGeometryV1 {
  const record = asRecord(value, context);
  assertExactKeys(record, context, ["schema_version", "geometry_type", "polygons"]);
  if (record.schema_version !== 1 || record.geometry_type !== "MultiPolygon") {
    throw assetLimitError(`${context} has an unsupported geometry schema.`, null);
  }
  if (!Array.isArray(record.polygons) || record.polygons.length === 0) {
    throw assetLimitError(`${context}.polygons must not be empty.`, null);
  }
  const polygons: PolygonCoordinates[] = [];
  for (const [polygonIndex, polygonValue] of record.polygons.entries()) {
    if (!Array.isArray(polygonValue) || polygonValue.length === 0) {
      throw assetLimitError(`${context}.polygons[${polygonIndex}] must contain a ring.`, null);
    }
    counts.polygonCount += 1;
    const polygon: LinearRing[] = [];
    for (const [ringIndex, ringValue] of polygonValue.entries()) {
      if (
        !Array.isArray(ringValue) ||
        ringValue.length < 4 ||
        ringValue.length > MAX_RING_VERTICES
      ) {
        throw assetLimitError(`${context} ring size is outside the contract budget.`, null);
      }
      counts.ringCount += 1;
      counts.vertexCount += ringValue.length;
      counts.maxRingVertices = Math.max(counts.maxRingVertices, ringValue.length);
      if (counts.ringCount > MAX_ASSET_RINGS) {
        throw assetLimitError("Asset exceeds the ring budget.", null);
      }
      const ring = ringValue.map((position, positionIndex) => parsePosition(
        position,
        `${context}.polygons[${polygonIndex}][${ringIndex}][${positionIndex}]`,
      ));
      const first = ring[0];
      const last = ring.at(-1);
      if (
        first === undefined ||
        last === undefined ||
        first[0] !== last[0] ||
        first[1] !== last[1]
      ) {
        throw assetLimitError(`${context} ring is not closed.`, null);
      }
      polygon.push(ring);
    }
    polygons.push(polygon);
  }
  return {
    schemaVersion: 1,
    geometryType: "MultiPolygon",
    polygons,
  };
}

function parseUnicodeLabel(value: unknown, context: string): string {
  const label = parseString(value, context, 240);
  if ([...label].length > 120) {
    throw assetLimitError(`${context} exceeds 120 Unicode code points.`, null);
  }
  return label;
}

function decodeBoundaryAsset(bytes: Uint8Array, descriptor: AssetDescriptor): DecodedAsset {
  let value: unknown;
  try {
    const text = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
    value = JSON.parse(text) as unknown;
  } catch {
    throw geometryError("Spatial asset is not valid UTF-8 JSON.", descriptor.assetId);
  }

  let asset: BoundaryAsset;
  let counts: GeometryCounts;
  if (descriptor.mediaType === "application/vnd.odin.boundary+json;v=1") {
    counts = emptyGeometryCounts(0);
    asset = decodeGeometry(value, "boundary", counts);
    if (descriptor.featureCount !== undefined) {
      throw geometryError("Boundary descriptor must not declare featureCount.", descriptor.assetId);
    }
  } else if (descriptor.mediaType === "application/vnd.odin.boundary-pack+json;v=1") {
    const record = asRecord(value, "boundaryPack");
    assertExactKeys(record, "boundaryPack", ["schema_version", "parent_scope_key", "features"]);
    if (record.schema_version !== 1 || !Array.isArray(record.features)) {
      throw assetLimitError("Boundary pack schema is invalid.", descriptor.assetId);
    }
    if (record.features.length < 1 || record.features.length > MAX_ASSET_FEATURES) {
      throw assetLimitError("Boundary pack feature count is outside the budget.", descriptor.assetId);
    }
    counts = emptyGeometryCounts(record.features.length);
    const identities = new Set<string>();
    const features: BoundaryPackFeatureV1[] = record.features.map((featureValue, index) => {
      const feature = asRecord(featureValue, `boundaryPack.features[${index}]`);
      if (feature.kind === "scope") {
        assertExactKeys(feature, `boundaryPack.features[${index}]`, [
          "kind",
          "scope_key",
          "label",
          "geometry",
        ]);
        const scopeKey = parseCanonicalScopeKey(
          feature.scope_key,
          `boundaryPack.features[${index}].scope_key`,
        );
        const identity = `scope\u0000${scopeKey}`;
        if (identities.has(identity)) throw assetLimitError("Duplicate pack feature.", scopeKey);
        identities.add(identity);
        return {
          kind: "scope",
          scopeKey,
          label: parseUnicodeLabel(feature.label, `boundaryPack.features[${index}].label`),
          geometry: decodeGeometry(
            feature.geometry,
            `boundaryPack.features[${index}].geometry`,
            counts,
          ),
        };
      }
      assertExactKeys(feature, `boundaryPack.features[${index}]`, [
        "kind",
        "feature_id",
        "label",
        "non_scope_reason",
        "geometry",
      ]);
      if (feature.kind !== "context" || feature.non_scope_reason !== "disputed-territory-context") {
        throw assetLimitError("Boundary-pack context feature is invalid.", descriptor.assetId);
      }
      const featureId = parseString(
        feature.feature_id,
        `boundaryPack.features[${index}].feature_id`,
        128,
      );
      const identity = `context\u0000${featureId}`;
      if (identities.has(identity)) throw assetLimitError("Duplicate pack feature.", featureId);
      identities.add(identity);
      return {
        kind: "context",
        featureId,
        label: parseUnicodeLabel(feature.label, `boundaryPack.features[${index}].label`),
        nonScopeReason: "disputed-territory-context",
        geometry: decodeGeometry(
          feature.geometry,
          `boundaryPack.features[${index}].geometry`,
          counts,
        ),
      };
    });
    asset = {
      schemaVersion: 1,
      parentScopeKey: parseCanonicalScopeKey(record.parent_scope_key, "boundaryPack.parent_scope_key"),
      features,
    };
  } else {
    throw geometryError("Asset media type is unsupported.", descriptor.assetId);
  }

  if (counts.vertexCount !== descriptor.vertexCount) {
    throw assetLimitError("Decoded vertex count does not match the descriptor.", descriptor.assetId);
  }
  if (
    descriptor.featureCount !== undefined &&
    counts.featureCount !== descriptor.featureCount
  ) {
    throw assetLimitError("Decoded feature count does not match the descriptor.", descriptor.assetId);
  }
  const estimatedHeapBytes = 1_024
    + counts.featureCount * 256
    + counts.polygonCount * 128
    + counts.ringCount * 64
    + counts.vertexCount * 64;
  if (estimatedHeapBytes > MAX_ASSET_HEAP_BYTES) {
    throw assetLimitError("Decoded asset exceeds the heap budget.", descriptor.assetId);
  }
  return {
    asset: freezeSpatialValue(asset),
    estimatedHeapBytes,
  };
}

async function errorFromResponse(response: Response): Promise<SpatialCatalogError> {
  try {
    const value: unknown = await response.json();
    const envelope = asRecord(value, "spatialProblem");
    assertExactKeys(envelope, "spatialProblem", ["detail"]);
    const detail = asRecord(envelope.detail, "spatialProblem.detail");
    assertExactKeys(detail, "spatialProblem.detail", [
      "schema_version",
      "code",
      "message",
      "target",
      "recoverable",
      "active_catalog_revision",
    ]);
    if (detail.schema_version !== 1 || typeof detail.code !== "string") {
      throw new Error("invalid problem schema");
    }
    const target = detail.target === null
      ? null
      : parseString(detail.target, "spatialProblem.detail.target", 128);
    if (typeof detail.recoverable !== "boolean") throw new Error("invalid recoverable flag");
    const activeCatalogRevision = detail.active_catalog_revision === null
      ? null
      : parseCatalogRevision(detail.active_catalog_revision);
    const mappedCode: ScopeProblem["code"] = (() => {
      switch (detail.code) {
        case "INVALID_SCOPE_KEY": return "INVALID_SCOPE_KEY";
        case "UNKNOWN_SCOPE": return "UNKNOWN_SCOPE";
        case "CATALOG_UNAVAILABLE": return "CATALOG_UNAVAILABLE";
        case "CATALOG_REVISION_UNAVAILABLE":
        case "INVALID_CATALOG_REVISION": return "CATALOG_REVISION_UNAVAILABLE";
        case "ASSET_BUSY": return "ASSET_BUSY";
        case "UNKNOWN_ASSET":
        case "INVALID_ASSET_ID":
        case "ASSET_CORRUPT": return "GEOMETRY_UNAVAILABLE";
        default: return "CATALOG_UNAVAILABLE";
      }
    })();
    const baseMessage = parseString(detail.message, "spatialProblem.detail.message", 200);
    const message = mappedCode === "CATALOG_REVISION_UNAVAILABLE" && activeCatalogRevision !== null
      ? `${baseMessage} Active revision: ${activeCatalogRevision}.`
      : baseMessage;
    return new SpatialCatalogError({
      code: mappedCode,
      target,
      message,
      recoverable: detail.recoverable,
      activeCatalogRevision,
    });
  } catch (error: unknown) {
    const fallbackCode: ScopeProblem["code"] = response.status === 429
      ? "ASSET_BUSY"
      : response.status === 409
        ? "CATALOG_REVISION_UNAVAILABLE"
        : response.status === 404
          ? "UNKNOWN_SCOPE"
          : "CATALOG_UNAVAILABLE";
    return new SpatialCatalogError({
      code: fallbackCode,
      message: `Spatial catalog request failed with HTTP ${response.status}.`,
      recoverable: response.status === 409 || response.status === 429 || response.status >= 500,
      cause: error,
    });
  }
}

async function readScopeJson(response: Response, signal: AbortSignal): Promise<unknown> {
  const declaredLength = response.headers.get("Content-Length");
  if (
    declaredLength !== null &&
    (!/^[0-9]+$/.test(declaredLength) || Number(declaredLength) > MAX_SCOPE_METADATA_BYTES)
  ) {
    throw new SpatialCatalogError({
      code: "CATALOG_UNAVAILABLE",
      message: "Scope metadata exceeds its byte budget.",
      recoverable: false,
    });
  }
  const text = await response.text();
  if (signal.aborted) throw abortError();
  if (new TextEncoder().encode(text).byteLength > MAX_SCOPE_METADATA_BYTES) {
    throw new SpatialCatalogError({
      code: "CATALOG_UNAVAILABLE",
      message: "Scope metadata exceeded its streaming byte budget.",
      recoverable: false,
    });
  }
  try {
    return JSON.parse(text) as unknown;
  } catch (error: unknown) {
    throw new SpatialCatalogError({
      code: "CATALOG_UNAVAILABLE",
      message: "Scope metadata is not valid JSON.",
      recoverable: false,
      cause: error,
    });
  }
}

export interface HttpSpatialCatalogOptions {
  readonly fetch?: SpatialFetch;
  readonly assetStore?: BoundaryAssetStore;
  readonly clock?: SpatialCatalogClock;
  readonly random?: () => number;
}

interface DecodedScopeBundle {
  readonly catalogRevision: CatalogRevision;
  readonly boundaryPolicy: string;
  readonly scope: ScopeSummary;
  readonly path: ScopePath;
  readonly preferredLod: GeometryLod | null;
  readonly outlineLods: AssetLodSet;
  readonly childrenLods: AssetLodSet;
  readonly containment: ContainmentAssetDescriptor | null;
}

interface ScopeCacheEntry {
  readonly etag: string;
  readonly resolved: ResolvedScope;
  readonly descriptors: readonly AssetDescriptor[];
}

interface NegativeScopeEntry {
  readonly expiresAt: number;
  readonly error: SpatialCatalogError;
}

function parseWireScopeSummary(value: unknown, context: string): ScopeSummary {
  const record = asRecord(value, context);
  assertExactKeys(record, context, [
    "key",
    "kind",
    "label",
    "short_label",
    "parent_key",
    "children_available",
    "presentation",
  ]);
  return parseScopeSummary({
    key: record.key,
    kind: record.kind,
    label: record.label,
    shortLabel: record.short_label,
    parentKey: record.parent_key,
    childrenAvailable: record.children_available,
    presentation: record.presentation,
  }, context);
}

function parseWirePath(value: unknown, current: ScopeSummary): ScopePath {
  if (!Array.isArray(value)) return lineageError("wire path must be an array", current.key);
  return parseScopePath(
    value.map((item, index) => {
      const summary = parseWireScopeSummary(item, `path[${index}]`);
      return {
        key: summary.key,
        kind: summary.kind,
        label: summary.label,
        shortLabel: summary.shortLabel,
        parentKey: summary.parentKey,
        childrenAvailable: summary.childrenAvailable,
        presentation: summary.presentation,
      };
    }),
    current,
  );
}

function parseWireRenderDescriptor(
  value: unknown,
  context: string,
  lod: GeometryLod,
): RenderAssetDescriptor {
  const record = asRecord(value, context);
  assertExactKeys(
    record,
    context,
    ["asset_id", "media_type", "byte_length", "vertex_count", "role", "lod"],
    ["feature_count"],
  );
  return parseRenderAsset({
    assetId: record.asset_id,
    mediaType: record.media_type,
    byteLength: record.byte_length,
    vertexCount: record.vertex_count,
    ...(record.feature_count === undefined ? {} : { featureCount: record.feature_count }),
    role: record.role,
    lod: record.lod,
  }, context, lod);
}

function parseWireLodSet(value: unknown, context: string): AssetLodSet {
  const record = asRecord(value, context);
  assertExactKeys(record, context, [], LODS);
  const result: Partial<Record<GeometryLod, RenderAssetDescriptor>> = {};
  for (const lod of LODS) {
    if (record[lod] !== undefined) {
      result[lod] = parseWireRenderDescriptor(record[lod], `${context}.${lod}`, lod);
    }
  }
  return result;
}

function parseWireContainment(value: unknown): ContainmentAssetDescriptor | null {
  if (value === null) return null;
  const record = asRecord(value, "containment");
  assertExactKeys(record, "containment", [
    "asset_id",
    "media_type",
    "byte_length",
    "vertex_count",
    "role",
    "max_error_m",
  ]);
  return parseContainment({
    assetId: record.asset_id,
    mediaType: record.media_type,
    byteLength: record.byte_length,
    vertexCount: record.vertex_count,
    role: record.role,
    maxErrorMeters: record.max_error_m,
  });
}

function decodeScopeBundle(
  value: unknown,
  requestedScope: ScopeKey,
  requestedRevision: CatalogRevision | null,
): DecodedScopeBundle {
  const record = asRecord(value, "scopeBundle");
  assertExactKeys(record, "scopeBundle", [
    "schema_version",
    "catalog_revision",
    "boundary_policy",
    "canonicalized_from",
    "scope",
    "path",
    "presentation",
    "containment",
    "provenance_ref",
  ]);
  if (record.schema_version !== 1) contractError("scopeBundle.schema_version must be 1");
  const catalogRevision = parseCatalogRevision(record.catalog_revision);
  if (requestedRevision !== null && catalogRevision !== requestedRevision) {
    lineageError("scope response revision does not match its request", requestedScope);
  }
  const boundaryPolicy = parseString(record.boundary_policy, "scopeBundle.boundary_policy", 96);
  if (!POLICY_IDENTIFIER.test(boundaryPolicy)) contractError("scopeBundle boundary policy is invalid");
  const scope = parseWireScopeSummary(record.scope, "scope");
  if (scope.key !== requestedScope) {
    lineageError("scope response identity does not match its request", requestedScope);
  }
  if (record.canonicalized_from !== null) {
    const canonicalized = parseScopeKeyCandidate(record.canonicalized_from);
    if (canonicalized !== scope.key) {
      lineageError("canonicalized_from does not resolve to current scope", scope.key);
    }
  }
  const path = parseWirePath(record.path, scope);
  const presentation = asRecord(record.presentation, "presentation");
  assertExactKeys(presentation, "presentation", [
    "preferred_lod",
    "outline_lods",
    "children_lods",
  ]);
  const preferredLod = presentation.preferred_lod === null
    ? null
    : LODS.includes(presentation.preferred_lod as GeometryLod)
      ? presentation.preferred_lod as GeometryLod
      : contractError("presentation.preferred_lod is invalid", scope.key);
  const outlineLods = parseWireLodSet(presentation.outline_lods, "presentation.outline_lods");
  const childrenLods = parseWireLodSet(presentation.children_lods, "presentation.children_lods");
  if (scope.childrenAvailable) {
    if (preferredLod === null || childrenLods[preferredLod] === undefined) {
      contractError("drillable scope has no preferred children LOD", scope.key);
    }
  } else if (preferredLod !== null || Object.keys(childrenLods).length > 0) {
    contractError("non-drillable scope publishes children presentation", scope.key);
  }
  parseString(record.provenance_ref, "scopeBundle.provenance_ref", 256);
  return freezeSpatialValue({
    catalogRevision,
    boundaryPolicy,
    scope,
    path,
    preferredLod,
    outlineLods,
    childrenLods,
    containment: parseWireContainment(record.containment),
  });
}

function descriptorsForScope(bundle: DecodedScopeBundle): readonly AssetDescriptor[] {
  const byId = new Map<string, AssetDescriptor>();
  for (const descriptor of [
    ...Object.values(bundle.outlineLods),
    ...Object.values(bundle.childrenLods),
    bundle.containment,
  ]) {
    if (descriptor === undefined || descriptor === null) continue;
    const existing = byId.get(descriptor.assetId);
    if (existing !== undefined) assertDescriptorMatch(existing, descriptor);
    else byId.set(descriptor.assetId, descriptor);
  }
  return [...byId.values()];
}

function geometryValues(asset: BoundaryAsset): readonly BoundaryGeometryV1[] {
  return "geometryType" in asset
    ? [asset]
    : asset.features.map((feature) => feature.geometry);
}

function extentFromAsset(asset: BoundaryAsset, scopeKey: ScopeKey): GeoExtent {
  if (scopeKey === "world") return { kind: "world" };
  const longitudes: number[] = [];
  let south = 90;
  let north = -90;
  for (const geometry of geometryValues(asset)) {
    for (const polygon of geometry.polygons) {
      for (const ring of polygon) {
        for (const [longitude, latitude] of ring) {
          longitudes.push(longitude);
          south = Math.min(south, latitude);
          north = Math.max(north, latitude);
        }
      }
    }
  }
  if (longitudes.length === 0 || south > north) {
    throw geometryError("Boundary asset cannot produce a camera extent.", scopeKey);
  }
  const ordered = [...new Set(longitudes)].sort((left, right) => left - right);
  let largestGap = -1;
  let gapIndex = 0;
  for (let index = 0; index < ordered.length; index += 1) {
    const current = ordered[index];
    const next = index === ordered.length - 1 ? (ordered[0] ?? 0) + 360 : ordered[index + 1];
    if (current === undefined || next === undefined) continue;
    const gap = next - current;
    if (gap > largestGap) {
      largestGap = gap;
      gapIndex = index;
    }
  }
  const west = ordered[(gapIndex + 1) % ordered.length];
  const east = ordered[gapIndex];
  if (west === undefined || east === undefined) {
    throw geometryError("Boundary longitude extent is unavailable.", scopeKey);
  }
  const longitude = west <= east
    ? [{ west, east }] as const
    : [{ west, east: 180 }, { west: -180, east }] as const;
  return { kind: "segments", south, north, longitude };
}

function semanticPresentation(
  bundle: DecodedScopeBundle,
  error: unknown,
): ResolvedPresentation {
  return {
    mode: "semantic-only",
    scopeKey: bundle.scope.key,
    catalogRevision: bundle.catalogRevision,
    problem: mapSpatialCatalogProblem(error),
  };
}

async function resolvedFromBundle(
  bundle: DecodedScopeBundle,
  assetStore: BoundaryAssetStore,
  signal: AbortSignal,
  prefetchOnly: boolean,
): Promise<ResolvedScope> {
  let presentation: ResolvedPresentation;
  if (bundle.scope.presentation === "semantic-only" || bundle.preferredLod === null) {
    presentation = semanticPresentation(bundle, new SpatialCatalogError({
      code: "GEOMETRY_UNAVAILABLE",
      target: bundle.scope.key,
      message: "Boundary presentation is unavailable.",
      recoverable: false,
    }));
  } else {
    const descriptor = bundle.outlineLods[bundle.preferredLod]
      ?? bundle.containment
      ?? bundle.childrenLods[bundle.preferredLod];
    if (descriptor === undefined) {
      presentation = semanticPresentation(bundle, geometryError(
        "No descriptor can produce a camera extent.",
        bundle.scope.key,
      ));
    } else {
      try {
        if (prefetchOnly) await assetStore.prefetch(descriptor, signal);
        const lease = await assetStore.acquire(descriptor, signal);
        try {
          if (
            "parentScopeKey" in lease.asset &&
            descriptor.mediaType === "application/vnd.odin.boundary-pack+json;v=1" &&
            lease.asset.parentScopeKey !== bundle.scope.key
          ) {
            throw geometryError("Boundary pack parent does not match scope.", bundle.scope.key);
          }
          presentation = {
            mode: "boundary",
            scopeKey: bundle.scope.key,
            catalogRevision: bundle.catalogRevision,
            preferredLod: bundle.preferredLod,
            outlineLods: bundle.outlineLods,
            childrenLods: bundle.childrenLods,
            cameraExtent: extentFromAsset(lease.asset, bundle.scope.key),
          };
        } finally {
          lease.release();
        }
      } catch (error: unknown) {
        if (isAbortFailure(error) || signal.aborted) throw abortError();
        presentation = semanticPresentation(bundle, error);
      }
    }
  }
  return parseResolvedScope({
    scope: bundle.scope,
    path: bundle.path,
    query: {
      schemaVersion: 1,
      scopeKey: bundle.scope.key,
      catalogRevision: bundle.catalogRevision,
      boundaryPolicy: bundle.boundaryPolicy,
    },
    presentation,
    containment: bundle.containment,
  });
}

export class HttpSpatialCatalog implements SpatialCatalogPort {
  private readonly fetcher: SpatialFetch;
  private readonly assetStore: BoundaryAssetStore;
  private readonly clock: SpatialCatalogClock;
  private readonly random: () => number;
  private readonly scopes = new Map<string, ScopeCacheEntry>();
  private readonly negativeScopes = new Map<string, NegativeScopeEntry>();
  private pinnedRevision: CatalogRevision | null = null;
  private disposed = false;

  constructor(options: HttpSpatialCatalogOptions = {}) {
    this.fetcher = options.fetch ?? defaultFetch;
    this.clock = options.clock ?? browserClock;
    this.random = options.random ?? Math.random;
    this.assetStore = options.assetStore ?? new BoundaryAssetStore({
      fetch: this.fetcher,
      clock: this.clock,
      random: this.random,
    });
  }

  async resolve(
    scopeKey: ScopeKey,
    catalogRevision: string | null,
    signal: AbortSignal,
  ): Promise<ResolvedScope> {
    this.assertAvailable();
    const revision = this.requestedRevision(catalogRevision);
    return this.loadScope(scopeKey, revision, signal, true, false);
  }

  async prefetch(
    scopeKey: ScopeKey,
    catalogRevision: string,
    _priority: "hover" | "anticipated",
    signal: AbortSignal,
  ): Promise<void> {
    this.assertAvailable();
    const revision = this.requestedRevision(catalogRevision);
    if (revision === null) {
      throw new SpatialCatalogError({
        code: "CATALOG_REVISION_UNAVAILABLE",
        message: "Prefetch requires a pinned catalog revision.",
      });
    }
    const key = this.scopeKey(scopeKey, revision);
    let entry = this.scopes.get(key);
    if (entry === undefined) {
      await this.loadScope(scopeKey, revision, signal, false, true);
      entry = this.scopes.get(key);
    }
    if (entry === undefined) throw geometryError("Prefetch scope cache is unavailable.", scopeKey);
    for (const descriptor of entry.descriptors) {
      await this.assetStore.prefetch(descriptor, signal);
    }
  }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    this.scopes.clear();
    this.negativeScopes.clear();
    this.assetStore.dispose();
  }

  private async loadScope(
    scopeKey: ScopeKey,
    revision: CatalogRevision | null,
    signal: AbortSignal,
    allowRetry: boolean,
    prefetchOnly: boolean,
  ): Promise<ResolvedScope> {
    if (signal.aborted) throw abortError();
    const cacheKey = this.scopeKey(scopeKey, revision);
    const negative = this.negativeScopes.get(cacheKey);
    if (negative !== undefined) {
      if (negative.expiresAt > this.clock.now()) throw negative.error;
      this.negativeScopes.delete(cacheKey);
    }
    const cached = this.scopes.get(cacheKey);
    const response = await this.fetchScopeResponse(
      scopeKey,
      revision,
      cached?.etag,
      signal,
      allowRetry,
    );
    if (response.status === 304) {
      if (cached === undefined) {
        throw new SpatialCatalogError({
          code: "CATALOG_UNAVAILABLE",
          target: scopeKey,
          message: "Scope returned 304 without a cached representation.",
        });
      }
      return cached.resolved;
    }
    if (!response.ok) {
      const error = await errorFromResponse(response);
      if (response.status === 404) {
        this.negativeScopes.set(cacheKey, {
          expiresAt: this.clock.now() + 30_000,
          error,
        });
      }
      throw error;
    }
    if (response.headers.get("Content-Type")?.split(";", 1)[0] !== "application/json") {
      throw new SpatialCatalogError({
        code: "CATALOG_UNAVAILABLE",
        target: scopeKey,
        message: "Scope response is not JSON.",
      });
    }
    const etag = response.headers.get("ETag");
    if (etag === null || !/^"[^"]+"$/.test(etag)) {
      throw new SpatialCatalogError({
        code: "CATALOG_UNAVAILABLE",
        target: scopeKey,
        message: "Scope response has no valid ETag.",
      });
    }
    const value = await readScopeJson(response, signal);
    if (signal.aborted) throw abortError();
    const bundle = decodeScopeBundle(value, scopeKey, revision);
    const resolved = await resolvedFromBundle(
      bundle,
      this.assetStore,
      signal,
      prefetchOnly,
    );
    const entry: ScopeCacheEntry = freezeSpatialValue({
      etag,
      resolved,
      descriptors: descriptorsForScope(bundle),
    });
    const canonicalKey = this.scopeKey(scopeKey, bundle.catalogRevision);
    this.scopes.set(canonicalKey, entry);
    this.scopes.set(cacheKey, entry);
    if (revision === null && this.pinnedRevision === null) {
      this.pinnedRevision = bundle.catalogRevision;
    }
    return resolved;
  }

  private async fetchScopeResponse(
    scopeKey: ScopeKey,
    revision: CatalogRevision | null,
    etag: string | undefined,
    signal: AbortSignal,
    allowRetry: boolean,
  ): Promise<Response> {
    const parameters = new URLSearchParams({ scope_key: scopeKey });
    if (revision !== null) parameters.set("catalog_revision", revision);
    const url = `/api/spatial/scope?${parameters.toString()}`;
    let retries = 0;
    while (true) {
      if (signal.aborted) throw abortError();
      let response: Response;
      try {
        response = await this.fetcher(url, {
          method: "GET",
          signal,
          headers: {
            Accept: "application/json",
            ...(etag === undefined ? {} : { "If-None-Match": etag }),
          },
        });
      } catch (error: unknown) {
        if (signal.aborted || isAbortFailure(error)) throw abortError();
        if (!allowRetry || retries >= 1) {
          throw new SpatialCatalogError({
            code: "CATALOG_UNAVAILABLE",
            target: scopeKey,
            message: "Spatial scope request failed.",
            recoverable: true,
            cause: error,
          });
        }
        retries += 1;
        await this.clock.sleep(this.jitterDelay(), signal);
        continue;
      }
      if (
        response.status >= 500 &&
        response.status <= 599 &&
        allowRetry &&
        retries < 1
      ) {
        retries += 1;
        await this.clock.sleep(this.jitterDelay(), signal);
        continue;
      }
      return response;
    }
  }

  private requestedRevision(candidate: string | null): CatalogRevision | null {
    if (candidate === null) return this.pinnedRevision;
    try {
      return parseCatalogRevision(candidate);
    } catch (error: unknown) {
      throw new SpatialCatalogError({
        code: "CATALOG_REVISION_UNAVAILABLE",
        target: candidate,
        message: "Catalog revision is invalid or unavailable.",
        recoverable: true,
        cause: error,
      });
    }
  }

  private scopeKey(scopeKey: ScopeKey, revision: CatalogRevision | null): string {
    return `${revision ?? "active"}\u0000${scopeKey}`;
  }

  private jitterDelay(): number {
    return 100 + Math.floor(Math.min(1, Math.max(0, this.random())) * 100);
  }

  private assertAvailable(): void {
    if (this.disposed) {
      throw new SpatialCatalogError({
        code: "CATALOG_UNAVAILABLE",
        message: "HTTP spatial catalog has been disposed.",
      });
    }
  }
}

export function createBootstrapSpatialCatalog(): HttpSpatialCatalog {
  return new HttpSpatialCatalog();
}
