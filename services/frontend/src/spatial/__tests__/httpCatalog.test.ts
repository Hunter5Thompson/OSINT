import { describe, expect, it, vi } from "vitest";
import {
  parseCatalogRevision,
  parseScopeKeyCandidate,
  type AssetDescriptor,
  type RenderAssetDescriptor,
  type SpatialQueryRef,
} from "../contracts";
import {
  BoundaryAssetStore,
  createBootstrapSpatialCatalog,
  HttpSpatialCatalog,
  SpatialCatalogError,
  type SpatialCatalogClock,
} from "../catalog";

describe("production spatial catalog bootstrap", () => {
  it("uses the backend HTTP adapter", () => {
    const catalog = createBootstrapSpatialCatalog();

    expect(catalog).toBeInstanceOf(HttpSpatialCatalog);
    catalog.dispose();
  });
});

const REVISION = "spatial-v1-fe9828dcda05";
const OLD_REVISION = "spatial-v1-001122334455";
const BOUNDARY_ID = "a".repeat(64);
const PACK_ID = "b".repeat(64);

const geometryWire = {
  schema_version: 1,
  geometry_type: "MultiPolygon",
  polygons: [[[[30, 50], [31, 50], [31, 51], [30, 50]]]],
};
const packWire = {
  schema_version: 1,
  parent_scope_key: "country:UKR",
  features: [{
    kind: "scope",
    scope_key: "admin1:iso3166-2:UA-14",
    label: "Donetsk",
    geometry: geometryWire,
  }],
};
const geometryText = JSON.stringify(geometryWire);
const packText = JSON.stringify(packWire);
const geometryBytes = new TextEncoder().encode(geometryText);
const packBytes = new TextEncoder().encode(packText);

const boundaryDescriptor: RenderAssetDescriptor = {
  assetId: BOUNDARY_ID,
  mediaType: "application/vnd.odin.boundary+json;v=1",
  byteLength: geometryBytes.byteLength,
  vertexCount: 4,
  role: "render",
  lod: "regional",
};
const packDescriptor: RenderAssetDescriptor = {
  assetId: PACK_ID,
  mediaType: "application/vnd.odin.boundary-pack+json;v=1",
  byteLength: packBytes.byteLength,
  vertexCount: 4,
  featureCount: 1,
  role: "render",
  lod: "regional",
};

interface FakeClock extends SpatialCatalogClock {
  readonly sleeps: number[];
  advance(milliseconds: number): void;
}

function createClock(onSleep?: (signal: AbortSignal) => void): FakeClock {
  let now = 0;
  const sleeps: number[] = [];
  return {
    sleeps,
    now: () => now,
    sleep: async (milliseconds, signal) => {
      sleeps.push(milliseconds);
      onSleep?.(signal);
      if (signal.aborted) throw new DOMException("Aborted", "AbortError");
      now += milliseconds;
      await Promise.resolve();
    },
    advance: (milliseconds) => {
      now += milliseconds;
    },
  };
}

function assetResponse(
  assetId: string,
  options: {
    readonly status?: number;
    readonly retryAfter?: string;
    readonly contentLength?: string;
  } = {},
): Response {
  const isPack = assetId === PACK_ID;
  const text = isPack ? packText : geometryText;
  const mediaType = isPack
    ? "application/vnd.odin.boundary-pack+json;v=1"
    : "application/vnd.odin.boundary+json;v=1";
  const headers = new Headers({
    "Content-Type": mediaType,
    "Content-Length": options.contentLength ?? String(new TextEncoder().encode(text).byteLength),
    "Content-Encoding": "identity",
    ETag: `"${assetId}"`,
  });
  if (options.retryAfter !== undefined) headers.set("Retry-After", options.retryAfter);
  return new Response(options.status === undefined || options.status === 200 ? text : null, {
    status: options.status ?? 200,
    headers,
  });
}

