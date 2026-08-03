import { describe, expect, it, vi } from "vitest";
import fixtureText from "./fixtures/spatial-contract-v1.json?raw";
import {
  HYDRATING_SPATIAL_SCOPE_SNAPSHOT,
  WORLD_SCOPE_KEY,
  freezeSpatialScopeSnapshot,
  parseCatalogRevision,
  parseScopeLocationCandidate,
  parseScopeKeyCandidate,
  scopeKindForKey,
  type CatalogRevision,
  type ScopeKey,
  type ScopeKind,
  type SpatialScopeSnapshot,
} from "../contracts";
import {
  MemorySpatialCatalog,
  SpatialCatalogError,
  mapSpatialCatalogProblem,
  parseResolvedScope,
} from "../catalog";
import {
  MemoryScopeNavigation,
  type ScopeNavigationClock,
} from "../navigation";

interface ScopeKeyVector {
  readonly candidate: string;
  readonly canonical: string;
  readonly kind: ScopeKind;
}

interface LocationCandidateVector {
  readonly candidate: string;
  readonly canonical: string;
}

interface SpatialContractFixture {
  readonly schemaVersion: 1;
  readonly catalogRevision: string;
  readonly boundaryPolicy: string;
  readonly scopeKeyVectors: {
    readonly accepted: readonly ScopeKeyVector[];
    readonly rejected: readonly string[];
  };
  readonly locationCandidateVectors: {
    readonly canonicalized: readonly LocationCandidateVector[];
  };
  readonly catalogRevisionVectors: {
    readonly accepted: readonly string[];
    readonly rejected: readonly string[];
  };
  readonly resolvedScopes: readonly unknown[];
}

function loadFixture(): SpatialContractFixture {
  const value: unknown = JSON.parse(fixtureText);
  return value as SpatialContractFixture;
}

const fixture = loadFixture();

class FakeClock implements ScopeNavigationClock {
  private nextId = 0;
  private readonly callbacks = new Map<number, () => void>();

  setTimeout(callback: () => void): number {
    const id = ++this.nextId;
    this.callbacks.set(id, callback);
    return id;
  }

  clearTimeout(id: number): void {
    this.callbacks.delete(id);
  }

  flush(): void {
    const callbacks = [...this.callbacks.values()];
    this.callbacks.clear();
    callbacks.forEach((callback) => callback());
  }
}

