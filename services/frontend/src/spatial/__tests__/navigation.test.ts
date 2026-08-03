import { afterEach, describe, expect, it, vi } from "vitest";
import fixtureText from "./fixtures/spatial-contract-v1.json?raw";
import {
  WORLD_SCOPE_KEY,
  parseScopeKeyCandidate,
  type OwnedSpatialScopeModule,
  type ScopeLocationEvent,
} from "../contracts";
import { MemorySpatialCatalog } from "../catalog";
import {
  RouterScopeNavigation,
  ScopeNavigationError,
  type RouterLocationSnapshot,
  type RouterNavigationRequest,
  type ScopeNavigationClock,
} from "../navigation";
import { createSpatialScopeController } from "../scopeController";

interface Fixture {
  readonly catalogRevision: string;
  readonly resolvedScopes: readonly unknown[];
}

interface ScheduledCallback {
  readonly at: number;
  readonly callback: () => void;
}

class FakeClock implements ScopeNavigationClock {
  private now = 0;
  private nextId = 0;
  private readonly scheduled = new Map<number, ScheduledCallback>();

  setTimeout(callback: () => void, delayMs: number): number {
    const id = ++this.nextId;
    this.scheduled.set(id, { at: this.now + delayMs, callback });
    return id;
  }

  clearTimeout(id: number): void {
    this.scheduled.delete(id);
  }

  advance(milliseconds: number): void {
    this.now += milliseconds;
    while (true) {
      const due = [...this.scheduled.entries()]
        .filter(([, value]) => value.at <= this.now)
        .sort((left, right) => left[1].at - right[1].at || left[0] - right[0]);
      const next = due[0];
      if (next === undefined) return;
      this.scheduled.delete(next[0]);
      next[1].callback();
    }
  }
}

const fixture = JSON.parse(fixtureText) as Fixture;
const UKRAINE = parseScopeKeyCandidate("country:UKR");
const POLAND = parseScopeKeyCandidate("country:POL");
const ACTIVE_REVISION = "spatial-v1-001122334455";

function location(
  search = "",
  state: unknown = null,
  pathname = "/worldview",
  hash = "",
): RouterLocationSnapshot {
  return { pathname, search, hash, state };
}

function echo(
  navigation: RouterScopeNavigation,
  request: RouterNavigationRequest,
): void {
  navigation.acceptLocation({
    pathname: request.pathname,
    search: request.search,
    hash: request.hash,
    state: request.state,
  });
}

function makeNavigation(initial = location()) {
  const clock = new FakeClock();
  const requests: RouterNavigationRequest[] = [];
  const navigation = new RouterScopeNavigation({
    initialLocation: initial,
    navigate: (request) => {
      requests.push(request);
    },
    clock,
  });
  return { navigation, requests, clock };
}

const controllers: OwnedSpatialScopeModule[] = [];
const navigations: RouterScopeNavigation[] = [];

afterEach(() => {
  controllers.splice(0).forEach((controller) => controller.stop());
  navigations.splice(0).forEach((navigation) => navigation.dispose());
});

async function waitForScope(
  controller: OwnedSpatialScopeModule,
  scopeKey: string,
  revision?: string,
): Promise<void> {
  await vi.waitFor(() => {
    expect(controller.getSnapshot().query?.scopeKey).toBe(scopeKey);
    if (revision !== undefined) {
      expect(controller.getSnapshot().query?.catalogRevision).toBe(revision);
    }
  });
}

function scopesAtRevision(revision: string): readonly unknown[] {
  return fixture.resolvedScopes.map((value) => {
    const source = JSON.stringify(value);
    const parsed: unknown = JSON.parse(source.replaceAll(fixture.catalogRevision, revision));
    return parsed;
  });
}

