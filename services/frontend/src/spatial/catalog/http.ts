// Internal catalog implementation; consumers use ../catalog.ts.
import {
  parseCatalogRevision,
  type ScopeProblem,
  type GeometryLod,
  type AssetDescriptor,
  type ScopeKey,
  type GeoExtent,
  type ResolvedPresentation,
  type ResolvedScope,
  type SpatialCatalogPort,
  type CatalogRevision,
  type SpatialQueryRef,
  freezeSpatialValue,
} from "../contracts";
import {
  SpatialCatalogError,
  asRecord,
  assertExactKeys,
  parseString,
  type DecodedScopeJson,
  MAX_SCOPE_METADATA_BYTES,
  abortError,
  MAX_CATALOG_METADATA_BYTES,
  contractError,
  type DecodedScopeBundle,
  type BoundaryAsset,
  type BoundaryGeometryV1,
  geometryError,
  type AssetRetryPolicy,
  isAbortFailure,
  type SpatialFetch,
  type SpatialCatalogClock,
  type ScopeCacheEntry,
  type NegativeScopeEntry,
  type InflightScopeLoad,
  type HttpSpatialCatalogOptions,
  defaultFetch,
  browserClock,
  DEFAULT_SCOPE_CACHE_BYTES,
  DEFAULT_SCOPE_CACHE_ENTRIES,
  type SpatialBoundaryProvenance,
  type HttpSpatialCatalogDiagnostics,
  type ScopeLoadPolicy,
  waitForPromise,
  SCOPE_METADATA_FRESH_MILLISECONDS,
} from "./core";
import {
  mapSpatialCatalogProblem,
  parseResolvedScope,
  decodeBoundaryProvenance,
  decodeScopeBundle,
} from "./metadata";
import {
  assertAssetContentMatch,
  BoundaryAssetStore,
} from "./assets";

