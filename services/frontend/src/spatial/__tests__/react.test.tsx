import { StrictMode, type ReactNode } from "react";
import { act, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import fixtureText from "./fixtures/spatial-contract-v1.json?raw";
import {
  HYDRATING_SPATIAL_SCOPE_SNAPSHOT,
  WORLD_SCOPE_KEY,
  parseScopeKeyCandidate,
  type OwnedSpatialScopeModule,
  type ScopeLocationEvent,
  type ScopeNavigationPort,
  type ScopeNavigationWrite,
  type SpatialScopeHandle,
} from "../contracts";
import { MemorySpatialCatalog } from "../catalog";
import { MemoryScopeNavigation } from "../navigation";
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

let latestHandle: SpatialScopeHandle | null = null;

function Probe(): ReactNode {
  latestHandle = useSpatialScope();
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

afterEach(() => {
  latestHandle = null;
});

describe("SpatialScopeProvider gate and hook", () => {
  it("is inert and default-off when VITE_SPATIAL_SCOPE_ENABLED is absent", () => {
    const factory = vi.fn<SpatialScopeModuleFactory>();
    render(
      <MemoryRouter>
        <SpatialScopeProvider
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

    gate.resolve();
    await vi.waitFor(() => expect(latestHandle?.phase).toBe("ready"));
    expect(latestHandle?.enter).toBe(enter);
    expect(latestHandle?.ascend).toBe(ascend);
    expect(latestHandle?.prefetch).toBe(prefetch);
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
});
