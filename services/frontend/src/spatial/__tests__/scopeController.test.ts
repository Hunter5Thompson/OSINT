import { afterEach, describe, expect, it } from "vitest";
import fixtureText from "./fixtures/spatial-contract-v1.json?raw";
import {
  HYDRATING_SPATIAL_SCOPE_SNAPSHOT,
  WORLD_SCOPE_KEY,
  parseCatalogRevision,
  parseScopeKeyCandidate,
  type CatalogRevision,
  type ResolvedScope,
  type ResolvedPresentationInput,
  type ScopeKey,
  type SpatialCatalogPort,
} from "../contracts";
import {
  MemorySpatialCatalog,
  SpatialCatalogError,
  parseResolvedScope,
} from "../catalog";
import { MemoryScopeNavigation } from "../navigation";
import {
  createSpatialScopeController,
  type SpatialScopePresentationPort,
} from "../scopeController";

interface Fixture {
  readonly catalogRevision: string;
  readonly boundaryPolicy: string;
  readonly resolvedScopes: readonly unknown[];
}

interface Deferred<T = void> {
  readonly promise: Promise<T>;
  resolve(value: T): void;
  reject(error: unknown): void;
}

function deferred<T = void>(): Deferred<T> {
  let resolvePromise: (value: T) => void = () => undefined;
  let rejectPromise: (error: unknown) => void = () => undefined;
  const promise = new Promise<T>((resolve, reject) => {
    resolvePromise = resolve;
    rejectPromise = reject;
  });
  return { promise, resolve: resolvePromise, reject: rejectPromise };
}

const fixture = JSON.parse(fixtureText) as Fixture;
const UKRAINE = parseScopeKeyCandidate("country:UKR");
const POLAND = parseScopeKeyCandidate("country:POL");
const DONETSK = parseScopeKeyCandidate("admin1:iso3166-2:UA-14");
const VINNYTSIA = parseScopeKeyCandidate("admin1:iso3166-2:UA-05");
const ACTIVE_REVISION = parseCatalogRevision(fixture.catalogRevision);
const RETIRED_REVISION = parseCatalogRevision("spatial-v1-001122334455");
const NEXT_REVISION = parseCatalogRevision("spatial-v1-aabbccddeeff");

interface TestSummary {
  readonly key: string;
  readonly kind: "world" | "country" | "admin1";
  readonly label: string;
  readonly shortLabel: string;
  readonly parentKey: string | null;
  readonly childrenAvailable: boolean;
  readonly presentation: "boundary" | "semantic-only";
}

const worldSummary = {
  key: "world",
  kind: "world",
  label: "World",
  shortLabel: "World",
  parentKey: null,
  childrenAvailable: true,
  presentation: "boundary",
} satisfies TestSummary;

const ukraineSummary = {
  key: "country:UKR",
  kind: "country",
  label: "Ukraine",
  shortLabel: "Ukraine",
  parentKey: "world",
  childrenAvailable: true,
  presentation: "boundary",
} satisfies TestSummary;

function semanticScope(
  scope: TestSummary,
  path: readonly TestSummary[],
): unknown {
  return {
    scope,
    path,
    query: {
      schemaVersion: 1,
      scopeKey: scope.key,
      catalogRevision: fixture.catalogRevision,
      boundaryPolicy: fixture.boundaryPolicy,
    },
    presentation: {
      mode: "semantic-only",
      scopeKey: scope.key,
      catalogRevision: fixture.catalogRevision,
      problem: {
        severity: "warning",
        code: "GEOMETRY_UNAVAILABLE",
        target: scope.key,
        recoverable: false,
        message: "Boundary presentation is unavailable.",
        activeCatalogRevision: null,
      },
    },
    containment: null,
    canonicalizedFrom: null,
  };
}

const polandSummary = {
  key: "country:POL",
  kind: "country",
  label: "Poland",
  shortLabel: "Poland",
  parentKey: "world",
  childrenAvailable: false,
  presentation: "semantic-only",
} satisfies TestSummary;

