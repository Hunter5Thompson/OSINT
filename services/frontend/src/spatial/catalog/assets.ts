// Internal catalog implementation; consumers use ../catalog.ts.
import {
  type AssetDescriptor,
  freezeSpatialValue,
} from "../contracts";
import {
  SpatialCatalogError,
  geometryError,
  MAX_ASSET_WIRE_BYTES,
  assetLimitError,
  LOD_VERTEX_BUDGET,
  MAX_ASSET_FEATURES,
  type SpatialFetch,
  type SpatialCatalogClock,
  type AssetHasher,
  type AssetCacheEntry,
  type InflightAsset,
  type BoundaryAssetStoreOptions,
  defaultFetch,
  browserClock,
  DEFAULT_DECODED_CACHE_ENTRIES,
  DEFAULT_DECODED_CACHE_BYTES,
  type AssetRetryPolicy,
  type BoundaryAssetLease,
  type BoundaryAssetStoreDiagnostics,
  abortError,
  waitForPromise,
  type DecodedAsset,
  isAbortFailure,
  parseRetryAfter,
} from "./core";
import {
  decodeBoundaryAsset,
} from "./geometry";
import {
  errorFromResponse,
} from "./http";

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

export function assertAssetContentMatch(left: AssetDescriptor, right: AssetDescriptor): void {
  // role, lod and maxErrorMeters belong to a manifest reference, not to the
  // content-addressed bytes cached here. Wire decoding validates those fields;
  // this guard locks the byte representation and decoded shape for one assetId.
  if (
    left.assetId !== right.assetId ||
    left.mediaType !== right.mediaType ||
    left.byteLength !== right.byteLength ||
    left.vertexCount !== right.vertexCount ||
    left.featureCount !== right.featureCount
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

export class BoundaryAssetStore {
  private readonly fetcher: SpatialFetch;
  private readonly clock: SpatialCatalogClock;
  private readonly sha256: AssetHasher;
  private readonly random: () => number;
  private readonly maxEntries: number;
  private readonly maxDecodedBytes: number;
  private readonly cache = new Map<string, AssetCacheEntry>();
  private readonly inflight = new Map<string, InflightAsset>();
  private cacheHits = 0;
  private cacheMisses = 0;
  private evictions = 0;
  private highWaterDecodedBytes = 0;
  private highWaterDecodedEntries = 0;
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
    policy: AssetRetryPolicy = { network: true, busy: true, foreground: true },
  ): Promise<BoundaryAssetLease> {
    return this.acquireWithPolicy(descriptor, signal, policy);
  }

  async prefetch(descriptor: AssetDescriptor, signal: AbortSignal): Promise<void> {
    const lease = await this.acquireForPrefetch(descriptor, signal);
    lease.release();
  }

  async acquireForPrefetch(
    descriptor: AssetDescriptor,
    signal: AbortSignal,
    policy: AssetRetryPolicy = { network: false, busy: false, foreground: false },
  ): Promise<BoundaryAssetLease> {
    return this.acquireWithPolicy(descriptor, signal, policy);
  }

  async acquireForSharedLoad(
    descriptor: AssetDescriptor,
    signal: AbortSignal,
    policy: AssetRetryPolicy,
  ): Promise<BoundaryAssetLease> {
    return policy.foreground
      ? this.acquire(descriptor, signal, policy)
      : this.acquireForPrefetch(descriptor, signal, policy);
  }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    for (const load of this.inflight.values()) load.controller.abort();
    this.inflight.clear();
    this.cache.clear();
  }

  diagnostics(): BoundaryAssetStoreDiagnostics {
    const entries = [...this.cache.values()];
    return freezeSpatialValue({
      activeLeases: entries.reduce((total, entry) => total + entry.leases, 0),
      cacheHits: this.cacheHits,
      cacheMisses: this.cacheMisses,
      decodedBytes: entries.reduce(
        (total, entry) => total + entry.estimatedHeapBytes,
        0,
      ),
      decodedEntries: entries.length,
      disposed: this.disposed,
      evictions: this.evictions,
      highWaterDecodedBytes: this.highWaterDecodedBytes,
      highWaterDecodedEntries: this.highWaterDecodedEntries,
      inflightLoads: this.inflight.size,
      maxDecodedBytes: this.maxDecodedBytes,
      maxEntries: this.maxEntries,
      prefetchedEntries: entries.filter((entry) => entry.prefetched).length,
    });
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
      this.cacheHits += 1;
      assertAssetContentMatch(cached.descriptor, descriptor);
      if (policy.foreground) cached.prefetched = false;
      return this.lease(cached, policy.foreground);
    }
    this.cacheMisses += 1;

    let load = this.inflight.get(descriptor.assetId);
    if (load === undefined) {
      const controller = new AbortController();
      // Keep a live shared policy: a foreground consumer may join after the
      // request starts and still promote a prefetch retry before response handling.
      const retryPolicy = policy;
      load = {
        descriptor,
        controller,
        retryPolicy,
        promise: this.loadAsset(descriptor, controller.signal, retryPolicy),
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
      assertAssetContentMatch(load.descriptor, descriptor);
      load.retryPolicy.network ||= policy.network;
      load.retryPolicy.busy ||= policy.busy;
      load.retryPolicy.foreground ||= policy.foreground;
    }

    load.consumers += 1;
    try {
      await waitForPromise(load.promise, signal);
      if (signal.aborted) throw abortError();
      const entry = this.cache.get(descriptor.assetId);
      if (entry === undefined) throw geometryError("Decoded asset was not cached.", descriptor.assetId);
      if (policy.foreground) entry.prefetched = false;
      return this.lease(entry, policy.foreground);
    } finally {
      load.consumers -= 1;
      if (load.consumers === 0 && !load.settled) {
        load.controller.abort();
        if (this.inflight.get(descriptor.assetId) === load) {
          this.inflight.delete(descriptor.assetId);
        }
      }
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
      prefetched: !load.retryPolicy.foreground,
    });
    // Sample insertion before either foreground or prefetch release can evict.
    this.updateHighWater();
  }

  private lease(entry: AssetCacheEntry, foreground: boolean): BoundaryAssetLease {
    entry.leases += 1;
    entry.lastUsed = this.clock.now();
    this.updateHighWater();
    if (foreground) {
      this.evict();
    }
    let released = false;
    return freezeSpatialValue({
      asset: entry.asset,
      release: () => {
        if (released) return;
        released = true;
        entry.leases -= 1;
        entry.lastUsed = this.clock.now();
        this.updateHighWater();
        this.evict();
      },
    });
  }

  private updateHighWater(): void {
    const entries = [...this.cache.values()];
    this.highWaterDecodedEntries = Math.max(
      this.highWaterDecodedEntries,
      entries.length,
    );
    this.highWaterDecodedBytes = Math.max(
      this.highWaterDecodedBytes,
      entries.reduce((total, candidate) => total + candidate.estimatedHeapBytes, 0),
    );
  }

  private evict(): void {
    let decodedBytes = [...this.cache.values()]
      .reduce((total, entry) => total + entry.estimatedHeapBytes, 0);
    while (this.cache.size > this.maxEntries || decodedBytes > this.maxDecodedBytes) {
      const candidate = [...this.cache.entries()]
        .filter(([, entry]) => entry.leases === 0)
        .sort((left, right) => (
          Number(right[1].prefetched) - Number(left[1].prefetched)
          || left[1].lastUsed - right[1].lastUsed
          || left[0].localeCompare(right[0])
        ))[0];
      if (candidate === undefined) return;
      this.cache.delete(candidate[0]);
      this.evictions += 1;
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
