// Internal catalog implementation; consumers use ../catalog.ts.
import {
  type ScopeSummary,
  scopeKindForKey,
  type ScopePath,
  type ScopeProblem,
  parseCatalogRevision,
  freezeSpatialValue,
  type GeometryLod,
  type RenderAssetDescriptor,
  type AssetLodSet,
  type ContainmentAssetDescriptor,
  type GeoExtent,
  type LongitudeSpan,
  type ScopeKey,
  parseScopeLocationCandidate,
  type CatalogRevision,
  type ResolvedPresentation,
  type ResolvedScope,
  type SpatialQueryRef,
} from "../contracts";
import {
  asRecord,
  assertExactKeys,
  parseCanonicalScopeKey,
  contractError,
  lineageError,
  parseString,
  PROBLEM_CODES,
  ASSET_ID,
  parsePositiveInteger,
  LODS,
  parseFiniteNumber,
  SpatialCatalogError,
  POLICY_IDENTIFIER,
  type SpatialBoundaryAttributionSource,
  type SpatialBoundaryProvenance,
  type DecodedScopeBundle,
} from "./core";

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
    "activeCatalogRevision",
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
  const activeCatalogRevision = record.activeCatalogRevision === null
    ? null
    : parseCatalogRevision(record.activeCatalogRevision);
  return freezeSpatialValue({
    severity: record.severity,
    code: record.code as ScopeProblem["code"],
    target: record.target,
    recoverable: record.recoverable,
    message: parseString(record.message, "problem.message", 500),
    activeCatalogRevision,
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
  let longitudeTuple:
    | readonly [LongitudeSpan]
    | readonly [LongitudeSpan, LongitudeSpan];
  if (longitude.length === 1) {
    const [onlySpan] = longitude;
    if (onlySpan === undefined) contractError("cameraExtent.longitude is empty");
    longitudeTuple = [onlySpan];
  } else {
    const [firstSpan, secondSpan] = longitude;
    if (firstSpan === undefined || secondSpan === undefined) {
      contractError("cameraExtent.longitude must contain two spans");
    }
    longitudeTuple = [firstSpan, secondSpan];
  }
  return {
    kind: "segments",
    south,
    north,
    longitude: longitudeTuple,
  };
}

function parseCanonicalizedFrom(value: unknown, scopeKey: ScopeKey): string | null {
  if (value === null) return null;
  const candidate = parseString(value, "canonicalizedFrom", 128);
  try {
    const parsed = parseScopeLocationCandidate(candidate);
    if (parsed.scopeKey !== scopeKey || parsed.canonicalizedFrom !== candidate) {
      lineageError("canonicalizedFrom does not canonicalize to current", scopeKey);
    }
  } catch (error: unknown) {
    if (error instanceof SpatialCatalogError) throw error;
    throw new SpatialCatalogError({
      code: "INVALID_LINEAGE",
      target: candidate,
      message: "INVALID_LINEAGE: canonicalizedFrom is not a valid location candidate",
      cause: error,
    });
  }
  return candidate;
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
  assertExactKeys(record, "resolvedScope", [
    "scope",
    "path",
    "children",
    "query",
    "presentation",
    "containment",
    "canonicalizedFrom",
  ]);
  const scope = parseScopeSummary(record.scope, "scope");
  const path = parseScopePath(record.path, scope);
  const children = parseDirectChildren(record.children, scope);
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
    children,
    query: {
      schemaVersion: 1,
      scopeKey: queryScopeKey,
      catalogRevision,
      boundaryPolicy,
    },
    presentation: parsePresentation(record.presentation, scope.key, catalogRevision),
    containment: parseContainment(record.containment),
    canonicalizedFrom: parseCanonicalizedFrom(record.canonicalizedFrom, scope.key),
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
    activeCatalogRevision: catalogError.activeCatalogRevision,
  });
}

function reviewedCatalogText(value: unknown, context: string, maxLength: number): string {
  const text = parseString(value, context, maxLength);
  if (text.includes("<") || text.includes(">")) {
    contractError(`${context} must not contain HTML`);
  }
  if (/(?:^|[^A-Za-z0-9])@[A-Za-z0-9_][A-Za-z0-9_.-]*/.test(text)) {
    contractError(`${context} must not contain an external author handle`);
  }
  if (/\p{Cc}/u.test(text)) contractError(`${context} contains a control character`);
  return text;
}

function decodeBoundaryAttributionSource(
  value: unknown,
  context: string,
): SpatialBoundaryAttributionSource {
  const record = asRecord(value, context);
  assertExactKeys(record, context, [
    "source_id",
    "release",
    "license_id",
    "text",
  ]);
  const sourceId = parseString(record.source_id, `${context}.source_id`, 96);
  const licenseId = parseString(record.license_id, `${context}.license_id`, 96);
  if (!POLICY_IDENTIFIER.test(sourceId) || !POLICY_IDENTIFIER.test(licenseId)) {
    contractError(`${context} has an invalid policy identifier`);
  }
  return freezeSpatialValue({
    sourceId,
    release: parseString(record.release, `${context}.release`, 128),
    licenseId,
    text: reviewedCatalogText(record.text, `${context}.text`, 300),
  });
}

