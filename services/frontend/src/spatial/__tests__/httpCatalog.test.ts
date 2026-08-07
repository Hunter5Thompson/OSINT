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
    readonly maxDecodedBytes?: number;
    readonly maxEntries?: number;
    readonly sha256?: (bytes: Uint8Array) => Promise<string>;
    readonly random?: () => number;
  } = {},
): BoundaryAssetStore {
  return new BoundaryAssetStore({
    fetch: fetcher,
    clock: options.clock,
    maxDecodedBytes: options.maxDecodedBytes,
    maxEntries: options.maxEntries,
    random: options.random,
    sha256: options.sha256 ?? (async (bytes) => (
      bytes.byteLength === geometryBytes.byteLength ? BOUNDARY_ID : PACK_ID
    )),
  });
}

class RecordingAssetStore extends BoundaryAssetStore {
  readonly acquired: AssetDescriptor[] = [];
  readonly prefetched: AssetDescriptor[] = [];

  constructor() {
    super({ fetch: vi.fn<typeof fetch>() });
  }

  override async acquire(descriptor: AssetDescriptor) {
    this.acquired.push(descriptor);
    const geometry = {
      schemaVersion: 1 as const,
      geometryType: "MultiPolygon" as const,
      polygons: [[[[30, 50], [31, 50], [31, 51], [30, 50]]]] as const,
    };
    return {
      asset: descriptor.mediaType.includes("boundary-pack")
        ? {
            schemaVersion: 1 as const,
            parentScopeKey: parseScopeKeyCandidate("country:UKR"),
            features: [{
              kind: "scope" as const,
              scopeKey: parseScopeKeyCandidate("admin1:iso3166-2:UA-14"),
              label: "Donetsk",
              geometry,
            }],
          }
        : geometry,
      release: () => undefined,
    };
  }

  override async acquireForPrefetch(descriptor: AssetDescriptor) {
    this.prefetched.push(descriptor);
    return this.acquire(descriptor);
  }

  override async prefetch(descriptor: AssetDescriptor): Promise<void> {
    this.prefetched.push(descriptor);
  }
}

