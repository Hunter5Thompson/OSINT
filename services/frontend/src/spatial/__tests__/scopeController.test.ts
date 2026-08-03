import { afterEach, describe, expect, it } from "vitest";
import fixtureText from "./fixtures/spatial-contract-v1.json?raw";
import {
  HYDRATING_SPATIAL_SCOPE_SNAPSHOT,
  WORLD_SCOPE_KEY,
  parseScopeKeyCandidate,
  type ResolvedPresentationInput,
  type ScopeKey,
} from "../contracts";
import { MemorySpatialCatalog } from "../catalog";
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