describe("RouterScopeNavigation URL and state contract", () => {
  it("uses push versus replace while preserving every foreign URL and state field", async () => {
    const initial = location(
      "?layer=flights&filter=hot&custom=one&custom=two",
      { foreign: { keep: true }, odinSpatialCatalogRevision: "untrusted" },
      "/worldview",
      "#intel",
    );
    const { navigation, requests } = makeNavigation(initial);
    navigations.push(navigation);
    const countryWrite = navigation.writeScope({
      scopeKey: UKRAINE,
      catalogRevision: fixture.catalogRevision,
      mode: "push",
      navigationId: "navigation-country",
    });

    expect(requests).toHaveLength(1);
    expect(requests[0]).toMatchObject({
      pathname: "/worldview",
      hash: "#intel",
      replace: false,
      state: {
        foreign: { keep: true },
        odinSpatialCatalogRevision: fixture.catalogRevision,
        odinSpatialNavigationId: "navigation-country",
      },
    });
    const countrySearch = new URLSearchParams(requests[0]?.search);
    expect(countrySearch.get("scope")).toBe(UKRAINE);
    expect(countrySearch.get("layer")).toBe("flights");
    expect(countrySearch.get("filter")).toBe("hot");
    expect(countrySearch.getAll("custom")).toEqual(["one", "two"]);
    echo(navigation, requests[0] as RouterNavigationRequest);
    await countryWrite;

    const worldWrite = navigation.writeScope({
      scopeKey: null,
      catalogRevision: fixture.catalogRevision,
      mode: "replace",
      navigationId: "navigation-world",
    });
    expect(requests).toHaveLength(2);
    expect(requests[1]?.replace).toBe(true);
    expect(new URLSearchParams(requests[1]?.search).has("scope")).toBe(false);
    expect(requests[1]?.hash).toBe("#intel");
    echo(navigation, requests[1] as RouterNavigationRequest);
    await worldWrite;
  });

  it("validates revision and navigation IDs from untrusted router state", () => {
    const { navigation } = makeNavigation();
    navigations.push(navigation);
    const listener = vi.fn<(event: ScopeLocationEvent) => void>();
    navigation.subscribeLocation(listener);

    navigation.acceptLocation(location("?scope=country%3AUKR", {
      odinSpatialCatalogRevision: "spatial-v1-INVALID",
      odinSpatialNavigationId: "contains spaces",
    }));
    expect(listener).toHaveBeenLastCalledWith({
      scopeCandidate: UKRAINE,
      catalogRevisionCandidate: null,
      navigationId: null,
    });

    navigation.acceptLocation(location("?scope=country%3AUKR", {
      odinSpatialCatalogRevision: fixture.catalogRevision,
      odinSpatialNavigationId: "historical-navigation-1",
    }));
    expect(listener).toHaveBeenLastCalledWith({
      scopeCandidate: UKRAINE,
      catalogRevisionCandidate: fixture.catalogRevision,
      navigationId: "historical-navigation-1",
    });
  });

  it("treats popstate as external input without writing a history echo", () => {
    const { navigation, requests } = makeNavigation();
    navigations.push(navigation);
    const listener = vi.fn();
    navigation.subscribeLocation(listener);

    navigation.acceptLocation(location("?scope=country%3AUKR&layer=firms", {
      odinSpatialCatalogRevision: fixture.catalogRevision,
      odinSpatialNavigationId: "old-entry",
      foreign: "preserved",
    }, "/worldview", "#back"));

    expect(requests).toHaveLength(0);
    expect(listener).toHaveBeenCalledOnce();
  });
});

