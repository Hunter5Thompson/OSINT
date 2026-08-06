import { StrictMode, type ReactNode } from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, useLocation, useNavigationType } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import fixtureText from "./fixtures/spatial-contract-v1.json?raw";
import {
  HYDRATING_SPATIAL_SCOPE_SNAPSHOT,
  WORLD_SCOPE_KEY,
  freezeSpatialScopeSnapshot,
  parseCatalogRevision,
  parseScopeKeyCandidate,
  type OwnedSpatialScopeModule,
  type ScopeLocationEvent,
  type ScopeNavigationPort,
  type ScopeNavigationWrite,
  type SpatialScopeCommand,
  type SpatialScopeHandle,
  type SpatialScopeSnapshot,
} from "../contracts";
import { MemorySpatialCatalog } from "../catalog";
import {
  MemoryScopeNavigation,
  RouterScopeNavigation,
  type RouterLocationSnapshot,
} from "../navigation";
import {
  SpatialScopeProvider,
  useSpatialScope,
  type SpatialScopeModuleFactory,
} from "../react";

interface Fixture {
  readonly catalogRevision: string;
  readonly resolvedScopes: readonly unknown[];
}

const fixture = JSON.parse(fixtureText) as Fixture;
const UKRAINE = parseScopeKeyCandidate("country:UKR");
const KOSOVO = parseScopeKeyCandidate("country:odin:kosovo");

class CountingNavigation implements ScopeNavigationPort {
  readonly listeners = new Set<(event: ScopeLocationEvent) => void>();
  readonly writes: ScopeNavigationWrite[] = [];
  subscribeCalls = 0;
  unsubscribeCalls = 0;

  readScopeCandidate(): string | null {
    return null;
  }

  writeScope(write: ScopeNavigationWrite): Promise<void> {
    this.writes.push(write);
    const event = {
      scopeCandidate: write.scopeKey,
      catalogRevisionCandidate: write.catalogRevision,
      navigationId: write.navigationId,
    } satisfies ScopeLocationEvent;
    this.listeners.forEach((listener) => listener(event));
    return Promise.resolve();
  }

  subscribeLocation(listener: (event: ScopeLocationEvent) => void): () => void {
    this.subscribeCalls += 1;
    this.listeners.add(listener);
    return () => {
      this.unsubscribeCalls += 1;
      this.listeners.delete(listener);
    };
  }
}

class LifecycleModule implements OwnedSpatialScopeModule {
  readonly calls: string[] = [];

  getSnapshot = () => HYDRATING_SPATIAL_SCOPE_SNAPSHOT;

  subscribe = (_listener: () => void) => () => undefined;

  dispatch: OwnedSpatialScopeModule["dispatch"] = async () => ({
    outcome: "unchanged",
    snapshot: HYDRATING_SPATIAL_SCOPE_SNAPSHOT,
  });

  start(): void {
    this.calls.push("start");
  }

  stop(): void {
    this.calls.push("stop");
  }
}

class RecoveryModule implements OwnedSpatialScopeModule {
  readonly commands: SpatialScopeCommand[] = [];
  private readonly snapshot: SpatialScopeSnapshot = freezeSpatialScopeSnapshot({
    phase: "ready",
    stateRevision: 1,
    current: {
      key: UKRAINE,
      kind: "country",
      label: "Ukraine",
      shortLabel: "Ukraine",
      parentKey: WORLD_SCOPE_KEY,
      childrenAvailable: true,
      presentation: "boundary",
    },
    path: [
      {
        key: WORLD_SCOPE_KEY,
        kind: "world",
        label: "World",
        shortLabel: "World",
        parentKey: null,
        childrenAvailable: true,
        presentation: "boundary",
      },
      {
        key: UKRAINE,
        kind: "country",
        label: "Ukraine",
        shortLabel: "Ukraine",
        parentKey: WORLD_SCOPE_KEY,
        childrenAvailable: true,
        presentation: "boundary",
      },
    ],
    query: {
      schemaVersion: 1,
      scopeKey: UKRAINE,
      catalogRevision: parseCatalogRevision("spatial-v1-001122334455"),
      boundaryPolicy: "odin-reference-v1",
    },
    pending: null,
    problem: {
      severity: "error",
      code: "CATALOG_REVISION_UNAVAILABLE",
      target: "spatial-v1-001122334455",
      recoverable: true,
      message: "The pinned catalog revision is no longer served.",
      activeCatalogRevision: parseCatalogRevision(fixture.catalogRevision),
    },
    visual: { phase: "ready", stateRevision: 1 },
  });