describe("spatial contract vectors", () => {
  it("ports the Slice-0 scope-key grammar into one branded parser", () => {
    for (const vector of fixture.scopeKeyVectors.accepted) {
      const parsed = parseScopeKeyCandidate(vector.candidate);
      expect(parsed).toBe(vector.canonical);
      expect(scopeKindForKey(parsed)).toBe(vector.kind);
      expect(typeof parsed).toBe("string");
    }

    for (const candidate of fixture.scopeKeyVectors.rejected) {
      expect(() => parseScopeKeyCandidate(candidate)).toThrow("INVALID_SCOPE_KEY");
    }
    expect(() => parseScopeKeyCandidate("x".repeat(129))).toThrow("INVALID_SCOPE_KEY");
    expect(() => parseScopeKeyCandidate(null)).toThrow("INVALID_SCOPE_KEY");
  });

  it("validates catalog revisions before they enter router state", () => {
    fixture.catalogRevisionVectors.accepted.forEach((candidate) => {
      expect(parseCatalogRevision(candidate)).toBe(candidate);
    });
    fixture.catalogRevisionVectors.rejected.forEach((candidate) => {
      expect(() => parseCatalogRevision(candidate)).toThrow("CATALOG_REVISION_UNAVAILABLE");
    });
  });

  it("keeps legacy URL aliases separate from canonical ScopeKey identity", () => {
    for (const vector of fixture.locationCandidateVectors.canonicalized) {
      expect(parseScopeLocationCandidate(vector.candidate)).toEqual({
        scopeKey: vector.canonical,
        canonicalizedFrom: vector.candidate,
      });
    }
    expect(parseScopeLocationCandidate("country:UKR")).toEqual({
      scopeKey: "country:UKR",
      canonicalizedFrom: null,
    });
    expect(() => parseScopeKeyCandidate("country:XKX")).toThrow("INVALID_SCOPE_KEY");
  });

  it("keeps the discriminated hydration snapshot deeply frozen and reusable", () => {
    expect(HYDRATING_SPATIAL_SCOPE_SNAPSHOT).toEqual({
      phase: "hydrating",
      stateRevision: 0,
      current: null,
      path: [],
      query: null,
      pending: null,
      problem: null,
      visual: { phase: "none", stateRevision: null },
    });
    expect(Object.isFrozen(HYDRATING_SPATIAL_SCOPE_SNAPSHOT)).toBe(true);
    expect(Object.isFrozen(HYDRATING_SPATIAL_SCOPE_SNAPSHOT.path)).toBe(true);
    expect(Object.isFrozen(HYDRATING_SPATIAL_SCOPE_SNAPSHOT.visual)).toBe(true);

    const ready: SpatialScopeSnapshot = {
      phase: "ready",
      stateRevision: 1,
      current: {
        key: WORLD_SCOPE_KEY,
        kind: "world",
        label: "World",
        shortLabel: "World",
        parentKey: null,
        childrenAvailable: true,
        presentation: "boundary",
      },
      path: [{
        key: WORLD_SCOPE_KEY,
        kind: "world",
        label: "World",
        shortLabel: "World",
        parentKey: null,
        childrenAvailable: true,
        presentation: "boundary",
      }],
      query: {
        schemaVersion: 1,
        scopeKey: WORLD_SCOPE_KEY,
        catalogRevision: parseCatalogRevision(fixture.catalogRevision),
        boundaryPolicy: fixture.boundaryPolicy,
      },
      pending: null,
      problem: null,
      visual: { phase: "building", stateRevision: 1 },
    };
    const frozen = freezeSpatialScopeSnapshot(ready);
    expect(freezeSpatialScopeSnapshot(frozen)).toBe(frozen);
    expect(Object.isFrozen(frozen.path[0])).toBe(true);
    expect(Object.isFrozen(frozen.query)).toBe(true);
    expect("geometry" in frozen).toBe(false);
    expect("geometry" in frozen.current).toBe(false);
  });
});

describe("strict resolved-scope decoding", () => {
  it("accepts the versioned contract fixture and freezes every publication", () => {
    const resolved = fixture.resolvedScopes.map(parseResolvedScope);
    expect(resolved.map((item) => item.scope.key)).toEqual([
      "world",
      "country:UKR",
      "admin1:iso3166-2:UA-14",
    ]);
    expect(Object.isFrozen(resolved[1])).toBe(true);
    expect(Object.isFrozen(resolved[1]?.path)).toBe(true);
    expect(Object.isFrozen(resolved[1]?.presentation)).toBe(true);
    expect("geometry" in (resolved[1] ?? {})).toBe(false);
    expect(resolved.every((item) => item.canonicalizedFrom === null)).toBe(true);
  });

  it("accepts only a canonicalizing source identity in canonicalizedFrom", () => {
    const lowerUkraine = {
      ...(fixture.resolvedScopes[1] as object),
      canonicalizedFrom: "country:ukr",
    };
    expect(parseResolvedScope(lowerUkraine).canonicalizedFrom).toBe("country:ukr");

    const kosovo: unknown = JSON.parse(
      JSON.stringify(fixture.resolvedScopes[1])
        .replaceAll("country:UKR", "country:odin:kosovo")
        .replaceAll("Ukraine", "Kosovo")
        .replace('"canonicalizedFrom":null', '"canonicalizedFrom":"country:XKX"'),
    );
    expect(parseResolvedScope(kosovo)).toMatchObject({
      scope: { key: "country:odin:kosovo" },
      canonicalizedFrom: "country:XKX",
    });

    expect(() => parseResolvedScope({
      ...(fixture.resolvedScopes[1] as object),
      canonicalizedFrom: "country:POL",
    })).toThrow("INVALID_LINEAGE");
  });

  it("rejects extra fields and broken lineage instead of weakening the contract", () => {
    const world = fixture.resolvedScopes[0];
    expect(() => parseResolvedScope({ ...(world as object), geometry: {} })).toThrow(
      "unexpected field",
    );

    const country = structuredClone(fixture.resolvedScopes[1]) as {
      path: Array<{ parentKey: string | null }>;
    };
    if (country.path[1]) country.path[1].parentKey = "country:POL";
    expect(() => parseResolvedScope(country)).toThrow("INVALID_LINEAGE");
  });
});