function scopeWire(): Record<string, unknown> {
  const world = {
    key: "world",
    kind: "world",
    label: "World",
    short_label: "World",
    parent_key: null,
    children_available: true,
    presentation: "boundary",
  };
  const country = {
    key: "country:UKR",
    kind: "country",
    label: "Ukraine",
    short_label: "Ukraine",
    parent_key: "world",
    children_available: true,
    presentation: "boundary",
  };
  return {
    schema_version: 1,
    catalog_revision: REVISION,
    boundary_policy: "odin-reference-v1",
    canonicalized_from: null,
    scope: country,
    path: [world, country],
    presentation: {
      preferred_lod: "regional",
      outline_lods: {
        regional: {
          asset_id: boundaryDescriptor.assetId,
          media_type: boundaryDescriptor.mediaType,
          byte_length: boundaryDescriptor.byteLength,
          vertex_count: boundaryDescriptor.vertexCount,
          role: "render",
          lod: "regional",
        },
      },
      children_lods: {
        regional: {
          asset_id: packDescriptor.assetId,
          media_type: packDescriptor.mediaType,
          byte_length: packDescriptor.byteLength,
          vertex_count: packDescriptor.vertexCount,
          feature_count: packDescriptor.featureCount,
          role: "render",
          lod: "regional",
        },
      },
    },
    containment: null,
    provenance_ref: "fixture-source",
  };
}

function metadataResponse(value: unknown, etag = '"scope-etag"'): Response {
  return new Response(JSON.stringify(value), {
    status: 200,
    headers: { "Content-Type": "application/json", ETag: etag },
  });
}

function spatialQuery(
  catalogRevision = REVISION,
  boundaryPolicy = "odin-reference-v1",
): Pick<SpatialQueryRef, "catalogRevision" | "boundaryPolicy"> {
  return {
    catalogRevision: parseCatalogRevision(catalogRevision),
    boundaryPolicy,
  };
}

function catalogWire(): Record<string, unknown> {
  return {
    schema_version: 1,
    active_catalog_revision: REVISION,
    served_catalog_revisions: [REVISION, OLD_REVISION],
    boundary_policy: "odin-reference-v1",
    root_scope_key: "world",
    capabilities: {
      max_enabled_kind: "country",
      timeline_scope: "bbox_approximate",
      intelligence_scope: "unavailable",
    },
    attributions: [
      {
        catalog_revision: REVISION,
        representation_note: "ODIN reference boundary representation",
        sources: [
          {
            source_id: "natural-earth-admin0",
            release: "5.1.2+f1890d9f152c",
            license_id: "public-domain",
            text: "Natural Earth",
          },
          {
            source_id: "odin-country-crosswalk",
            release: "spatial-crosswalk-v1",
            license_id: "LicenseRef-ODIN-Reviewed-Crosswalk",
            text: "ODIN reviewed identity registry",
          },
        ],
      },
      {
        catalog_revision: OLD_REVISION,
        representation_note: "Previous reviewed representation",
        sources: [
          {
            source_id: "natural-earth-admin0",
            release: "5.1.1",
            license_id: "public-domain",
            text: "Natural Earth",
          },
        ],
      },
    ],
  };
}