export function decodeBoundaryProvenance(
  value: unknown,
  query: Pick<SpatialQueryRef, "catalogRevision" | "boundaryPolicy">,
): SpatialBoundaryProvenance {
  const record = asRecord(value, "catalogBootstrap");
  assertExactKeys(record, "catalogBootstrap", [
    "schema_version",
    "active_catalog_revision",
    "served_catalog_revisions",
    "boundary_policy",
    "root_scope_key",
    "capabilities",
    "attributions",
  ]);
  if (record.schema_version !== 1) contractError("catalogBootstrap.schema_version must be 1");
  const activeRevision = parseCatalogRevision(record.active_catalog_revision);
  if (
    !Array.isArray(record.served_catalog_revisions)
    || record.served_catalog_revisions.length < 1
    || record.served_catalog_revisions.length > 2
  ) {
    contractError("catalogBootstrap.served_catalog_revisions is invalid");
  }
  const servedRevisions = record.served_catalog_revisions.map((revision) =>
    parseCatalogRevision(revision));
  if (
    servedRevisions[0] !== activeRevision
    || new Set(servedRevisions).size !== servedRevisions.length
  ) {
    contractError("catalogBootstrap served revisions are inconsistent");
  }
  const boundaryPolicy = parseString(
    record.boundary_policy,
    "catalogBootstrap.boundary_policy",
    96,
  );
  if (boundaryPolicy !== "odin-reference-v1" || boundaryPolicy !== query.boundaryPolicy) {
    contractError("catalogBootstrap boundary policy does not match the committed scope");
  }
  if (record.root_scope_key !== "world") {
    contractError("catalogBootstrap.root_scope_key must be world");
  }
  const capabilities = asRecord(record.capabilities, "catalogBootstrap.capabilities");
  assertExactKeys(capabilities, "catalogBootstrap.capabilities", [
    "max_enabled_kind",
    "timeline_scope",
    "intelligence_scope",
  ]);
  if (
    typeof capabilities.max_enabled_kind !== "string"
    || !["world", "country", "admin1", "admin2"].includes(
      capabilities.max_enabled_kind,
    )
    || typeof capabilities.timeline_scope !== "string"
    || !["bbox_approximate", "exact"].includes(capabilities.timeline_scope)
    || typeof capabilities.intelligence_scope !== "string"
    || !["unavailable", "exact"].includes(capabilities.intelligence_scope)
  ) {
    contractError("catalogBootstrap capabilities are invalid");
  }
  if (
    !Array.isArray(record.attributions)
    || record.attributions.length !== servedRevisions.length
  ) {
    contractError("catalogBootstrap attributions do not match served revisions");
  }
  const attributions = record.attributions.map((candidate, attributionIndex) => {
    const context = `catalogBootstrap.attributions[${attributionIndex}]`;
    const attribution = asRecord(candidate, context);
    assertExactKeys(attribution, context, [
      "catalog_revision",
      "representation_note",
      "sources",
    ]);
    const catalogRevision = parseCatalogRevision(attribution.catalog_revision);
    if (catalogRevision !== servedRevisions[attributionIndex]) {
      contractError(`${context} does not match its served revision`);
    }
    if (
      !Array.isArray(attribution.sources)
      || attribution.sources.length < 1
      || attribution.sources.length > 32
    ) {
      contractError(`${context}.sources is invalid`);
    }
    const sources = attribution.sources.map((source, sourceIndex) =>
      decodeBoundaryAttributionSource(source, `${context}.sources[${sourceIndex}]`));
    const sourceIds = sources.map((source) => source.sourceId);
    if (
      new Set(sourceIds).size !== sourceIds.length
      || sourceIds.some((sourceId, index) => index > 0 && sourceId < sourceIds[index - 1]!)
    ) {
      contractError(`${context}.sources must be unique and canonically ordered`);
    }
    return freezeSpatialValue({
      boundaryPolicy,
      catalogRevision,
      representationNote: reviewedCatalogText(
        attribution.representation_note,
        `${context}.representation_note`,
        500,
      ),
      sources,
    });
  });
  const selected = attributions.find(
    (attribution) => attribution.catalogRevision === query.catalogRevision,
  );
  if (selected === undefined) {
    throw new SpatialCatalogError({
      code: "CATALOG_REVISION_UNAVAILABLE",
      target: query.catalogRevision,
      message: "Committed catalog revision is not present in catalog metadata.",
      recoverable: true,
      activeCatalogRevision: activeRevision,
    });
  }
  return selected;
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

function parseDirectChildren(value: unknown, current: ScopeSummary): readonly ScopeSummary[] {
  if (!Array.isArray(value)) contractError("children must be an array", current.key);
  const children = value.map((item, index) =>
    parseScopeSummary(item, `children[${index}]`));
  const keys = new Set<ScopeKey>();
  for (const child of children) {
    if (child.parentKey !== current.key || keys.has(child.key)) {
      lineageError("direct child identity does not match current scope", current.key);
    }
    keys.add(child.key);
  }
  if (current.childrenAvailable !== (children.length > 0)) {
    lineageError("children do not match childrenAvailable", current.key);
  }
  return freezeSpatialValue(children);
}

function parseWireChildren(value: unknown, current: ScopeSummary): readonly ScopeSummary[] {
  if (!Array.isArray(value)) contractError("wire children must be an array", current.key);
  return parseDirectChildren(
    value.map((item, index) => {
      const summary = parseWireScopeSummary(item, `children[${index}]`);
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

export function decodeScopeBundle(
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
    "children",
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
  const canonicalizedFrom = parseCanonicalizedFrom(record.canonicalized_from, scope.key);
  const path = parseWirePath(record.path, scope);
  const children = parseWireChildren(record.children, scope);
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
    canonicalizedFrom,
    scope,
    path,
    children,
    preferredLod,
    outlineLods,
    childrenLods,
    containment: parseWireContainment(record.containment),
  });
}
