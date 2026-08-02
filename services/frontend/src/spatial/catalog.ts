import {
  freezeSpatialValue,
  parseCatalogRevision,
  parseScopeKeyCandidate,
  scopeKindForKey,
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
  readonly cause?: unknown;
}

export class SpatialCatalogError extends Error {
  readonly code: ScopeProblem["code"];
  readonly target: string | null;
  readonly recoverable: boolean;

  constructor(init: SpatialCatalogErrorInit) {
    super(init.message, { cause: init.cause });
    this.name = "SpatialCatalogError";
    this.code = init.code;
    this.target = init.target ?? null;
    this.recoverable = init.recoverable ?? false;
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

export class MemorySpatialCatalog implements SpatialCatalogPort {
  private readonly activeCatalogRevision: CatalogRevision;
  private readonly entries = new Map<string, ResolvedScope>();
  private readonly revisions = new Set<CatalogRevision>();
  private readonly resolveGates = new Map<ScopeKey, DeferredGate[]>();
  private readonly resolveCallLog: MemoryResolveCall[] = [];
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
    _priority: "hover" | "anticipated",
    signal: AbortSignal,
  ): Promise<void> {
    await this.resolve(scopeKey, catalogRevision, signal);
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