const vinnytsiaSummary = {
  key: "admin1:iso3166-2:UA-05",
  kind: "admin1",
  label: "Vinnytsia Oblast",
  shortLabel: "Vinnytsia",
  parentKey: "country:UKR",
  childrenAvailable: false,
  presentation: "semantic-only",
} satisfies TestSummary;

const extraScopes = [
  semanticScope(polandSummary, [worldSummary, polandSummary]),
  semanticScope(vinnytsiaSummary, [worldSummary, ukraineSummary, vinnytsiaSummary]),
];

interface RolloverCall {
  readonly kind: "resolve" | "rehydrate";
  readonly scopeKey: ScopeKey;
  readonly catalogRevision: CatalogRevision;
  readonly signal: AbortSignal;
}

class RolloverSpatialCatalog implements SpatialCatalogPort {
  readonly calls: RolloverCall[] = [];
  private readonly entries = new Map<string, ResolvedScope>();
  private activeRevision = RETIRED_REVISION;
  private retiredOldRevision = false;
  private rehydrateGate: Deferred<void> | null = null;
  private rehydrateFailure: SpatialCatalogError | null = null;

  constructor() {
    for (const candidate of [...fixture.resolvedScopes, ...extraScopes]) {
      const active = parseResolvedScope(candidate);
      const retired = parseResolvedScope(JSON.parse(
        JSON.stringify(candidate).replaceAll(fixture.catalogRevision, RETIRED_REVISION),
      ) as unknown);
      this.entries.set(this.entryKey(active.scope.key, ACTIVE_REVISION), active);
      this.entries.set(this.entryKey(retired.scope.key, RETIRED_REVISION), retired);
    }
  }

  rollover(): void {
    this.activeRevision = ACTIVE_REVISION;
    this.retiredOldRevision = true;
  }

  deferNextRehydrate(): Deferred<void> {
    const gate = deferred<void>();
    this.rehydrateGate = gate;
    return gate;
  }

  failNextRehydrate(error: SpatialCatalogError): void {
    this.rehydrateFailure = error;
  }

  async resolve(
    scopeKey: ScopeKey,
    catalogRevision: string | null,
    signal: AbortSignal,
  ): Promise<ResolvedScope> {
    const revision = catalogRevision === null
      ? this.activeRevision
      : parseCatalogRevision(catalogRevision);
    this.calls.push({ kind: "resolve", scopeKey, catalogRevision: revision, signal });
    if (signal.aborted) throw new DOMException("Aborted", "AbortError");
    if (revision === RETIRED_REVISION && this.retiredOldRevision) {
      throw new SpatialCatalogError({
        code: "CATALOG_REVISION_UNAVAILABLE",
        target: revision,
        message: "The pinned revision is no longer served.",
        recoverable: true,
        activeCatalogRevision: this.activeRevision,
      });
    }
    return this.lookup(scopeKey, revision);
  }

  async rehydrate(
    scopeKey: ScopeKey,
    activeCatalogRevision: CatalogRevision,
    signal: AbortSignal,
  ): Promise<ResolvedScope> {
    this.calls.push({
      kind: "rehydrate",
      scopeKey,
      catalogRevision: activeCatalogRevision,
      signal,
    });
    const failure = this.rehydrateFailure;
    this.rehydrateFailure = null;
    if (failure !== null) throw failure;
    const gate = this.rehydrateGate;
    this.rehydrateGate = null;
    if (gate !== null) await gate.promise;
    if (activeCatalogRevision !== this.activeRevision) {
      throw new SpatialCatalogError({
        code: "CATALOG_REVISION_UNAVAILABLE",
        target: activeCatalogRevision,
        message: "The requested recovery revision changed again.",
        recoverable: true,
        activeCatalogRevision: this.activeRevision,
      });
    }
    return this.lookup(scopeKey, activeCatalogRevision);
  }

  async prefetch(
    _scopeKey: ScopeKey,
    _catalogRevision: string,
    _priority: "hover" | "anticipated",
    signal: AbortSignal,
  ): Promise<void> {
    if (signal.aborted) throw new DOMException("Aborted", "AbortError");
  }