  getSnapshot = () => this.snapshot;

  subscribe = (_listener: () => void) => () => undefined;

  dispatch: OwnedSpatialScopeModule["dispatch"] = async (command) => {
    this.commands.push(command);
    return { outcome: "unchanged", snapshot: this.snapshot };
  };

  start(): void {
    // Static test store.
  }

  stop(): void {
    // Static test store.
  }
}

let latestHandle: SpatialScopeHandle | null = null;
let latestLocation: RouterLocationSnapshot | null = null;
let latestNavigationType: ReturnType<typeof useNavigationType> | null = null;
let renderLog: string[] = [];

function Probe(): ReactNode {
  latestHandle = useSpatialScope();
  return <div data-testid="scope-phase">{latestHandle.phase}</div>;
}

function RouterProbe(): ReactNode {
  latestHandle = useSpatialScope();
  const location = useLocation();
  latestLocation = {
    pathname: location.pathname,
    search: location.search,
    hash: location.hash,
    state: location.state as unknown,
  };
  latestNavigationType = useNavigationType();
  renderLog.push(`${latestHandle.phase}:${latestHandle.pending ?? "none"}`);
  return <div data-testid="scope-phase">{latestHandle.phase}</div>;
}

function OutsideProbe(): ReactNode {
  useSpatialScope();
  return null;
}

function catalog(): MemorySpatialCatalog {
  return new MemorySpatialCatalog({
    activeCatalogRevision: fixture.catalogRevision,
    resolvedScopes: fixture.resolvedScopes,
  });
}

function catalogWithKosovo(): MemorySpatialCatalog {
  const ukraine = fixture.resolvedScopes[1];
  const kosovo: unknown = JSON.parse(
    JSON.stringify(ukraine)
      .replaceAll("country:UKR", "country:odin:kosovo")
      .replaceAll("Ukraine", "Kosovo"),
  );
  return new MemorySpatialCatalog({
    activeCatalogRevision: fixture.catalogRevision,
    resolvedScopes: [...fixture.resolvedScopes, kosovo],
  });
}

afterEach(() => {
  latestHandle = null;
  latestLocation = null;
  latestNavigationType = null;
  renderLog = [];
  vi.restoreAllMocks();
});

describe("SpatialScopeProvider gate and hook", () => {
  it("is inert when explicitly disabled regardless of the build artifact", () => {
    const factory = vi.fn<SpatialScopeModuleFactory>();
    render(
      <MemoryRouter>
        <SpatialScopeProvider
          enabled={false}
          catalog={catalog()}
          navigation={new CountingNavigation()}
          moduleFactory={factory}
        >
          <div data-testid="disabled-child">disabled</div>
        </SpatialScopeProvider>
      </MemoryRouter>,
    );
    expect(screen.getByTestId("disabled-child")).toBeInTheDocument();
    expect(factory).not.toHaveBeenCalled();
  });

  it("throws a programmer error when the hook is used outside the provider", () => {
    expect(() => render(<OutsideProbe />)).toThrow(
      "useSpatialScope must be used inside <SpatialScopeProvider>",
    );
  });

  it("publishes the hydrating singleton and keeps command wrappers stable", async () => {
    const memoryCatalog = catalog();
    const gate = memoryCatalog.deferNextResolve(WORLD_SCOPE_KEY);
    render(
      <MemoryRouter>
        <SpatialScopeProvider
          enabled
          catalog={memoryCatalog}
          navigation={new MemoryScopeNavigation()}
        >
          <Probe />
        </SpatialScopeProvider>
      </MemoryRouter>,
    );
    const hydrating = latestHandle;
    expect(hydrating).toMatchObject(HYDRATING_SPATIAL_SCOPE_SNAPSHOT);
    expect(screen.getByTestId("scope-phase")).toHaveTextContent("hydrating");
    const enter = hydrating?.enter;
    const ascend = hydrating?.ascend;
    const prefetch = hydrating?.prefetch;
    const rehydrate = hydrating?.rehydrate;
    const cancelPending = hydrating?.cancelPending;

    gate.resolve();
    await vi.waitFor(() => expect(latestHandle?.phase).toBe("ready"));
    expect(latestHandle?.enter).toBe(enter);
    expect(latestHandle?.ascend).toBe(ascend);
    expect(latestHandle?.prefetch).toBe(prefetch);
    expect(latestHandle?.rehydrate).toBe(rehydrate);
    expect(latestHandle?.cancelPending).toBe(cancelPending);
  });

  it("renders exactly one explicit 409 recovery action", async () => {
    const recoveryModule = new RecoveryModule();
    render(
      <MemoryRouter>
        <SpatialScopeProvider
          enabled
          catalog={catalog()}
          navigation={new CountingNavigation()}
          moduleFactory={() => recoveryModule}
        >
          <Probe />
        </SpatialScopeProvider>
      </MemoryRouter>,
    );

    const actions = screen.getAllByRole("button", {
      name: "Aktiven Kartenstand laden",
    });
    expect(actions).toHaveLength(1);
    fireEvent.click(actions[0] as HTMLButtonElement);

    await vi.waitFor(() => {
      expect(recoveryModule.commands).toEqual([{ type: "rehydrate" }]);
    });
  });
});