describe("RouterScopeNavigation serialized echoes", () => {
  it("suppresses a stale timed-out A echo and repairs it to committed B", async () => {
    const { navigation, requests, clock } = makeNavigation();
    navigations.push(navigation);
    const listener = vi.fn();
    navigation.subscribeLocation(listener);
    const writeA = navigation.writeScope({
      scopeKey: UKRAINE,
      catalogRevision: fixture.catalogRevision,
      mode: "push",
      navigationId: "navigation-a",
    });
    const rejectedA = expect(writeA).rejects.toMatchObject({ code: "URL_SYNC_FAILED" });
    const writeB = navigation.writeScope({
      scopeKey: POLAND,
      catalogRevision: fixture.catalogRevision,
      mode: "push",
      navigationId: "navigation-b",
    });
    expect(requests).toHaveLength(1);

    clock.advance(2_000);
    await rejectedA;
    expect(requests).toHaveLength(2);
    echo(navigation, requests[1] as RouterNavigationRequest);
    await writeB;
    listener.mockClear();

    echo(navigation, requests[0] as RouterNavigationRequest);
    expect(listener).not.toHaveBeenCalled();
    expect(requests).toHaveLength(3);
    expect(requests[2]?.replace).toBe(true);
    expect(new URLSearchParams(requests[2]?.search).get("scope")).toBe(POLAND);
  });

  it("suppresses a pending own echo but later reuses the same historical ID", async () => {
    const { navigation, requests } = makeNavigation();
    navigations.push(navigation);
    const catalog = new MemorySpatialCatalog({
      activeCatalogRevision: fixture.catalogRevision,
      resolvedScopes: fixture.resolvedScopes,
    });
    const controller = createSpatialScopeController({
      catalog,
      navigation,
      createNavigationId: () => "reusable-navigation-id",
    });
    controllers.push(controller);
    controller.start();
    await waitForScope(controller, WORLD_SCOPE_KEY);

    const enter = controller.dispatch({
      type: "enter",
      target: UKRAINE,
      cause: "country-click",
    });
    await vi.waitFor(() => expect(requests).toHaveLength(1));
    const historicalCountryEntry = requests[0] as RouterNavigationRequest;
    echo(navigation, historicalCountryEntry);
    await enter;
    expect(catalog.resolveCalls.filter((call) => call.scopeKey === UKRAINE)).toHaveLength(1);

    navigation.acceptLocation(location("", null));
    await waitForScope(controller, WORLD_SCOPE_KEY);
    navigation.acceptLocation({
      pathname: historicalCountryEntry.pathname,
      search: historicalCountryEntry.search,
      hash: historicalCountryEntry.hash,
      state: historicalCountryEntry.state,
    });
    await waitForScope(controller, UKRAINE);
    expect(catalog.resolveCalls.filter((call) => call.scopeKey === UKRAINE)).toHaveLength(2);
    expect(requests).toHaveLength(1);
  });

  it("suppresses and repairs an own echo that arrives after lifecycle cancellation", async () => {
    const { navigation, requests } = makeNavigation();
    navigations.push(navigation);
    const listener = vi.fn();
    navigation.subscribeLocation(listener);
    const cancelledWrite = navigation.writeScope({
      scopeKey: UKRAINE,
      catalogRevision: fixture.catalogRevision,
      mode: "push",
      navigationId: "strict-replay-cancelled",
    });
    const cancelled = expect(cancelledWrite).rejects.toMatchObject({ name: "AbortError" });
    navigation.cancelPending();
    await cancelled;

    const committedWrite = navigation.writeScope({
      scopeKey: POLAND,
      catalogRevision: fixture.catalogRevision,
      mode: "push",
      navigationId: "strict-replay-committed",
    });
    echo(navigation, requests[1] as RouterNavigationRequest);
    await committedWrite;
    listener.mockClear();

    echo(navigation, requests[0] as RouterNavigationRequest);
    expect(listener).not.toHaveBeenCalled();
    expect(requests).toHaveLength(3);
    expect(requests[2]?.replace).toBe(true);
    expect(new URLSearchParams(requests[2]?.search).get("scope")).toBe(POLAND);
  });
});