  dispose(): void {
    this.entries.clear();
  }

  private lookup(scopeKey: ScopeKey, revision: CatalogRevision): ResolvedScope {
    const resolved = this.entries.get(this.entryKey(scopeKey, revision));
    if (resolved === undefined) {
      throw new SpatialCatalogError({
        code: "UNKNOWN_SCOPE",
        target: scopeKey,
        message: "Scope is absent from the selected revision.",
      });
    }
    return resolved;
  }

  private entryKey(scopeKey: ScopeKey, revision: CatalogRevision): string {
    return `${revision}\u0000${scopeKey}`;
  }
}

class ControlledPresentation implements SpatialScopePresentationPort {
  readonly calls: Array<{
    readonly input: ResolvedPresentationInput;
    readonly stateRevision: number;
    readonly signal: AbortSignal;
  }> = [];
  private readonly gates = new Map<ScopeKey, Deferred<void>[]>();

  deferNext(scopeKey: ScopeKey): Deferred<void> {
    const gate = deferred<void>();
    const queue = this.gates.get(scopeKey) ?? [];
    queue.push(gate);
    this.gates.set(scopeKey, queue);
    return gate;
  }

  present(
    input: ResolvedPresentationInput,
    stateRevision: number,
    signal: AbortSignal,
  ): Promise<void> {
    this.calls.push({ input, stateRevision, signal });
    const queue = this.gates.get(input.scopeKey);
    const gate = queue?.shift();
    if (queue?.length === 0) this.gates.delete(input.scopeKey);
    return gate?.promise ?? Promise.resolve();
  }
}

const liveControllers: Array<ReturnType<typeof createSpatialScopeController>> = [];

function setup(options: {
  readonly initialScopeCandidate?: string | null;
  readonly presentation?: SpatialScopePresentationPort;
} = {}) {
  const catalog = new MemorySpatialCatalog({
    activeCatalogRevision: fixture.catalogRevision,
    resolvedScopes: [...fixture.resolvedScopes, ...extraScopes],
  });
  const navigation = new MemoryScopeNavigation({
    initialScopeCandidate: options.initialScopeCandidate ?? null,
  });
  const presentation = options.presentation ?? new ControlledPresentation();
  let navigationId = 0;
  const controller = createSpatialScopeController({
    catalog,
    navigation,
    presentation,
    createNavigationId: () => `test-navigation-${++navigationId}`,
  });
  liveControllers.push(controller);
  return { catalog, navigation, presentation, controller };
}

async function waitForScope(
  controller: ReturnType<typeof createSpatialScopeController>,
  scopeKey: ScopeKey,
): Promise<void> {
  if (controller.getSnapshot().query?.scopeKey === scopeKey) return;
  await new Promise<void>((resolve) => {
    const unsubscribe = controller.subscribe(() => {
      if (controller.getSnapshot().query?.scopeKey === scopeKey) {
        unsubscribe();
        resolve();
      }
    });
  });
}

async function startAtWorld(
  controller: ReturnType<typeof createSpatialScopeController>,
): Promise<void> {
  controller.start();
  await waitForScope(controller, WORLD_SCOPE_KEY);
}

async function setupRetiredRevision() {
  const catalog = new RolloverSpatialCatalog();
  const navigation = new MemoryScopeNavigation({
    initialScopeCandidate: UKRAINE,
  });
  const controller = createSpatialScopeController({ catalog, navigation });
  liveControllers.push(controller);
  controller.start();
  await waitForScope(controller, UKRAINE);
  expect(controller.getSnapshot().query?.catalogRevision).toBe(RETIRED_REVISION);
  catalog.rollover();
  const committedQuery = controller.getSnapshot().query;

  const failed = await controller.dispatch({
    type: "enter",
    target: DONETSK,
    cause: "child-click",
  });

  expect(failed).toMatchObject({
    outcome: "failed",
    problem: {
      code: "CATALOG_REVISION_UNAVAILABLE",
      activeCatalogRevision: ACTIVE_REVISION,
    },
  });
  expect(controller.getSnapshot().query).toBe(committedQuery);
  expect(navigation.writes).toHaveLength(0);
  return { catalog, navigation, controller, committedQuery };
}