describe("SpatialScopeProvider lifecycle", () => {
  it("instantiates one module and replays start-stop-start in StrictMode", async () => {
    const lifecycle = new LifecycleModule();
    const factory = vi.fn<SpatialScopeModuleFactory>(() => lifecycle);
    const view = render(
      <StrictMode>
        <MemoryRouter>
          <SpatialScopeProvider
            enabled
            catalog={catalog()}
            navigation={new CountingNavigation()}
            moduleFactory={factory}
          >
            <Probe />
          </SpatialScopeProvider>
        </MemoryRouter>
      </StrictMode>,
    );

    await vi.waitFor(() => expect(lifecycle.calls).toEqual(["start", "stop", "start"]));
    expect(factory).toHaveBeenCalledOnce();
    view.unmount();
    expect(lifecycle.calls).toEqual(["start", "stop", "start", "stop"]);
  });

  it("keeps one live router subscription, resolves once, and aborts all work on cleanup", async () => {
    const memoryCatalog = catalog();
    const navigation = new CountingNavigation();
    const view = render(
      <StrictMode>
        <MemoryRouter>
          <SpatialScopeProvider enabled catalog={memoryCatalog} navigation={navigation}>
            <Probe />
          </SpatialScopeProvider>
        </MemoryRouter>
      </StrictMode>,
    );
    await vi.waitFor(() => expect(latestHandle?.query?.scopeKey).toBe(WORLD_SCOPE_KEY));
    expect(navigation.listeners.size).toBe(1);
    expect(memoryCatalog.resolveCalls.filter((call) => call.scopeKey === WORLD_SCOPE_KEY)).toHaveLength(1);

    const gate = memoryCatalog.deferNextResolve(UKRAINE);
    let pending: ReturnType<SpatialScopeHandle["enter"]> | null = null;
    act(() => {
      pending = latestHandle?.enter(UKRAINE, "country-click") ?? null;
    });
    await vi.waitFor(() => {
      expect(memoryCatalog.resolveCalls.filter((call) => call.scopeKey === UKRAINE)).toHaveLength(1);
    });
    view.unmount();
    gate.resolve();

    expect(navigation.listeners.size).toBe(0);
    await expect(pending).resolves.toEqual({ outcome: "cancelled" });
  });

  it("disposes a factory-owned catalog only after the final StrictMode cleanup", async () => {
    const ownedCatalog = catalog();
    const dispose = vi.spyOn(ownedCatalog, "dispose");
    const catalogFactory = vi.fn(() => ownedCatalog);
    const view = render(
      <StrictMode>
        <MemoryRouter>
          <SpatialScopeProvider
            enabled
            catalogFactory={catalogFactory}
            navigation={new CountingNavigation()}
          >
            <Probe />
          </SpatialScopeProvider>
        </MemoryRouter>
      </StrictMode>,
    );

    await vi.waitFor(() => expect(latestHandle?.query?.scopeKey).toBe(WORLD_SCOPE_KEY));
    await act(async () => Promise.resolve());
    expect(catalogFactory).toHaveBeenCalledOnce();
    expect(dispose).not.toHaveBeenCalled();

    view.unmount();
    await vi.waitFor(() => expect(dispose).toHaveBeenCalledOnce());
  });

  it("does not dispose a borrowed catalog", async () => {
    const borrowedCatalog = catalog();
    const dispose = vi.spyOn(borrowedCatalog, "dispose");
    const view = render(
      <MemoryRouter>
        <SpatialScopeProvider
          enabled
          catalog={borrowedCatalog}
          navigation={new CountingNavigation()}
        >
          <Probe />
        </SpatialScopeProvider>
      </MemoryRouter>,
    );
    await vi.waitFor(() => expect(latestHandle?.query?.scopeKey).toBe(WORLD_SCOPE_KEY));

    view.unmount();
    await act(async () => Promise.resolve());
    expect(dispose).not.toHaveBeenCalled();
  });

  it("disposes its router coordinator only after the final StrictMode cleanup", async () => {
    const dispose = vi.spyOn(RouterScopeNavigation.prototype, "dispose");
    const view = render(
      <StrictMode>
        <MemoryRouter>
          <SpatialScopeProvider enabled catalog={catalog()}>
            <RouterProbe />
          </SpatialScopeProvider>
        </MemoryRouter>
      </StrictMode>,
    );

    await vi.waitFor(() => expect(latestHandle?.query?.scopeKey).toBe(WORLD_SCOPE_KEY));
    await act(async () => Promise.resolve());
    expect(dispose).not.toHaveBeenCalled();

    view.unmount();
    await vi.waitFor(() => expect(dispose).toHaveBeenCalledOnce());
  });
});