describe("controller and router revision/failure coordination", () => {
  it("replaces an explicit world candidate with the canonical absent parameter", async () => {
    const initial = location("?scope=world&foreign=keep", null);
    const { navigation, requests } = makeNavigation(initial);
    navigations.push(navigation);
    const catalog = new MemorySpatialCatalog({
      activeCatalogRevision: fixture.catalogRevision,
      resolvedScopes: fixture.resolvedScopes,
    });
    const controller = createSpatialScopeController({ catalog, navigation });
    controllers.push(controller);
    controller.start();

    await vi.waitFor(() => expect(requests).toHaveLength(1));
    expect(requests[0]?.replace).toBe(true);
    const parameters = new URLSearchParams(requests[0]?.search);
    expect(parameters.has("scope")).toBe(false);
    expect(parameters.get("foreign")).toBe("keep");
    echo(navigation, requests[0] as RouterNavigationRequest);
    await waitForScope(controller, WORLD_SCOPE_KEY);
  });

  it("replaces a non-canonical historical candidate without duplicating semantic state", async () => {
    const { navigation, requests } = makeNavigation();
    navigations.push(navigation);
    const catalog = new MemorySpatialCatalog({
      activeCatalogRevision: fixture.catalogRevision,
      resolvedScopes: fixture.resolvedScopes,
    });
    const controller = createSpatialScopeController({ catalog, navigation });
    controllers.push(controller);
    controller.start();
    await waitForScope(controller, WORLD_SCOPE_KEY);

    const lowerCaseLocation = location("?scope=country%3Aukr&foreign=keep", null);
    navigation.acceptLocation(lowerCaseLocation);
    await vi.waitFor(() => expect(requests).toHaveLength(1));
    expect(requests[0]?.replace).toBe(true);
    expect(new URLSearchParams(requests[0]?.search).get("scope")).toBe(UKRAINE);
    echo(navigation, requests[0] as RouterNavigationRequest);
    await waitForScope(controller, UKRAINE);

    const stateRevision = controller.getSnapshot().stateRevision;
    navigation.acceptLocation(lowerCaseLocation);
    await vi.waitFor(() => expect(requests).toHaveLength(2));
    echo(navigation, requests[1] as RouterNavigationRequest);
    await vi.waitFor(() => expect(controller.getSnapshot().phase).toBe("ready"));

    expect(controller.getSnapshot().stateRevision).toBe(stateRevision);
    expect(catalog.resolveCalls.filter((call) => call.scopeKey === UKRAINE)).toHaveLength(1);
  });

  it("uses active revision on reload but the validated pinned revision on Back", async () => {
    const initial = location("?scope=country%3AUKR", {
      odinSpatialCatalogRevision: fixture.catalogRevision,
      odinSpatialNavigationId: "old-reload-state",
    });
    const { navigation, requests } = makeNavigation(initial);
    navigations.push(navigation);
    const catalog = new MemorySpatialCatalog({
      activeCatalogRevision: ACTIVE_REVISION,
      resolvedScopes: [
        ...fixture.resolvedScopes,
        ...scopesAtRevision(ACTIVE_REVISION),
      ],
    });
    const controller = createSpatialScopeController({ catalog, navigation });
    controllers.push(controller);
    controller.start();
    await waitForScope(controller, UKRAINE, ACTIVE_REVISION);

    navigation.acceptLocation(location("", null));
    await waitForScope(controller, WORLD_SCOPE_KEY, ACTIVE_REVISION);
    navigation.acceptLocation(initial);
    await waitForScope(controller, UKRAINE, fixture.catalogRevision);
    expect(requests).toHaveLength(0);
  });

  it("repairs an unresolvable historical URL to the committed scope", async () => {
    const { navigation, requests } = makeNavigation();
    navigations.push(navigation);
    const catalog = new MemorySpatialCatalog({
      activeCatalogRevision: fixture.catalogRevision,
      resolvedScopes: fixture.resolvedScopes,
    });
    const controller = createSpatialScopeController({ catalog, navigation });
    controllers.push(controller);
    controller.start();
    await waitForScope(controller, WORLD_SCOPE_KEY);

    navigation.acceptLocation(location("?scope=country%3ADEU&foreign=keep", {
      odinSpatialCatalogRevision: fixture.catalogRevision,
      odinSpatialNavigationId: "historical-unknown",
    }, "/worldview", "#history"));
    await vi.waitFor(() => expect(requests).toHaveLength(1));
    const repair = requests[0] as RouterNavigationRequest;
    expect(repair.replace).toBe(true);
    expect(new URLSearchParams(repair.search).has("scope")).toBe(false);
    expect(new URLSearchParams(repair.search).get("foreign")).toBe("keep");
    expect(repair.hash).toBe("#history");
    echo(navigation, repair);

    await vi.waitFor(() => {
      expect(controller.getSnapshot()).toMatchObject({
        phase: "ready",
        current: { key: WORLD_SCOPE_KEY },
        problem: { code: "UNKNOWN_SCOPE", target: "country:DEU" },
      });
    });
  });

  it("repairs a lexically invalid historical URL without a semantic revision", async () => {
    const { navigation, requests } = makeNavigation();
    navigations.push(navigation);
    const catalog = new MemorySpatialCatalog({
      activeCatalogRevision: fixture.catalogRevision,
      resolvedScopes: fixture.resolvedScopes,
    });
    const controller = createSpatialScopeController({ catalog, navigation });
    controllers.push(controller);
    controller.start();
    await waitForScope(controller, WORLD_SCOPE_KEY);
    const stateRevision = controller.getSnapshot().stateRevision;

    navigation.acceptLocation(location("?scope=country%2FUKR&foreign=keep", null));
    await vi.waitFor(() => expect(requests).toHaveLength(1));
    echo(navigation, requests[0] as RouterNavigationRequest);
    await vi.waitFor(() => {
      expect(controller.getSnapshot().problem?.code).toBe("INVALID_SCOPE_KEY");
    });
    expect(controller.getSnapshot().stateRevision).toBe(stateRevision);
    expect(controller.getSnapshot().current?.key).toBe(WORLD_SCOPE_KEY);
  });

  it("repairs an invalid initial link to world and keeps a visible input problem", async () => {
    const initial = location(
      "?scope=country%2FUKR&layer=flights&foreign=keep",
      { foreignState: 7 },
      "/worldview",
      "#intel",
    );
    const { navigation, requests } = makeNavigation(initial);
    navigations.push(navigation);
    const catalog = new MemorySpatialCatalog({
      activeCatalogRevision: fixture.catalogRevision,
      resolvedScopes: fixture.resolvedScopes,
    });
    const controller = createSpatialScopeController({ catalog, navigation });
    controllers.push(controller);
    controller.start();

    await vi.waitFor(() => expect(requests).toHaveLength(1));
    const repair = requests[0] as RouterNavigationRequest;
    expect(repair.replace).toBe(true);
    const search = new URLSearchParams(repair.search);
    expect(search.has("scope")).toBe(false);
    expect(search.get("layer")).toBe("flights");
    expect(search.get("foreign")).toBe("keep");
    expect(repair.hash).toBe("#intel");
    expect(repair.state).toMatchObject({ foreignState: 7 });
    echo(navigation, repair);
    await waitForScope(controller, WORLD_SCOPE_KEY);
    expect(controller.getSnapshot().problem).toMatchObject({ code: "INVALID_SCOPE_KEY" });
  });

  it("fails closed after two seconds and commits only after explicit retry", async () => {
    const { navigation, requests, clock } = makeNavigation();
    navigations.push(navigation);
    const catalog = new MemorySpatialCatalog({
      activeCatalogRevision: fixture.catalogRevision,
      resolvedScopes: fixture.resolvedScopes,
    });
    let navigationId = 0;
    const controller = createSpatialScopeController({
      catalog,
      navigation,
      createNavigationId: () => `timeout-navigation-${++navigationId}`,
    });
    controllers.push(controller);
    controller.start();
    await waitForScope(controller, WORLD_SCOPE_KEY);

    const first = controller.dispatch({
      type: "enter",
      target: UKRAINE,
      cause: "country-click",
    });
    await vi.waitFor(() => expect(requests).toHaveLength(1));
    clock.advance(2_000);
    await expect(first).resolves.toMatchObject({
      outcome: "failed",
      problem: { code: "URL_SYNC_FAILED" },
    });
    expect(controller.getSnapshot()).toMatchObject({
      current: { key: WORLD_SCOPE_KEY },
      problem: { code: "URL_SYNC_FAILED" },
    });

    const retry = controller.dispatch({
      type: "enter",
      target: UKRAINE,
      cause: "country-click",
    });
    await vi.waitFor(() => expect(requests).toHaveLength(2));
    echo(navigation, requests[1] as RouterNavigationRequest);
    await expect(retry).resolves.toMatchObject({ outcome: "committed" });
    expect(controller.getSnapshot().current?.key).toBe(UKRAINE);
  });

  it("exposes URL_SYNC_FAILED as a typed navigation problem", () => {
    const error = new ScopeNavigationError({
      target: UKRAINE,
      message: "Router echo timed out.",
    });
    expect(error).toMatchObject({
      code: "URL_SYNC_FAILED",
      target: UKRAINE,
      recoverable: true,
    });
  });
});