export async function errorFromResponse(response: Response): Promise<SpatialCatalogError> {
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

async function readScopeJson(
  response: Response,
  signal: AbortSignal,
): Promise<DecodedScopeJson> {
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
  const byteLength = new TextEncoder().encode(text).byteLength;
  if (byteLength > MAX_SCOPE_METADATA_BYTES) {
    throw new SpatialCatalogError({
      code: "CATALOG_UNAVAILABLE",
      message: "Scope metadata exceeded its streaming byte budget.",
      recoverable: false,
    });
  }
  try {
    return { byteLength, value: JSON.parse(text) as unknown };
  } catch (error: unknown) {
    throw new SpatialCatalogError({
      code: "CATALOG_UNAVAILABLE",
      message: "Scope metadata is not valid JSON.",
      recoverable: false,
      cause: error,
    });
  }
}

async function readCatalogJson(response: Response, signal: AbortSignal): Promise<unknown> {
  const declaredLength = response.headers.get("Content-Length");
  if (
    declaredLength !== null
    && (!/^[0-9]+$/.test(declaredLength)
      || Number(declaredLength) > MAX_CATALOG_METADATA_BYTES)
  ) {
    contractError("catalog metadata exceeds its byte budget");
  }
  const text = await response.text();
  if (signal.aborted) throw abortError();
  if (new TextEncoder().encode(text).byteLength > MAX_CATALOG_METADATA_BYTES) {
    contractError("catalog metadata exceeded its streaming byte budget");
  }
  try {
    return JSON.parse(text) as unknown;
  } catch (error: unknown) {
    throw new SpatialCatalogError({
      code: "CATALOG_UNAVAILABLE",
      message: "Catalog metadata is not valid JSON.",
      recoverable: false,
      cause: error,
    });
  }
}

function effectivePresentationLod(bundle: DecodedScopeBundle): GeometryLod | null {
  if (bundle.preferredLod !== null) return bundle.preferredLod;
  for (const lod of ["regional", "overview", "local"] as const) {
    if (bundle.outlineLods[lod] !== undefined) return lod;
  }
  return null;
}

function prefetchDescriptorsForScope(
  bundle: DecodedScopeBundle,
): readonly AssetDescriptor[] {
  const byId = new Map<string, AssetDescriptor>();
  const lod = effectivePresentationLod(bundle);
  for (const descriptor of lod === null
    ? []
    : [bundle.outlineLods[lod], bundle.childrenLods[lod]]) {
    if (descriptor === undefined || descriptor === null) continue;
    const existing = byId.get(descriptor.assetId);
    if (existing !== undefined) assertAssetContentMatch(existing, descriptor);
    else byId.set(descriptor.assetId, descriptor);
  }
  return [...byId.values()];
}

function extentDescriptorForScope(
  bundle: DecodedScopeBundle,
): AssetDescriptor | null {
  const lod = effectivePresentationLod(bundle);
  if (lod === null) return null;
  return bundle.outlineLods[lod]
    ?? bundle.childrenLods[lod]
    ?? bundle.containment
    ?? null;
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
  assetPolicy: AssetRetryPolicy,
): Promise<ResolvedScope> {
  let presentation: ResolvedPresentation;
  const presentationLod = effectivePresentationLod(bundle);
  if (bundle.scope.presentation === "semantic-only" || presentationLod === null) {
    presentation = semanticPresentation(bundle, new SpatialCatalogError({
      code: "GEOMETRY_UNAVAILABLE",
      target: bundle.scope.key,
      message: "Boundary presentation is unavailable.",
      recoverable: false,
    }));
  } else {
    const descriptor = extentDescriptorForScope(bundle);
    if (descriptor === null) {
      presentation = semanticPresentation(bundle, geometryError(
        "No descriptor can produce a camera extent.",
        bundle.scope.key,
      ));
    } else {
      try {
        const lease = await assetStore.acquireForSharedLoad(
          descriptor,
          signal,
          assetPolicy,
        );
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
            preferredLod: presentationLod,
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
    children: bundle.children,
    query: {
      schemaVersion: 1,
      scopeKey: bundle.scope.key,
      catalogRevision: bundle.catalogRevision,
      boundaryPolicy: bundle.boundaryPolicy,
    },
    presentation,
    containment: bundle.containment,
    canonicalizedFrom: bundle.canonicalizedFrom,
  });
}

export class HttpSpatialCatalog implements SpatialCatalogPort {
  private readonly fetcher: SpatialFetch;
  private readonly assetStore: BoundaryAssetStore;
  private readonly clock: SpatialCatalogClock;
  private readonly maxScopeBytes: number;
  private readonly maxScopeEntries: number;
  private readonly random: () => number;
  private readonly scopes = new Map<string, ScopeCacheEntry>();
  private readonly negativeScopes = new Map<string, NegativeScopeEntry>();
  private readonly inflightScopes = new Map<string, InflightScopeLoad>();
  private metadataEvictions = 0;
  private metadataHighWater = 0;
  private metadataHighWaterBytes = 0;
  private metadataHits = 0;
  private metadataMisses = 0;
  private metadataRevalidations = 0;
  private pinnedRevision: CatalogRevision | null = null;
  private disposed = false;

  constructor(options: HttpSpatialCatalogOptions = {}) {
    this.fetcher = options.fetch ?? defaultFetch;
    this.clock = options.clock ?? browserClock;
    this.maxScopeBytes = options.maxScopeBytes ?? DEFAULT_SCOPE_CACHE_BYTES;
    this.maxScopeEntries = options.maxScopeEntries ?? DEFAULT_SCOPE_CACHE_ENTRIES;
    this.random = options.random ?? Math.random;
    if (
      !Number.isSafeInteger(this.maxScopeBytes)
      || this.maxScopeBytes < 1
      || this.maxScopeBytes > DEFAULT_SCOPE_CACHE_BYTES
    ) {
      throw new RangeError(
        `maxScopeBytes must be an integer between 1 and ${DEFAULT_SCOPE_CACHE_BYTES}`,
      );
    }
    if (
      !Number.isSafeInteger(this.maxScopeEntries)
      || this.maxScopeEntries < 1
      || this.maxScopeEntries > DEFAULT_SCOPE_CACHE_ENTRIES
    ) {
      throw new RangeError("maxScopeEntries must be an integer between 1 and 256");
    }
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

  async loadBoundaryProvenance(
    query: Pick<SpatialQueryRef, "catalogRevision" | "boundaryPolicy">,
    signal: AbortSignal,
  ): Promise<SpatialBoundaryProvenance> {
    this.assertAvailable();
    if (signal.aborted) throw abortError();
    let response: Response;
    try {
      response = await this.fetcher("/api/spatial/catalog", {
        method: "GET",
        signal,
        headers: { Accept: "application/json" },
      });
    } catch (error: unknown) {
      if (signal.aborted || isAbortFailure(error)) throw abortError();
      throw new SpatialCatalogError({
        code: "CATALOG_UNAVAILABLE",
        message: "Spatial catalog metadata request failed.",
        recoverable: true,
        cause: error,
      });
    }
    if (!response.ok) throw await errorFromResponse(response);
    if (response.headers.get("Content-Type")?.split(";", 1)[0] !== "application/json") {
      contractError("catalog metadata response is not JSON");
    }
    const value = await readCatalogJson(response, signal);
    if (signal.aborted) throw abortError();
    return decodeBoundaryProvenance(value, query);
  }

  async rehydrate(
    scopeKey: ScopeKey,
    activeCatalogRevision: CatalogRevision,
    signal: AbortSignal,
  ): Promise<ResolvedScope> {
    this.assertAvailable();
    if (signal.aborted) throw abortError();
    const revision = parseCatalogRevision(activeCatalogRevision);
    const resolved = await this.loadScope(scopeKey, revision, signal, true, false);
    if (signal.aborted) throw abortError();
    this.pinnedRevision = revision;
    return resolved;
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
    let loadedForPrefetch = false;
    if (entry === undefined) {
      await this.loadScope(scopeKey, revision, signal, false, true);
      entry = this.scopes.get(key);
      loadedForPrefetch = true;
    }
    if (entry === undefined) throw geometryError("Prefetch scope cache is unavailable.", scopeKey);
    for (const descriptor of entry.prefetchDescriptors) {
      if (loadedForPrefetch && descriptor.assetId === entry.extentAssetId) continue;
      await this.assetStore.prefetch(descriptor, signal);
    }
  }

  diagnostics(): HttpSpatialCatalogDiagnostics {
    return freezeSpatialValue({
      disposed: this.disposed,
      inflightMetadataLoads: this.inflightScopes.size,
      maxScopeBytes: this.maxScopeBytes,
      maxScopeEntries: this.maxScopeEntries,
      metadataBytes: this.metadataBytes(),
      metadataEntries: this.scopes.size,
      metadataEvictions: this.metadataEvictions,
      metadataHighWaterBytes: this.metadataHighWaterBytes,
      metadataHighWater: this.metadataHighWater,
      metadataHits: this.metadataHits,
      metadataMisses: this.metadataMisses,
      metadataRevalidations: this.metadataRevalidations,
      negativeEntries: this.negativeScopes.size,
    });
  }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    for (const load of this.inflightScopes.values()) load.controller.abort();
    this.inflightScopes.clear();
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
    const key = this.scopeKey(scopeKey, revision);
    let load = this.inflightScopes.get(key);
    if (load === undefined) {
      const controller = new AbortController();
      const foreground = !prefetchOnly;
      const policy: ScopeLoadPolicy = {
        allowRetry,
        asset: {
          network: foreground,
          busy: foreground,
          foreground,
        },
      };
      load = {
        controller,
        policy,
        promise: this.performScopeLoad(scopeKey, revision, controller.signal, policy),
        consumers: 0,
        settled: false,
      };
      this.inflightScopes.set(key, load);
      const ownedLoad = load;
      ownedLoad.promise.then(
        () => this.settleScopeLoad(key, ownedLoad),
        () => this.settleScopeLoad(key, ownedLoad),
      );
    } else if (!prefetchOnly) {
      load.policy.allowRetry ||= allowRetry;
      load.policy.asset.network = true;
      load.policy.asset.busy = true;
      load.policy.asset.foreground = true;
    }

    load.consumers += 1;
    try {
      return await waitForPromise(load.promise, signal);
    } finally {
      load.consumers -= 1;
      if (load.consumers === 0 && !load.settled) {
        load.controller.abort();
        if (this.inflightScopes.get(key) === load) this.inflightScopes.delete(key);
      }
    }
  }

  private settleScopeLoad(key: string, load: InflightScopeLoad): void {
    load.settled = true;
    if (this.inflightScopes.get(key) === load) this.inflightScopes.delete(key);
  }

  private async performScopeLoad(
    scopeKey: ScopeKey,
    revision: CatalogRevision | null,
    signal: AbortSignal,
    policy: ScopeLoadPolicy,
  ): Promise<ResolvedScope> {
    if (signal.aborted) throw abortError();
    const cacheKey = this.scopeKey(scopeKey, revision);
    const now = this.clock.now();
    this.pruneExpiredNegativeScopes(now);
    const negative = this.negativeScopes.get(cacheKey);
    if (negative !== undefined) {
      if (negative.expiresAt > now) {
        negative.lastUsed = now;
        throw negative.error;
      }
      this.negativeScopes.delete(cacheKey);
    }
    const cached = this.scopes.get(cacheKey);
    if (
      cached !== undefined
      && now - cached.validatedAt < SCOPE_METADATA_FRESH_MILLISECONDS
    ) {
      cached.lastUsed = now;
      this.metadataHits += 1;
      return cached.resolved;
    }
    if (cached === undefined) this.metadataMisses += 1;
    else this.metadataRevalidations += 1;
    const response = await this.fetchScopeResponse(
      scopeKey,
      revision,
      cached?.etag,
      signal,
      policy,
    );
    if (response.status === 304) {
      if (cached === undefined) {
        throw new SpatialCatalogError({
          code: "CATALOG_UNAVAILABLE",
          target: scopeKey,
          message: "Scope returned 304 without a cached representation.",
        });
      }
      cached.lastUsed = this.clock.now();
      cached.validatedAt = cached.lastUsed;
      this.metadataHits += 1;
      return cached.resolved;
    }
    if (!response.ok) {
      const error = await errorFromResponse(response);
      if (response.status === 404) {
        this.negativeScopes.set(cacheKey, {
          expiresAt: this.clock.now() + 30_000,
          error,
          lastUsed: this.clock.now(),
        });
        this.evictNegativeScopes();
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
    const decodedJson = await readScopeJson(response, signal);
    if (signal.aborted) throw abortError();
    const bundle = decodeScopeBundle(decodedJson.value, scopeKey, revision);
    const resolved = await resolvedFromBundle(
      bundle,
      this.assetStore,
      signal,
      policy.asset,
    );
    const cachedAt = this.clock.now();
    const entry: ScopeCacheEntry = {
      byteLength: decodedJson.byteLength,
      etag,
      resolved,
      extentAssetId: extentDescriptorForScope(bundle)?.assetId ?? null,
      prefetchDescriptors: freezeSpatialValue(prefetchDescriptorsForScope(bundle)),
      lastUsed: cachedAt,
      validatedAt: cachedAt,
    };
    const canonicalKey = this.scopeKey(scopeKey, bundle.catalogRevision);
    this.scopes.set(canonicalKey, entry);
    if (revision === null && this.pinnedRevision === null) {
      this.pinnedRevision = bundle.catalogRevision;
    }
    this.evictScopes();
    this.metadataHighWater = Math.max(this.metadataHighWater, this.scopes.size);
    this.metadataHighWaterBytes = Math.max(
      this.metadataHighWaterBytes,
      this.metadataBytes(),
    );
    return resolved;
  }

  private evictScopes(): void {
    while (
      this.scopes.size > this.maxScopeEntries
      || this.metadataBytes() > this.maxScopeBytes
    ) {
      const candidate = [...this.scopes.entries()].sort((left, right) => (
        left[1].lastUsed - right[1].lastUsed
        || left[0].localeCompare(right[0])
      ))[0];
      if (candidate === undefined) return;
      this.scopes.delete(candidate[0]);
      this.metadataEvictions += 1;
    }
  }

  private metadataBytes(): number {
    return [...this.scopes.values()].reduce(
      (total, entry) => total + entry.byteLength,
      0,
    );
  }

  private evictNegativeScopes(): void {
    this.pruneExpiredNegativeScopes(this.clock.now());
    while (this.negativeScopes.size > this.maxScopeEntries) {
      const candidate = [...this.negativeScopes.entries()].sort((left, right) => (
        left[1].lastUsed - right[1].lastUsed
        || left[0].localeCompare(right[0])
      ))[0];
      if (candidate === undefined) return;
      this.negativeScopes.delete(candidate[0]);
    }
  }

  private pruneExpiredNegativeScopes(now: number): void {
    for (const [key, entry] of this.negativeScopes) {
      if (entry.expiresAt <= now) this.negativeScopes.delete(key);
    }
  }

  private async fetchScopeResponse(
    scopeKey: ScopeKey,
    revision: CatalogRevision | null,
    etag: string | undefined,
    signal: AbortSignal,
    policy: ScopeLoadPolicy,
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
        if (!policy.allowRetry || retries >= 1) {
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
        policy.allowRetry &&
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
        activeCatalogRevision: this.pinnedRevision,
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