afterEach(() => {
  liveControllers.splice(0).forEach((controller) => controller.stop());
});

describe("SpatialScopeController hydration and hierarchy", () => {
  it("hydrates a deep link without ever publishing a world query flash", async () => {
    const { catalog, controller } = setup({ initialScopeCandidate: DONETSK });
    const gate = catalog.deferNextResolve(DONETSK);
    const publishedQueries: Array<ScopeKey | null> = [];
    controller.subscribe(() => {
      publishedQueries.push(controller.getSnapshot().query?.scopeKey ?? null);
    });

    expect(controller.getSnapshot()).toBe(HYDRATING_SPATIAL_SCOPE_SNAPSHOT);
    controller.start();
    expect(controller.getSnapshot().phase).toBe("hydrating");
    expect(controller.getSnapshot().query).toBeNull();
    gate.resolve();
    await waitForScope(controller, DONETSK);

    expect(publishedQueries).not.toContain(WORLD_SCOPE_KEY);
    expect(controller.getSnapshot().path.map((item) => item.key)).toEqual([
      WORLD_SCOPE_KEY,
      UKRAINE,
      DONETSK,
    ]);
  });

  it("commits world to country to admin1 and ascends via the catalog parent", async () => {
    const { controller } = setup();
    await startAtWorld(controller);
    await expect(controller.dispatch({
      type: "enter",
      target: UKRAINE,
      cause: "country-click",
    })).resolves.toMatchObject({ outcome: "committed" });
    await expect(controller.dispatch({
      type: "enter",
      target: DONETSK,
      cause: "child-click",
    })).resolves.toMatchObject({ outcome: "committed" });
    await expect(controller.dispatch({
      type: "ascend",
      cause: "breadcrumb",
    })).resolves.toMatchObject({ outcome: "committed" });

    expect(controller.getSnapshot().current?.key).toBe(UKRAINE);
    expect(controller.getSnapshot().path.map((item) => item.key)).toEqual([
      WORLD_SCOPE_KEY,
      UKRAINE,
    ]);
  });

  it("reconstructs a complete canonical lineage when entering a sibling", async () => {
    const { controller } = setup({ initialScopeCandidate: DONETSK });
    controller.start();
    await waitForScope(controller, DONETSK);
    await controller.dispatch({
      type: "enter",
      target: VINNYTSIA,
      cause: "child-click",
    });
    expect(controller.getSnapshot().path.map((item) => item.key)).toEqual([
      WORLD_SCOPE_KEY,
      UKRAINE,
      VINNYTSIA,
    ]);
  });

  it("treats current and root commands as no-ops without history writes", async () => {
    const { controller, navigation } = setup();
    await startAtWorld(controller);
    const before = controller.getSnapshot();

    await expect(controller.dispatch({
      type: "enter",
      target: WORLD_SCOPE_KEY,
      cause: "programmatic",
    })).resolves.toEqual({ outcome: "unchanged", snapshot: before });
    await expect(controller.dispatch({
      type: "ascend",
      cause: "keyboard",
    })).resolves.toEqual({ outcome: "unchanged", snapshot: before });
    expect(navigation.writes).toHaveLength(0);
    expect(controller.getSnapshot()).toBe(before);
  });
});