function problemResponse(
  status: number,
  code: string,
  target: string | null,
  activeRevision: string | null = REVISION,
): Response {
  return new Response(JSON.stringify({
    detail: {
      schema_version: 1,
      code,
      message: code,
      target,
      recoverable: status === 409 || status === 429 || status >= 500,
      active_catalog_revision: activeRevision,
    },
  }), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function urlOf(input: RequestInfo | URL): string {
  if (typeof input === "string") return input;
  return input instanceof URL ? input.toString() : input.url;
}

function headersOf(init?: RequestInit): Headers {
  return new Headers(init?.headers);
}

function createStore(
  fetcher: typeof fetch,
  options: {
    readonly clock?: SpatialCatalogClock;
    readonly maxEntries?: number;
    readonly sha256?: (bytes: Uint8Array) => Promise<string>;
    readonly random?: () => number;
  } = {},
): BoundaryAssetStore {
  return new BoundaryAssetStore({
    fetch: fetcher,
    clock: options.clock,
    maxEntries: options.maxEntries,
    random: options.random,
    sha256: options.sha256 ?? (async (bytes) => (
      bytes.byteLength === geometryBytes.byteLength ? BOUNDARY_ID : PACK_ID
    )),
  });
}

describe("HttpSpatialCatalog wire contract", () => {
  it("selects reviewed provenance for the exact committed catalog revision", async () => {
    const fetcher = vi.fn<typeof fetch>(async () => metadataResponse(catalogWire()));
    const catalog = new HttpSpatialCatalog({ fetch: fetcher, assetStore: createStore(fetcher) });

    const provenance = await catalog.loadBoundaryProvenance(
      spatialQuery(OLD_REVISION),
      new AbortController().signal,
    );

    expect(provenance).toEqual({
      boundaryPolicy: "odin-reference-v1",
      catalogRevision: OLD_REVISION,
      representationNote: "Previous reviewed representation",
      sources: [
        {
          licenseId: "public-domain",
          release: "5.1.1",
          sourceId: "natural-earth-admin0",
          text: "Natural Earth",
        },
      ],
    });
    expect(fetcher).toHaveBeenCalledWith(
      "/api/spatial/catalog",
      expect.objectContaining({
        headers: { Accept: "application/json" },
        method: "GET",
        signal: expect.any(AbortSignal),
      }),
    );
  });

  it.each([
    ["stale revision", (wire: Record<string, unknown>) => {
      wire.served_catalog_revisions = [OLD_REVISION];
      wire.attributions = (wire.attributions as unknown[]).slice(1);
      wire.active_catalog_revision = OLD_REVISION;
    }],
    ["extra field", (wire: Record<string, unknown>) => {
      const attribution = (wire.attributions as Array<Record<string, unknown>>)[0];
      if (attribution !== undefined) attribution.external_url = "https://example.invalid";
    }],
    ["array-valued capability", (wire: Record<string, unknown>) => {
      const capabilities = wire.capabilities as Record<string, unknown>;
      capabilities.max_enabled_kind = ["country"];
    }],
    ["external author handle", (wire: Record<string, unknown>) => {
      const attribution = (wire.attributions as Array<Record<string, unknown>>)[0];
      const sources = attribution?.sources as Array<Record<string, unknown>>;
      if (sources[0] !== undefined) sources[0].text = "Data assembled by @unreviewed";
    }],
    ["HTML attribution", (wire: Record<string, unknown>) => {
      const attribution = (wire.attributions as Array<Record<string, unknown>>)[0];
      const sources = attribution?.sources as Array<Record<string, unknown>>;
      if (sources[0] !== undefined) sources[0].text = "<strong>Natural Earth</strong>";
    }],
  ])("rejects %s catalog attribution", async (_name, mutate) => {
    const wire = catalogWire();
    mutate(wire);
    const fetcher = vi.fn<typeof fetch>(async () => metadataResponse(wire));
    const catalog = new HttpSpatialCatalog({ fetch: fetcher, assetStore: createStore(fetcher) });

    await expect(catalog.loadBoundaryProvenance(
      spatialQuery(),
      new AbortController().signal,
    )).rejects.toBeInstanceOf(SpatialCatalogError);
  });

  it("strictly decodes snake_case, pins the revision, and reuses a 304", async () => {
    let scopeRequests = 0;
    const fetcher = vi.fn<typeof fetch>(async (input, init) => {
      const url = urlOf(input);
      if (url.startsWith("/api/spatial/scope")) {
        scopeRequests += 1;
        if (scopeRequests === 2) {
          expect(headersOf(init).get("If-None-Match")).toBe('"scope-etag"');
          return new Response(null, { status: 304, headers: { ETag: '"scope-etag"' } });
        }
        return metadataResponse(scopeWire());
      }
      if (url === `/api/spatial/assets/${BOUNDARY_ID}`) return assetResponse(BOUNDARY_ID);
      throw new Error(`unexpected URL: ${url}`);
    });
    const store = createStore(fetcher);
    const catalog = new HttpSpatialCatalog({ fetch: fetcher, assetStore: store });
    const scopeKey = parseScopeKeyCandidate("country:UKR");

    const active = await catalog.resolve(scopeKey, null, new AbortController().signal);
    const cached = await catalog.resolve(scopeKey, null, new AbortController().signal);

    expect(active).toBe(cached);
    expect(active.scope).toEqual({
      key: scopeKey,
      kind: "country",
      label: "Ukraine",
      shortLabel: "Ukraine",
      parentKey: parseScopeKeyCandidate("world"),
      childrenAvailable: true,
      presentation: "boundary",
    });
    expect(active.query.catalogRevision).toBe(parseCatalogRevision(REVISION));
    expect(active.presentation).toMatchObject({
      mode: "boundary",
      scopeKey,
      catalogRevision: REVISION,
      preferredLod: "regional",
      cameraExtent: {
        kind: "segments",
        south: 50,
        north: 51,
      },
    });
    expect(fetcher.mock.calls.map(([input]) => urlOf(input))).toEqual([
      "/api/spatial/scope?scope_key=country%3AUKR",
      `/api/spatial/assets/${BOUNDARY_ID}`,
      `/api/spatial/scope?scope_key=country%3AUKR&catalog_revision=${REVISION}`,
    ]);
  });

  it("preserves a canonicalizing wire identity separately from ScopeKey", async () => {
    const wire = scopeWire();
    wire.canonicalized_from = "country:ukr";
    const fetcher = vi.fn<typeof fetch>(async (input) => {
      const url = urlOf(input);
      if (url.startsWith("/api/spatial/scope")) return metadataResponse(wire);
      if (url === `/api/spatial/assets/${BOUNDARY_ID}`) return assetResponse(BOUNDARY_ID);
      throw new Error(`unexpected URL: ${url}`);
    });
    const catalog = new HttpSpatialCatalog({ fetch: fetcher, assetStore: createStore(fetcher) });

    const resolved = await catalog.resolve(
      parseScopeKeyCandidate("country:UKR"),
      REVISION,
      new AbortController().signal,
    );

    expect(resolved.canonicalizedFrom).toBe("country:ukr");
  });

  it.each([
    ["unknown field", (wire: Record<string, unknown>) => { wire.unexpected = true; }],
    ["schema", (wire: Record<string, unknown>) => { wire.schema_version = 2; }],
    ["revision mismatch", (wire: Record<string, unknown>) => {
      wire.catalog_revision = OLD_REVISION;
    }],
  ])("rejects %s instead of weakening the decoder", async (_name, mutate) => {
    const wire = scopeWire();
    mutate(wire);
    const fetcher = vi.fn<typeof fetch>(async () => metadataResponse(wire));
    const catalog = new HttpSpatialCatalog({ fetch: fetcher, assetStore: createStore(fetcher) });

    await expect(catalog.resolve(
      parseScopeKeyCandidate("country:UKR"),
      REVISION,
      new AbortController().signal,
    )).rejects.toBeInstanceOf(SpatialCatalogError);
  });

  it("maps 409 visibly without silently replacing the pinned revision", async () => {
    const fetcher = vi.fn<typeof fetch>(async () => problemResponse(
      409,
      "CATALOG_REVISION_UNAVAILABLE",
      OLD_REVISION,
    ));
    const catalog = new HttpSpatialCatalog({ fetch: fetcher, assetStore: createStore(fetcher) });

    await expect(catalog.resolve(
      parseScopeKeyCandidate("country:UKR"),
      OLD_REVISION,
      new AbortController().signal,
    )).rejects.toMatchObject({
      code: "CATALOG_REVISION_UNAVAILABLE",
      target: OLD_REVISION,
      recoverable: true,
      activeCatalogRevision: REVISION,
      message: expect.stringContaining(`Active revision: ${REVISION}`),
    });
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(urlOf(fetcher.mock.calls[0]?.[0] ?? "")).toContain(OLD_REVISION);
  });

  it("resolves a rehydrate only after an explicit active-revision command", async () => {
    const fetcher = vi.fn<typeof fetch>(async (input) => {
      const url = urlOf(input);
      if (url.startsWith("/api/spatial/scope")) return metadataResponse(scopeWire());
      if (url === `/api/spatial/assets/${BOUNDARY_ID}`) return assetResponse(BOUNDARY_ID);
      throw new Error(`unexpected URL: ${url}`);
    });
    const catalog = new HttpSpatialCatalog({ fetch: fetcher, assetStore: createStore(fetcher) });

    const resolved = await catalog.rehydrate(
      parseScopeKeyCandidate("country:UKR"),
      parseCatalogRevision(REVISION),
      new AbortController().signal,
    );
    await catalog.resolve(
      parseScopeKeyCandidate("country:UKR"),
      null,
      new AbortController().signal,
    );

    expect(resolved.query.catalogRevision).toBe(REVISION);
    const scopeRequests = fetcher.mock.calls
      .map((call) => urlOf(call[0]))
      .filter((url) => url.startsWith("/api/spatial/scope"));
    expect(scopeRequests).toHaveLength(2);
    expect(scopeRequests.every(
      (url) => url.includes(`catalog_revision=${REVISION}`),
    )).toBe(true);
  });

  it("negative-caches a 404 for exactly thirty seconds", async () => {
    const clock = createClock();
    const fetcher = vi.fn<typeof fetch>(async () => problemResponse(
      404,
      "UNKNOWN_SCOPE",
      "country:ZZZ",
    ));
    const catalog = new HttpSpatialCatalog({
      fetch: fetcher,
      assetStore: createStore(fetcher, { clock }),
      clock,
    });
    const missing = parseScopeKeyCandidate("country:ZZZ");

    await expect(catalog.resolve(missing, REVISION, new AbortController().signal)).rejects
      .toMatchObject({ code: "UNKNOWN_SCOPE" });
    await expect(catalog.resolve(missing, REVISION, new AbortController().signal)).rejects
      .toMatchObject({ code: "UNKNOWN_SCOPE" });
    expect(fetcher).toHaveBeenCalledTimes(1);

    clock.advance(30_001);
    await expect(catalog.resolve(missing, REVISION, new AbortController().signal)).rejects
      .toMatchObject({ code: "UNKNOWN_SCOPE" });
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("performs one jittered current-signal retry for network/5xx", async () => {
    const clock = createClock();
    let requests = 0;
    const fetcher = vi.fn<typeof fetch>(async (input) => {
      const url = urlOf(input);
      if (url.startsWith("/api/spatial/scope")) {
        requests += 1;
        if (requests === 1) return new Response(null, { status: 503 });
        return metadataResponse(scopeWire());
      }
      return assetResponse(BOUNDARY_ID);
    });
    const catalog = new HttpSpatialCatalog({
      fetch: fetcher,
      assetStore: createStore(fetcher, { clock }),
      clock,
      random: () => 0.5,
    });

    await catalog.resolve(
      parseScopeKeyCandidate("country:UKR"),
      REVISION,
      new AbortController().signal,
    );

    expect(requests).toBe(2);
    expect(clock.sleeps).toEqual([150]);
  });

  it("re-checks cancellation before the jittered retry", async () => {
    const controller = new AbortController();
    const clock = createClock(() => controller.abort());
    const fetcher = vi.fn<typeof fetch>(async () => new Response(null, { status: 503 }));
    const catalog = new HttpSpatialCatalog({
      fetch: fetcher,
      assetStore: createStore(fetcher, { clock }),
      clock,
    });

    await expect(catalog.resolve(
      parseScopeKeyCandidate("country:UKR"),
      REVISION,
      controller.signal,
    )).rejects.toMatchObject({ name: "AbortError" });
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
});

describe("BoundaryAssetStore", () => {
  it("reports bounded decoded-cache counters for canary evidence", async () => {
    const fetcher = vi.fn<typeof fetch>(async (input) => {
      const id = urlOf(input).split("/").at(-1) ?? "";
      return assetResponse(id);
    });
    const store = createStore(fetcher, { maxEntries: 1 });

    const first = await store.acquire(boundaryDescriptor, new AbortController().signal);
    first.release();
    const second = await store.acquire(packDescriptor, new AbortController().signal);
    second.release();

    expect(store.diagnostics()).toEqual({
      activeLeases: 0,
      decodedBytes: 1_728,
      decodedEntries: 1,
      disposed: false,
      inflightLoads: 0,
      maxDecodedBytes: 32 * 1024 * 1024,
      maxEntries: 1,
    });

    store.dispose();
    expect(store.diagnostics()).toEqual({
      activeLeases: 0,
      decodedBytes: 0,
      decodedEntries: 0,
      disposed: true,
      inflightLoads: 0,
      maxDecodedBytes: 32 * 1024 * 1024,
      maxEntries: 1,
    });
  });

  it("validates bytes, hash, schema and descriptor counts before caching", async () => {
    const fetcher = vi.fn<typeof fetch>(async () => assetResponse(BOUNDARY_ID));
    const store = createStore(fetcher);

    const lease = await store.acquire(boundaryDescriptor, new AbortController().signal);

    expect(lease.asset).toMatchObject({ schemaVersion: 1, geometryType: "MultiPolygon" });
    expect(Object.isFrozen(lease.asset)).toBe(true);
    lease.release();
    const again = await store.acquire(boundaryDescriptor, new AbortController().signal);
    expect(again.asset).toBe(lease.asset);
    again.release();
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it.each([
    ["hash", { ...boundaryDescriptor }, async () => "c".repeat(64)],
    ["byte length", { ...boundaryDescriptor, byteLength: geometryBytes.byteLength + 1 }, undefined],
    ["vertex count", { ...boundaryDescriptor, vertexCount: 5 }, undefined],
    ["wire budget", { ...boundaryDescriptor, byteLength: 4 * 1024 * 1024 + 1 }, undefined],
  ])("rejects a %s mismatch", async (_name, descriptor, sha256) => {
    const fetcher = vi.fn<typeof fetch>(async () => assetResponse(
      BOUNDARY_ID,
      { contentLength: String(descriptor.byteLength) },
    ));
    const store = createStore(fetcher, { sha256 });

    await expect(store.acquire(
      descriptor as AssetDescriptor,
      new AbortController().signal,
    )).rejects.toBeInstanceOf(SpatialCatalogError);
  });

  it("rejects a boundary-pack feature-count mismatch", async () => {
    const descriptor = { ...packDescriptor, featureCount: 2 };
    const fetcher = vi.fn<typeof fetch>(async () => assetResponse(PACK_ID));
    const store = createStore(fetcher, { sha256: async () => PACK_ID });

    await expect(store.acquire(descriptor, new AbortController().signal)).rejects
      .toMatchObject({ code: "ASSET_LIMIT_EXCEEDED" });
  });

  it("deduplicates in flight while one aborted consumer cannot poison another", async () => {
    let releaseResponse: ((response: Response) => void) | undefined;
    const pending = new Promise<Response>((resolve) => {
      releaseResponse = resolve;
    });
    const fetcher = vi.fn<typeof fetch>(() => pending);
    const store = createStore(fetcher);
    const firstController = new AbortController();
    const secondController = new AbortController();

    const first = store.acquire(boundaryDescriptor, firstController.signal);
    const second = store.acquire(boundaryDescriptor, secondController.signal);
    firstController.abort();
    releaseResponse?.(assetResponse(BOUNDARY_ID));

    await expect(first).rejects.toMatchObject({ name: "AbortError" });
    const lease = await second;
    expect(fetcher).toHaveBeenCalledTimes(1);
    lease.release();
  });

  it("upgrades a shared prefetch load when active presentation joins", async () => {
    const clock = createClock();
    let releaseFirst: ((response: Response) => void) | undefined;
    const firstResponse = new Promise<Response>((resolve) => {
      releaseFirst = resolve;
    });
    let requests = 0;
    const fetcher = vi.fn<typeof fetch>(() => {
      requests += 1;
      return requests === 1
        ? firstResponse
        : Promise.resolve(assetResponse(BOUNDARY_ID));
    });
    const store = createStore(fetcher, { clock });

    const prefetch = store.prefetch(boundaryDescriptor, new AbortController().signal);
    await vi.waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
    const active = store.acquire(boundaryDescriptor, new AbortController().signal);
    releaseFirst?.(assetResponse(BOUNDARY_ID, { status: 429, retryAfter: "1" }));

    const [prefetchResult, activeResult] = await Promise.allSettled([prefetch, active]);

    expect(prefetchResult.status).toBe("fulfilled");
    expect(activeResult.status).toBe("fulfilled");
    if (activeResult.status === "fulfilled") activeResult.value.release();
    expect(requests).toBe(2);
    expect(clock.sleeps).toEqual([1_000]);
  });

  it("never evicts a leased decoded asset", async () => {
    const fetcher = vi.fn<typeof fetch>(async (input) => {
      const id = urlOf(input).split("/").at(-1) ?? "";
      return assetResponse(id);
    });
    const store = createStore(fetcher, { maxEntries: 1 });
    const first = await store.acquire(boundaryDescriptor, new AbortController().signal);
    const second = await store.acquire(packDescriptor, new AbortController().signal);
    second.release();

    const firstAgain = await store.acquire(boundaryDescriptor, new AbortController().signal);
    expect(firstAgain.asset).toBe(first.asset);
    expect(fetcher).toHaveBeenCalledTimes(2);
    firstAgain.release();
    first.release();
  });

  it("retries 429 once for active presentation but never for prefetch", async () => {
    const clock = createClock();
    let requests = 0;
    const fetcher = vi.fn<typeof fetch>(async () => {
      requests += 1;
      return requests === 1
        ? assetResponse(BOUNDARY_ID, { status: 429, retryAfter: "1" })
        : assetResponse(BOUNDARY_ID);
    });
    const activeStore = createStore(fetcher, { clock });

    const lease = await activeStore.acquire(boundaryDescriptor, new AbortController().signal);
    lease.release();
    expect(requests).toBe(2);
    expect(clock.sleeps).toEqual([1_000]);

    const prefetch = vi.fn<typeof fetch>(async () => assetResponse(
      BOUNDARY_ID,
      { status: 429, retryAfter: "1" },
    ));
    const prefetchStore = createStore(prefetch, { clock: createClock() });
    await expect(prefetchStore.prefetch(
      boundaryDescriptor,
      new AbortController().signal,
    )).rejects.toMatchObject({ code: "ASSET_BUSY" });
    expect(prefetch).toHaveBeenCalledTimes(1);
  });

  it("jitter-retries one active asset 5xx against the current signal", async () => {
    const clock = createClock();
    let requests = 0;
    const fetcher = vi.fn<typeof fetch>(async () => {
      requests += 1;
      return requests === 1
        ? new Response(null, { status: 503 })
        : assetResponse(BOUNDARY_ID);
    });
    const store = createStore(fetcher, { clock, random: () => 0.5 });

    const lease = await store.acquire(boundaryDescriptor, new AbortController().signal);

    lease.release();
    expect(requests).toBe(2);
    expect(clock.sleeps).toEqual([150]);
  });
});