describe("MemorySpatialCatalog", () => {
  it("resolves the active or pinned revision with stable object identity", async () => {
    const catalog = new MemorySpatialCatalog({
      activeCatalogRevision: fixture.catalogRevision,
      resolvedScopes: fixture.resolvedScopes,
    });
    const ukraine = parseScopeKeyCandidate("country:UKR");
    const active = await catalog.resolve(ukraine, null, new AbortController().signal);
    const pinned = await catalog.resolve(
      ukraine,
      parseCatalogRevision(fixture.catalogRevision),
      new AbortController().signal,
    );

    expect(active).toBe(pinned);
    expect(active.query.scopeKey).toBe(ukraine);
    expect(catalog.resolveCalls).toHaveLength(2);
  });

  it("supports deterministic deferred resolve and caller cancellation", async () => {
    const catalog = new MemorySpatialCatalog({
      activeCatalogRevision: fixture.catalogRevision,
      resolvedScopes: fixture.resolvedScopes,
    });
    const ukraine = parseScopeKeyCandidate("country:UKR");
    const gate = catalog.deferNextResolve(ukraine);
    const aborter = new AbortController();
    const pending = catalog.resolve(ukraine, null, aborter.signal);
    aborter.abort();
    gate.resolve();
    await expect(pending).rejects.toMatchObject({ name: "AbortError" });
  });

  it("maps typed catalog failures to immutable user-facing problems", () => {
    const error = new SpatialCatalogError({
      code: "UNKNOWN_SCOPE",
      target: "country:ZZZ",
      message: "Scope is not present in the catalog.",
      recoverable: false,
    });
    const problem = mapSpatialCatalogProblem(error);
    expect(problem).toEqual({
      severity: "error",
      code: "UNKNOWN_SCOPE",
      target: "country:ZZZ",
      recoverable: false,
      message: "Scope is not present in the catalog.",
    });
    expect(Object.isFrozen(problem)).toBe(true);
  });
});

describe("MemoryScopeNavigation", () => {
  it("uses an injected clock and publishes the exact matching navigation echo", async () => {
    const clock = new FakeClock();
    const navigation = new MemoryScopeNavigation({
      initialScopeCandidate: null,
      clock,
    });
    const listener = vi.fn();
    navigation.subscribeLocation(listener);
    let settled = false;
    const write = navigation.writeScope({
      scopeKey: parseScopeKeyCandidate("country:UKR"),
      catalogRevision: parseCatalogRevision(fixture.catalogRevision),
      mode: "push",
      navigationId: "navigation-1",
    }).then(() => {
      settled = true;
    });

    await Promise.resolve();
    expect(settled).toBe(false);
    expect(navigation.readScopeCandidate()).toBeNull();
    clock.flush();
    await write;

    expect(navigation.readScopeCandidate()).toBe("country:UKR");
    expect(listener).toHaveBeenCalledWith({
      scopeCandidate: "country:UKR",
      catalogRevisionCandidate: fixture.catalogRevision,
      navigationId: "navigation-1",
    });
  });

  it("uses null as the visible world candidate", async () => {
    const navigation = new MemoryScopeNavigation({
      initialScopeCandidate: "country:UKR",
    });
    await navigation.writeScope({
      scopeKey: null,
      catalogRevision: fixture.catalogRevision as CatalogRevision,
      mode: "replace",
      navigationId: "navigation-world",
    });
    expect(navigation.readScopeCandidate()).toBeNull();
  });
});

// Compile-time ownership assertions: commands accept branded identity and never wire geometry.
const _scopeKeyContract: ScopeKey = WORLD_SCOPE_KEY;
const _catalogRevisionContract: CatalogRevision = parseCatalogRevision(fixture.catalogRevision);
void _scopeKeyContract;
void _catalogRevisionContract;