describe("SpatialScopeController generations and failures", () => {
  it("lets B supersede a deferred A without stale state or URL mutation", async () => {
    const { catalog, controller, navigation } = setup();
    await startAtWorld(controller);
    const gateA = catalog.deferNextResolve(UKRAINE);
    const resultA = controller.dispatch({
      type: "enter",
      target: UKRAINE,
      cause: "country-click",
    });
    expect(controller.getSnapshot().pending).toBe(UKRAINE);

    const resultB = controller.dispatch({
      type: "enter",
      target: POLAND,
      cause: "country-click",
    });
    await expect(resultB).resolves.toMatchObject({ outcome: "committed" });
    gateA.resolve();
    await expect(resultA).resolves.toEqual({ outcome: "superseded" });

    expect(controller.getSnapshot().current?.key).toBe(POLAND);
    expect(navigation.writes.map((write) => write.scopeKey)).toEqual([POLAND]);
  });

  it("returns cancelled for caller abort and leaves the committed scope intact", async () => {
    const { catalog, controller, navigation } = setup();
    await startAtWorld(controller);
    const gate = catalog.deferNextResolve(UKRAINE);
    const aborter = new AbortController();
    const result = controller.dispatch({
      type: "enter",
      target: UKRAINE,
      cause: "country-click",
    }, { signal: aborter.signal });
    aborter.abort();
    gate.resolve();

    await expect(result).resolves.toEqual({ outcome: "cancelled" });
    expect(controller.getSnapshot().current?.key).toBe(WORLD_SCOPE_KEY);
    expect(controller.getSnapshot().pending).toBeNull();
    expect(navigation.writes).toHaveLength(0);
  });

  it("returns cancelled when stop aborts work without a newer intent", async () => {
    const { catalog, controller } = setup();
    await startAtWorld(controller);
    const gate = catalog.deferNextResolve(UKRAINE);
    const result = controller.dispatch({
      type: "enter",
      target: UKRAINE,
      cause: "country-click",
    });
    controller.stop();
    gate.resolve();

    await expect(result).resolves.toEqual({ outcome: "cancelled" });
    expect(controller.getSnapshot()).toBe(HYDRATING_SPATIAL_SCOPE_SNAPSHOT);
  });

  it("ascends from the committed parent while a child drilldown is pending", async () => {
    const { catalog, controller } = setup({ initialScopeCandidate: UKRAINE });
    controller.start();
    await waitForScope(controller, UKRAINE);
    const gate = catalog.deferNextResolve(DONETSK);
    const child = controller.dispatch({
      type: "enter",
      target: DONETSK,
      cause: "child-click",
    });
    const ascend = controller.dispatch({ type: "ascend", cause: "breadcrumb" });

    await expect(ascend).resolves.toMatchObject({ outcome: "committed" });
    gate.resolve();
    await expect(child).resolves.toEqual({ outcome: "superseded" });
    expect(controller.getSnapshot().current?.key).toBe(WORLD_SCOPE_KEY);
  });

  it("shares one in-flight resolve between prefetch and foreground enter", async () => {
    const { catalog, controller } = setup();
    await startAtWorld(controller);
    const gate = catalog.deferNextResolve(UKRAINE);
    const prefetch = controller.dispatch({
      type: "prefetch",
      target: UKRAINE,
      priority: "hover",
    });
    const enter = controller.dispatch({
      type: "enter",
      target: UKRAINE,
      cause: "country-click",
    });
    expect(catalog.resolveCalls.filter((call) => call.scopeKey === UKRAINE)).toHaveLength(1);
    gate.resolve();

    await expect(prefetch).resolves.toEqual({ outcome: "prefetched", target: UKRAINE });
    await expect(enter).resolves.toMatchObject({ outcome: "committed" });
    expect(catalog.resolveCalls.filter((call) => call.scopeKey === UKRAINE)).toHaveLength(1);
  });

  it("maps catalog failure into a result and never rejects or changes the query", async () => {
    const { controller, navigation } = setup();
    await startAtWorld(controller);
    const beforeQuery = controller.getSnapshot().query;

    await expect(controller.dispatch({
      type: "enter",
      target: parseScopeKeyCandidate("country:DEU"),
      cause: "search",
    })).resolves.toMatchObject({
      outcome: "failed",
      problem: { code: "UNKNOWN_SCOPE", target: "country:DEU" },
    });
    expect(controller.getSnapshot().query).toBe(beforeQuery);
    expect(controller.getSnapshot().phase).toBe("ready");
    expect(navigation.writes).toHaveLength(0);
  });

  it("requires an explicit 409 rehydrate before replacing the committed revision", async () => {
    const { catalog, controller, navigation, committedQuery } = await setupRetiredRevision();
    const committedStateRevision = controller.getSnapshot().stateRevision;

    expect(catalog.calls.filter((call) => call.scopeKey === DONETSK)).toHaveLength(1);
    expect(controller.getSnapshot()).toMatchObject({
      phase: "ready",
      current: { key: UKRAINE },
      query: { catalogRevision: RETIRED_REVISION },
      problem: {
        code: "CATALOG_REVISION_UNAVAILABLE",
        activeCatalogRevision: ACTIVE_REVISION,
      },
    });
    expect(controller.getSnapshot().query).toBe(committedQuery);

    const recovered = await controller.dispatch({ type: "rehydrate" });

    expect(recovered).toMatchObject({ outcome: "committed" });
    expect(controller.getSnapshot()).toMatchObject({
      phase: "ready",
      stateRevision: committedStateRevision + 1,
      current: { key: UKRAINE },
      query: { catalogRevision: ACTIVE_REVISION },
      problem: null,
    });
    expect(navigation.writes).toEqual([
      expect.objectContaining({
        scopeKey: UKRAINE,
        catalogRevision: ACTIVE_REVISION,
        mode: "replace",
      }),
    ]);
    expect(catalog.calls.map((call) => [
      call.kind,
      call.scopeKey,
      call.catalogRevision,
    ])).toEqual([
      ["resolve", UKRAINE, RETIRED_REVISION],
      ["resolve", DONETSK, RETIRED_REVISION],
      ["rehydrate", UKRAINE, ACTIVE_REVISION],
    ]);
  });

  it.each([
    [
      "404",
      new SpatialCatalogError({
        code: "UNKNOWN_SCOPE",
        target: UKRAINE,
        message: "The committed scope is absent from the active revision.",
      }),
      "UNKNOWN_SCOPE",
      null,
    ],
    [
      "network/5xx",
      new SpatialCatalogError({
        code: "CATALOG_UNAVAILABLE",
        target: UKRAINE,
        message: "The active catalog cannot be reached.",
        recoverable: true,
      }),
      "CATALOG_UNAVAILABLE",
      null,
    ],
    [
      "second 409",
      new SpatialCatalogError({
        code: "CATALOG_REVISION_UNAVAILABLE",
        target: ACTIVE_REVISION,
        message: "The recovery revision changed again.",
        recoverable: true,
        activeCatalogRevision: NEXT_REVISION,
      }),
      "CATALOG_REVISION_UNAVAILABLE",
      NEXT_REVISION,
    ],
  ] as const)("keeps a rehydrate %s visible and fail-closed", async (
    _case,
    error,
    expectedCode,
    expectedActiveRevision,
  ) => {
    const { catalog, controller, navigation, committedQuery } = await setupRetiredRevision();
    catalog.failNextRehydrate(error);

    const result = await controller.dispatch({ type: "rehydrate" });

    expect(result).toMatchObject({
      outcome: "failed",
      problem: {
        code: expectedCode,
        activeCatalogRevision: expectedActiveRevision,
      },
    });
    expect(controller.getSnapshot().query).toBe(committedQuery);
    expect(controller.getSnapshot().current?.key).toBe(UKRAINE);
    expect(navigation.writes).toHaveLength(0);
    expect(catalog.calls.some((call) => call.scopeKey === WORLD_SCOPE_KEY)).toBe(false);
  });

  it("does not call the rehydrate adapter for an already-aborted intent", async () => {
    const { catalog, controller, committedQuery } = await setupRetiredRevision();
    const aborter = new AbortController();
    aborter.abort();
    const callsBefore = catalog.calls.length;

    const result = await controller.dispatch(
      { type: "rehydrate" },
      { signal: aborter.signal },
    );

    expect(result).toEqual({ outcome: "cancelled" });
    expect(catalog.calls).toHaveLength(callsBefore);
    expect(controller.getSnapshot().query).toBe(committedQuery);
  });

  it("cannot commit an older rehydrate response over a newer history intent", async () => {
    const { catalog, controller } = await setupRetiredRevision();
    const gate = catalog.deferNextRehydrate();
    const recovery = controller.dispatch({ type: "rehydrate" });
    const newer = controller.dispatch({
      type: "hydrate",
      target: POLAND,
      catalogRevision: ACTIVE_REVISION,
      cause: "browser-history",
    });

    await expect(newer).resolves.toMatchObject({ outcome: "committed" });
    gate.resolve();
    await expect(recovery).resolves.toEqual({ outcome: "superseded" });
    expect(controller.getSnapshot()).toMatchObject({
      current: { key: POLAND },
      query: { catalogRevision: ACTIVE_REVISION },
    });
  });
});