describe("HttpSpatialCatalog wire contract", () => {
  it("renders a direct non-drillable Admin-1 bundle from its preferred outline", async () => {
    const wire = scopeWire();
    const world = (wire.path as unknown[])[0];
    const country = (wire.path as unknown[])[1];
    const admin1 = {
      key: "admin1:iso3166-2:UA-14",
      kind: "admin1",
      label: "Donetsk Oblast",
      short_label: "Donetsk",
      parent_key: "country:UKR",
      children_available: false,
      presentation: "boundary",
    };
    wire.scope = admin1;
    wire.path = [world, country, admin1];
    wire.presentation = {
      preferred_lod: null,
      outline_lods: (wire.presentation as Record<string, unknown>).outline_lods,
      children_lods: {},
    };
    const fetcher = vi.fn<typeof fetch>(async () => metadataResponse(wire));
    const assets = new RecordingAssetStore();
    const catalog = new HttpSpatialCatalog({ fetch: fetcher, assetStore: assets });

    const resolved = await catalog.resolve(
      parseScopeKeyCandidate("admin1:iso3166-2:UA-14"),
      REVISION,
      new AbortController().signal,
    );

    expect(resolved.presentation).toMatchObject({
      mode: "boundary",
      preferredLod: "regional",
      cameraExtent: { kind: "segments", south: 50, north: 51 },
    });
    expect(assets.acquired.map((descriptor) => descriptor.assetId)).toEqual([BOUNDARY_ID]);
  });

  it("prefetches only the preferred outline and child LOD", async () => {
    const wire = scopeWire();
    const presentation = wire.presentation as Record<string, Record<string, unknown>>;
    presentation.outline_lods = {
      ...(presentation.outline_lods as object),
      overview: {
        asset_id: "c".repeat(64),
        media_type: boundaryDescriptor.mediaType,
        byte_length: boundaryDescriptor.byteLength,
        vertex_count: boundaryDescriptor.vertexCount,
        role: "render",
        lod: "overview",
      },
    };
    presentation.children_lods = {
      ...(presentation.children_lods as object),
      local: {
        asset_id: "d".repeat(64),
        media_type: packDescriptor.mediaType,
        byte_length: packDescriptor.byteLength,
        vertex_count: packDescriptor.vertexCount,
        feature_count: packDescriptor.featureCount,
        role: "render",
        lod: "local",
      },
    };
    wire.containment = {
      asset_id: "e".repeat(64),
      media_type: boundaryDescriptor.mediaType,
      byte_length: boundaryDescriptor.byteLength,
      vertex_count: boundaryDescriptor.vertexCount,
      role: "containment",
      max_error_m: 0,
    };
    const fetcher = vi.fn<typeof fetch>(async () => metadataResponse(wire));
    const assets = new RecordingAssetStore();
    const catalog = new HttpSpatialCatalog({ fetch: fetcher, assetStore: assets });

    await catalog.prefetch(
      parseScopeKeyCandidate("country:UKR"),
      REVISION,
      "hover",
      new AbortController().signal,
    );

    expect(assets.prefetched.map((descriptor) => descriptor.assetId)).toEqual([
      BOUNDARY_ID,
      PACK_ID,
    ]);
    expect(assets.prefetched).toHaveLength(2);
  });

  it("shares an in-flight hover load with click while cancelling only hover", async () => {
    let scopeRequests = 0;
    let assetRequests = 0;
    let releaseAsset: ((response: Response) => void) | undefined;
    const pendingAsset = new Promise<Response>((resolve) => {
      releaseAsset = resolve;
    });
    const fetcher = vi.fn<typeof fetch>(async (input) => {
      const url = urlOf(input);
      if (url.startsWith("/api/spatial/scope")) {
        scopeRequests += 1;
        return metadataResponse(scopeWire());
      }
      if (url === `/api/spatial/assets/${BOUNDARY_ID}`) {
        assetRequests += 1;
        return pendingAsset;
      }
      if (url === `/api/spatial/assets/${PACK_ID}`) return assetResponse(PACK_ID);
      throw new Error(`unexpected URL: ${url}`);
    });
    const store = createStore(fetcher);
    const catalog = new HttpSpatialCatalog({ fetch: fetcher, assetStore: store });
    const scopeKey = parseScopeKeyCandidate("country:UKR");
    const hoverController = new AbortController();

    const hover = catalog.prefetch(
      scopeKey,
      REVISION,
      "hover",
      hoverController.signal,
    );
    await vi.waitFor(() => expect(assetRequests).toBe(1));
    const click = catalog.resolve(
      scopeKey,
      REVISION,
      new AbortController().signal,
    );
    hoverController.abort();
    releaseAsset?.(assetResponse(BOUNDARY_ID));

    await expect(hover).rejects.toMatchObject({ name: "AbortError" });
    await expect(click).resolves.toMatchObject({ scope: { key: scopeKey } });
    expect(scopeRequests).toBe(1);
    expect(assetRequests).toBe(1);
    expect(store.diagnostics()).toMatchObject({
      activeLeases: 0,
      prefetchedEntries: 0,
    });
  });

  it("bounds scope metadata with a 256-entry LRU and exposes high-water counters", async () => {
    const clock = createClock();
    const scopeKeys = ["country:POL", "country:DEU", "country:FRA"] as const;
    const requestCounts = new Map<string, number>();
    const fetcher = vi.fn<typeof fetch>(async (input) => {
      const url = new URL(urlOf(input), "http://odin.test");
      const scopeKey = url.searchParams.get("scope_key") ?? "";
      requestCounts.set(scopeKey, (requestCounts.get(scopeKey) ?? 0) + 1);
      const wire = scopeWire();
      const world = (wire.path as unknown[])[0];
      const country = {
        key: scopeKey,
        kind: "country",
        label: scopeKey,
        short_label: scopeKey,
        parent_key: "world",
        children_available: false,
        presentation: "boundary",
      };
      wire.scope = country;
      wire.path = [world, country];
      wire.presentation = {
        preferred_lod: null,
        outline_lods: (wire.presentation as Record<string, unknown>).outline_lods,
        children_lods: {},
      };
      return metadataResponse(wire, `"${scopeKey}"`);
    });
    const catalog = new HttpSpatialCatalog({
      fetch: fetcher,
      assetStore: new RecordingAssetStore(),
      clock,
      maxScopeEntries: 2,
    });

    for (const scopeKey of scopeKeys) {
      await catalog.resolve(
        parseScopeKeyCandidate(scopeKey),
        REVISION,
        new AbortController().signal,
      );
      clock.advance(1);
    }

    expect(catalog.diagnostics()).toMatchObject({
      metadataEntries: 2,
      metadataEvictions: 1,
      metadataHighWater: 2,
      maxScopeEntries: 2,
    });
    await catalog.resolve(
      parseScopeKeyCandidate(scopeKeys[0]),
      REVISION,
      new AbortController().signal,
    );
    expect(requestCounts.get(scopeKeys[0])).toBe(2);

    const defaultCatalog = new HttpSpatialCatalog({
      fetch: fetcher,
      assetStore: new RecordingAssetStore(),
    });
    expect(defaultCatalog.diagnostics().maxScopeEntries).toBe(256);
  });

  it("also evicts scope metadata against its aggregate byte budget", async () => {
    const clock = createClock();
    const requestCounts = new Map<string, number>();
    const responseFor = (scopeKey: string) => {
      const wire = scopeWire();
      const world = (wire.path as unknown[])[0];
      const country = {
        key: scopeKey,
        kind: "country",
        label: scopeKey,
        short_label: scopeKey,
        parent_key: "world",
        children_available: false,
        presentation: "boundary",
      };
      wire.scope = country;
      wire.path = [world, country];
      wire.presentation = {
        preferred_lod: null,
        outline_lods: (wire.presentation as Record<string, unknown>).outline_lods,
        children_lods: {},
      };
      return wire;
    };
    const firstKey = "country:POL";
    const secondKey = "country:DEU";
    const oneEntryBytes = new TextEncoder().encode(
      JSON.stringify(responseFor(firstKey)),
    ).byteLength;
    const fetcher = vi.fn<typeof fetch>(async (input) => {
      const url = new URL(urlOf(input), "http://odin.test");
      const scopeKey = url.searchParams.get("scope_key") ?? "";
      requestCounts.set(scopeKey, (requestCounts.get(scopeKey) ?? 0) + 1);
      return metadataResponse(responseFor(scopeKey), `"${scopeKey}"`);
    });
    const catalog = new HttpSpatialCatalog({
      fetch: fetcher,
      assetStore: new RecordingAssetStore(),
      clock,
      maxScopeBytes: oneEntryBytes + 16,
      maxScopeEntries: 3,
    });

    for (const scopeKey of [firstKey, secondKey]) {
      await catalog.resolve(
        parseScopeKeyCandidate(scopeKey),
        REVISION,
        new AbortController().signal,
      );
      clock.advance(1);
    }

    expect(catalog.diagnostics()).toMatchObject({
      metadataEntries: 1,
      metadataEvictions: 1,
      maxScopeBytes: oneEntryBytes + 16,
    });
    expect(catalog.diagnostics().metadataBytes).toBeLessThanOrEqual(oneEntryBytes + 16);
    await catalog.resolve(
      parseScopeKeyCandidate(firstKey),
      REVISION,
      new AbortController().signal,
    );
    expect(requestCounts.get(firstKey)).toBe(2);

    catalog.dispose();
    expect(catalog.diagnostics()).toMatchObject({
      disposed: true,
      inflightMetadataLoads: 0,
      metadataBytes: 0,
      metadataEntries: 0,
      negativeEntries: 0,
    });
  });

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

  it("pins the revision, adopts a fresh cached resolve, then revalidates at 60 seconds", async () => {
    const clock = createClock();
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
    const store = createStore(fetcher, { clock });
    const catalog = new HttpSpatialCatalog({ fetch: fetcher, assetStore: store, clock });
    const scopeKey = parseScopeKeyCandidate("country:UKR");

    const active = await catalog.resolve(scopeKey, null, new AbortController().signal);
    const cached = await catalog.resolve(scopeKey, null, new AbortController().signal);
    expect(scopeRequests).toBe(1);
    expect(catalog.diagnostics().metadataEntries).toBe(1);
    clock.advance(60_001);
    const revalidated = await catalog.resolve(
      scopeKey,
      REVISION,
      new AbortController().signal,
    );

    expect(active).toBe(cached);
    expect(active).toBe(revalidated);
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
    expect(scopeRequests).toHaveLength(1);
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

  it("prunes expired negative entries when another scope is requested", async () => {
    const clock = createClock();
    const fetcher = vi.fn<typeof fetch>(async (input) => {
      const url = urlOf(input);
      if (url.includes("scope_key=country%3AZZZ")) {
        return problemResponse(404, "UNKNOWN_SCOPE", "country:ZZZ");
      }
      if (url.startsWith("/api/spatial/scope")) return metadataResponse(scopeWire());
      if (url === `/api/spatial/assets/${BOUNDARY_ID}`) return assetResponse(BOUNDARY_ID);
      throw new Error(`unexpected URL: ${url}`);
    });
    const catalog = new HttpSpatialCatalog({
      fetch: fetcher,
      assetStore: createStore(fetcher, { clock }),
      clock,
    });

    await expect(catalog.resolve(
      parseScopeKeyCandidate("country:ZZZ"),
      REVISION,
      new AbortController().signal,
    )).rejects.toMatchObject({ code: "UNKNOWN_SCOPE" });
    expect(catalog.diagnostics().negativeEntries).toBe(1);

    clock.advance(30_001);
    await catalog.resolve(
      parseScopeKeyCandidate("country:UKR"),
      REVISION,
      new AbortController().signal,
    );
    expect(catalog.diagnostics().negativeEntries).toBe(0);
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
  it("uses the exact Plan-05 decoded-cache budgets by default", () => {
    const fetcher = vi.fn<typeof fetch>();
    const store = createStore(fetcher);

    expect(store.diagnostics()).toMatchObject({
      maxDecodedBytes: 64 * 1024 * 1024,
      maxEntries: 8,
    });
  });

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

    expect(store.diagnostics()).toMatchObject({
      activeLeases: 0,
      decodedBytes: 1_728,
      decodedEntries: 1,
      disposed: false,
      evictions: 1,
      highWaterDecodedBytes: 1_728,
      highWaterDecodedEntries: 1,
      inflightLoads: 0,
      maxDecodedBytes: 64 * 1024 * 1024,
      maxEntries: 1,
      prefetchedEntries: 0,
    });

    store.dispose();
    expect(store.diagnostics()).toMatchObject({
      activeLeases: 0,
      decodedBytes: 0,
      decodedEntries: 0,
      disposed: true,
      inflightLoads: 0,
      maxDecodedBytes: 64 * 1024 * 1024,
      maxEntries: 1,
      prefetchedEntries: 0,
    });
  });

  it("evicts a prefetched entry before an older foreground entry", async () => {
    const clock = createClock();
    const fetcher = vi.fn<typeof fetch>(async (input) => {
      const id = urlOf(input).split("/").at(-1) ?? "";
      return assetResponse(id);
    });
    const store = createStore(fetcher, { clock, maxEntries: 1 });

    const foreground = await store.acquire(
      boundaryDescriptor,
      new AbortController().signal,
    );
    foreground.release();
    clock.advance(10);
    await store.prefetch(packDescriptor, new AbortController().signal);

    const foregroundAgain = await store.acquire(
      boundaryDescriptor,
      new AbortController().signal,
    );
    foregroundAgain.release();
    const prefetchedAgain = await store.acquire(
      packDescriptor,
      new AbortController().signal,
    );
    prefetchedAgain.release();

    expect(fetcher).toHaveBeenCalledTimes(3);
    expect(store.diagnostics()).toMatchObject({ evictions: 2 });
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