describe("SpatialScopeProvider router composition", () => {
  it("resolves one initial intent and replaces a non-canonical deep link", async () => {
    const memoryCatalog = catalog();
    const gate = memoryCatalog.deferNextResolve(UKRAINE);
    const acceptLocation = vi.spyOn(RouterScopeNavigation.prototype, "acceptLocation");
    render(
      <MemoryRouter
        initialEntries={[{
          pathname: "/worldview",
          search: "?scope=country%3Aukr&layer=flights&foreign=keep",
          hash: "#intel",
          state: { foreignState: 7 },
        }]}
      >
        <SpatialScopeProvider enabled catalog={memoryCatalog}>
          <RouterProbe />
        </SpatialScopeProvider>
      </MemoryRouter>,
    );

    await vi.waitFor(() => {
      expect(memoryCatalog.resolveCalls.filter((call) => call.scopeKey === UKRAINE)).toHaveLength(1);
    });
    expect(acceptLocation).not.toHaveBeenCalled();
    expect(renderLog.filter((value) => value === `hydrating:${UKRAINE}`)).toHaveLength(1);

    act(() => gate.resolve());
    await vi.waitFor(() => expect(latestHandle?.query?.scopeKey).toBe(UKRAINE));

    const parameters = new URLSearchParams(latestLocation?.search ?? "");
    expect(parameters.get("scope")).toBe(UKRAINE);
    expect(parameters.get("layer")).toBe("flights");
    expect(parameters.get("foreign")).toBe("keep");
    expect(latestLocation?.hash).toBe("#intel");
    expect(latestLocation?.state).toMatchObject({ foreignState: 7 });
    expect(latestNavigationType).toBe("REPLACE");
    expect(acceptLocation).toHaveBeenCalledOnce();
  });

  it("resolves the explicit XKX legacy location alias to Kosovo and replaces it", async () => {
    const memoryCatalog = catalogWithKosovo();
    render(
      <MemoryRouter initialEntries={["/worldview?scope=country%3AXKX"]}>
        <SpatialScopeProvider enabled catalog={memoryCatalog}>
          <RouterProbe />
        </SpatialScopeProvider>
      </MemoryRouter>,
    );

    await vi.waitFor(() => expect(latestHandle?.query?.scopeKey).toBe(KOSOVO));
    expect(memoryCatalog.resolveCalls.filter((call) => call.scopeKey === KOSOVO)).toHaveLength(1);
    expect(new URLSearchParams(latestLocation?.search ?? "").get("scope")).toBe(KOSOVO);
    expect(latestNavigationType).toBe("REPLACE");
  });
});