describe("SpatialScopeController semantic and presentation lifetimes", () => {
  it("commits semantic-only scope and reports unavailable geometry without rollback", async () => {
    const presentation = new ControlledPresentation();
    const { controller } = setup({ presentation });
    await startAtWorld(controller);
    const result = await controller.dispatch({
      type: "enter",
      target: DONETSK,
      cause: "programmatic",
    });

    expect(result.outcome).toBe("committed");
    expect(controller.getSnapshot()).toMatchObject({
      phase: "ready",
      current: { key: DONETSK },
      query: { scopeKey: DONETSK },
      problem: { code: "GEOMETRY_UNAVAILABLE" },
      visual: {
        phase: "unavailable",
        problem: { code: "GEOMETRY_UNAVAILABLE" },
      },
    });
    expect(presentation.calls.map((call) => call.input.scopeKey)).not.toContain(DONETSK);
  });

  it("ignores presentation completion for a stale stateRevision", async () => {
    const presentation = new ControlledPresentation();
    const { controller } = setup({ presentation });
    await startAtWorld(controller);
    const ukrainePresentation = presentation.deferNext(UKRAINE);
    await controller.dispatch({
      type: "enter",
      target: UKRAINE,
      cause: "country-click",
    });
    const ukraineRevision = controller.getSnapshot().stateRevision;
    expect(controller.getSnapshot().visual).toMatchObject({
      phase: "building",
      stateRevision: ukraineRevision,
    });

    await controller.dispatch({
      type: "enter",
      target: POLAND,
      cause: "country-click",
    });
    const polandSnapshot = controller.getSnapshot();
    ukrainePresentation.resolve();
    await Promise.resolve();
    await Promise.resolve();

    expect(controller.getSnapshot()).toBe(polandSnapshot);
    expect(controller.getSnapshot()).toMatchObject({
      current: { key: POLAND },
      visual: { phase: "unavailable", stateRevision: polandSnapshot.stateRevision },
    });
  });

  it("keeps the semantic commit when presentation fails", async () => {
    const presentation = new ControlledPresentation();
    const { controller } = setup({ presentation });
    await startAtWorld(controller);
    const failedPresentation = presentation.deferNext(UKRAINE);

    await expect(controller.dispatch({
      type: "enter",
      target: UKRAINE,
      cause: "country-click",
    })).resolves.toMatchObject({ outcome: "committed" });
    const committedRevision = controller.getSnapshot().stateRevision;
    failedPresentation.reject(new Error("WebGL staging failed"));
    await Promise.resolve();
    await Promise.resolve();

    expect(controller.getSnapshot()).toMatchObject({
      phase: "ready",
      stateRevision: committedRevision,
      current: { key: UKRAINE },
      query: { scopeKey: UKRAINE },
      problem: { code: "PRESENTATION_FAILED" },
      visual: {
        phase: "unavailable",
        stateRevision: committedRevision,
        problem: { code: "PRESENTATION_FAILED" },
      },
    });
  });

  it("caches snapshot identity until the next publication", async () => {
    const { controller } = setup();
    expect(controller.getSnapshot()).toBe(controller.getSnapshot());
    await startAtWorld(controller);
    const ready = controller.getSnapshot();
    expect(controller.getSnapshot()).toBe(ready);
    await controller.dispatch({
      type: "prefetch",
      target: UKRAINE,
      priority: "anticipated",
    });
    expect(controller.getSnapshot()).toBe(ready);
  });
});
