import { act, fireEvent, render, renderHook, screen } from "@testing-library/react";
import { StrictMode, useState, type ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import fixtureText from "./fixtures/spatial-contract-v1.json?raw";

import { SpotlightProvider, useSpotlight } from
  "../../components/globe/spotlight/SpotlightContext";
import { MemorySpatialCatalog } from "../catalog";
import {
  WORLD_SCOPE_KEY,
  freezeSpatialScopeSnapshot,
  parseCatalogRevision,
  parseScopeKeyCandidate,
  type OwnedSpatialScopeModule,
  type ResolvedPresentationInput,
  type ScopeKey,
  type SpatialScopeCommand,
  type SpatialScopeResult,
  type SpatialScopeSnapshot,
} from "../contracts";
import { MemoryScopeNavigation } from "../navigation";
import {
  SpatialScopeProvider,
} from "../react";
import {
  commitSpatialChildSelection,
  createSelectionEnvelope,
  openSpatialChild,
  selectionForScopeRevision,
} from "../selection";
import { SpatialScopeBreadcrumb } from "../SpatialScopeBreadcrumb";
import { WorldviewKeyboardCoordinator } from "../WorldviewKeyboardCoordinator";
import { MutuallyExclusiveCountryPath } from "../WorldviewCountryPath";
import {
  CesiumSpatialPresentationBridge,
  type AttachedSpatialPresenter,
} from "../cesium/SpatialPresentationBridge";
import { SpatialScopeViewerBridge } from "../cesium/SpatialScopeViewerBridge";
import { classifyWorldviewHit } from "../../components/globe/EntityClickHandler";
import { useCountryHitTest } from "../../components/globe/hooks/useCountryHitTest";

interface Fixture {
  readonly catalogRevision: string;
  readonly resolvedScopes: readonly unknown[];
}

const fixture = JSON.parse(fixtureText) as Fixture;
const revision = parseCatalogRevision(fixture.catalogRevision);
const ukraine = parseScopeKeyCandidate("country:UKR");

function worldSummary() {
  return {
    key: WORLD_SCOPE_KEY,
    kind: "world" as const,
    label: "World",
    shortLabel: "World",
    parentKey: null,
    childrenAvailable: true,
    presentation: "boundary" as const,
  };
}

function ukraineSummary() {
  return {
    key: ukraine,
    kind: "country" as const,
    label: "Ukraine",
    shortLabel: "Ukraine",
    parentKey: WORLD_SCOPE_KEY,
    childrenAvailable: true,
    presentation: "boundary" as const,
  };
}

function readySnapshot(
  current: "world" | "ukraine" = "ukraine",
  pending: ScopeKey | null = null,
): SpatialScopeSnapshot {
  const summary = current === "world" ? worldSummary() : ukraineSummary();
  const path = current === "world"
    ? [worldSummary()] as const
    : [worldSummary(), ukraineSummary()] as const;
  return freezeSpatialScopeSnapshot({
    phase: pending === null ? "ready" : "resolving",
    stateRevision: current === "world" ? 1 : 2,
    current: summary,
    path,
    query: {
      schemaVersion: 1,
      scopeKey: summary.key,
      catalogRevision: revision,
      boundaryPolicy: "odin-reference-v1",
    },
    pending,
    problem: null,
    visual: {
      phase: "ready",
      stateRevision: current === "world" ? 1 : 2,
    },
  });
}

class InteractiveModule implements OwnedSpatialScopeModule {
  readonly commands: SpatialScopeCommand[] = [];
  private readonly listeners = new Set<() => void>();

  constructor(private snapshot: SpatialScopeSnapshot) {}

  getSnapshot = () => this.snapshot;

  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  dispatch: OwnedSpatialScopeModule["dispatch"] = async (command) => {
    this.commands.push(command);
    if (command.type === "enter" && command.target === WORLD_SCOPE_KEY) {
      this.snapshot = readySnapshot("world");
      this.listeners.forEach((listener) => listener());
      return { outcome: "committed", snapshot: this.snapshot };
    }
    return { outcome: "unchanged", snapshot: this.snapshot };
  };

  start(): void {}
  stop(): void {}
}

function catalog(): MemorySpatialCatalog {
  return new MemorySpatialCatalog({
    activeCatalogRevision: fixture.catalogRevision,
    resolvedScopes: fixture.resolvedScopes,
  });
}

function ScopeHarness({
  module,
  children,
}: {
  readonly module: InteractiveModule;
  readonly children: ReactNode;
}) {
  return (
    <MemoryRouter>
      <SpatialScopeProvider
        enabled
        catalog={catalog()}
        navigation={new MemoryScopeNavigation()}
        moduleFactory={() => module}
      >
        {children}
      </SpatialScopeProvider>
    </MemoryRouter>
  );
}

describe("MutuallyExclusiveCountryPath", () => {
  it("mounts exactly the legacy pair flag-off and the spatial pair flag-on", () => {
    const view = render(
      <MutuallyExclusiveCountryPath
        spatialEnabled={false}
        legacyRenderer={<div data-testid="legacy-renderer" />}
        legacyClickHandler={<div data-testid="legacy-click" />}
        spatialRenderer={<div data-testid="spatial-renderer" />}
        spatialClickHandler={<div data-testid="spatial-click" />}
      />,
    );
    expect(screen.getByTestId("legacy-renderer")).toBeInTheDocument();
    expect(screen.getByTestId("legacy-click")).toBeInTheDocument();
    expect(screen.queryByTestId("spatial-renderer")).toBeNull();
    expect(screen.queryByTestId("spatial-click")).toBeNull();

    view.rerender(
      <MutuallyExclusiveCountryPath
        spatialEnabled
        legacyRenderer={<div data-testid="legacy-renderer" />}
        legacyClickHandler={<div data-testid="legacy-click" />}
        spatialRenderer={<div data-testid="spatial-renderer" />}
        spatialClickHandler={<div data-testid="spatial-click" />}
      />,
    );
    expect(screen.queryByTestId("legacy-renderer")).toBeNull();
    expect(screen.queryByTestId("legacy-click")).toBeNull();
    expect(screen.getByTestId("spatial-renderer")).toBeInTheDocument();
    expect(screen.getByTestId("spatial-click")).toBeInTheDocument();
  });

  it("does not load the Legacy country index for the Spatial click path", () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    renderHook(() => useCountryHitTest(false));
    expect(fetchSpy).not.toHaveBeenCalled();
    fetchSpy.mockRestore();
  });
});

describe("spatial selection policy", () => {
  it("creates a separate canonical country selection only after commit", async () => {
    const committed = vi.fn<() => Promise<SpatialScopeResult>>().mockResolvedValue({
      outcome: "committed",
      snapshot: readySnapshot("ukraine"),
    });
    const failed = vi.fn<() => Promise<SpatialScopeResult>>().mockResolvedValue({
      outcome: "failed",
      problem: {
        severity: "error",
        code: "UNKNOWN_SCOPE",
        target: ukraine,
        recoverable: false,
        message: "missing",
        activeCatalogRevision: null,
      },
    });

    await expect(commitSpatialChildSelection(ukraine, committed)).resolves.toEqual({
      scopeKey: ukraine,
      label: "Ukraine",
    });
    await expect(commitSpatialChildSelection(ukraine, failed)).resolves.toBeNull();
  });

  it("changes selection and Spotlight only after an explicit successful commit", async () => {
    const select = vi.fn();
    const clearCircle = vi.fn();
    const failed = vi.fn<() => Promise<SpatialScopeResult>>().mockResolvedValue({
      outcome: "failed",
      problem: {
        severity: "error",
        code: "UNKNOWN_SCOPE",
        target: ukraine,
        recoverable: false,
        message: "missing",
        activeCatalogRevision: null,
      },
    });

    await expect(openSpatialChild(ukraine, failed, select, clearCircle)).resolves.toBe(false);
    expect(select).not.toHaveBeenCalled();
    expect(clearCircle).not.toHaveBeenCalled();

    await expect(openSpatialChild(
      ukraine,
      () => Promise.resolve({ outcome: "committed", snapshot: readySnapshot("ukraine") }),
      select,
      clearCircle,
    )).resolves.toBe(true);
    expect(select).toHaveBeenCalledWith({ scopeKey: ukraine, label: "Ukraine" });
    expect(clearCircle).toHaveBeenCalledOnce();

    select.mockClear();
    clearCircle.mockClear();
    await expect(openSpatialChild(
      WORLD_SCOPE_KEY,
      () => Promise.resolve({ outcome: "committed", snapshot: readySnapshot("world") }),
      select,
      clearCircle,
    )).resolves.toBe(true);
    expect(select).toHaveBeenCalledWith(null);
    expect(clearCircle).toHaveBeenCalledOnce();
  });

  it("hides an old operational envelope on the first new revision render", () => {
    const operational = createSelectionEnvelope({ type: "event", id: "evt-1" }, 4);
    const country = createSelectionEnvelope(
      { scopeKey: ukraine, label: "Ukraine" },
      4,
      ukraine,
    );

    expect(selectionForScopeRevision(operational, 4, WORLD_SCOPE_KEY)).toEqual({
      type: "event",
      id: "evt-1",
    });
    expect(selectionForScopeRevision(operational, 5, ukraine)).toBeNull();
    expect(selectionForScopeRevision(country, 5, ukraine)).toEqual({
      scopeKey: ukraine,
      label: "Ukraine",
    });
    expect(selectionForScopeRevision(country, 5, WORLD_SCOPE_KEY)).toBeNull();
  });
});

describe("WorldView pick classification", () => {
  it("never classifies a Spatial child surface as an operational primitive", () => {
    const child = {
      id: {
        odinKind: "spatial-child",
        scopeKey: ukraine,
        stateRevision: 2,
      },
    };
    expect(classifyWorldviewHit(child, null)).toBeNull();
    expect(classifyWorldviewHit({ primitive: { _eventData: { id: "evt-1" } } }, null))
      .toBe("operational");
  });
});

describe("SpatialScopeBreadcrumb", () => {
  it("is semantic, keyboard-native, and retains focus after an ancestor commit", async () => {
    const module = new InteractiveModule(readySnapshot("ukraine"));
    render(
      <ScopeHarness module={module}>
        <SpatialScopeBreadcrumb />
      </ScopeHarness>,
    );

    const nav = screen.getByRole("navigation", { name: "Spatial scope" });
    expect(nav).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Ukraine" })).toHaveAttribute(
      "aria-current",
      "location",
    );
    const worldButton = screen.getByRole("button", { name: "World" });
    worldButton.focus();
    fireEvent.click(worldButton);

    await screen.findByRole("button", { name: "World" });
    expect(module.commands[0]).toEqual({
      type: "enter",
      target: WORLD_SCOPE_KEY,
      cause: "breadcrumb",
    });
    expect(document.activeElement).toBe(worldButton);
    expect(worldButton).toHaveAttribute("aria-current", "location");
  });

  it("shows pending truth and offers a separate semantic ascend action", () => {
    const pending = parseScopeKeyCandidate("admin1:iso3166-2:UA-14");
    const module = new InteractiveModule(readySnapshot("ukraine", pending));
    render(
      <ScopeHarness module={module}>
        <SpatialScopeBreadcrumb />
      </ScopeHarness>,
    );
    expect(screen.getByText(/Opening admin1:iso3166-2:UA-14/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Eine Ebene hoch" }));
    expect(module.commands.at(-1)).toEqual({ type: "ascend", cause: "breadcrumb" });
  });
});

function SpotlightProbe() {
  const { focusTarget, dispatch } = useSpotlight();
  return (
    <>
      <button
        type="button"
        onClick={() => dispatch({
          type: "set",
          target: {
            kind: "circle",
            trigger: "pin",
            center: { lon: 1, lat: 1 },
            radius: 1,
            altitude: 0,
            label: "pin",
          },
        })}
      >
        Set circle
      </button>
      <output data-testid="spotlight-kind">{focusTarget?.kind ?? "none"}</output>
    </>
  );
}

function KeyboardHarness({ module }: { readonly module: InteractiveModule }) {
  const [hasTransientSelection, setHasTransientSelection] = useState(true);
  return (
    <SpotlightProvider>
      <ScopeHarness module={module}>
        <button
          type="button"
          onClick={() => setHasTransientSelection(false)}
        >
          Clear test selection
        </button>
        <SpotlightProbe />
        <WorldviewKeyboardCoordinator
          hasTransientSelection={hasTransientSelection}
          clearTransientSelection={() => setHasTransientSelection(false)}
        />
        <output data-testid="selection-state">
          {hasTransientSelection ? "selected" : "clear"}
        </output>
      </ScopeHarness>
    </SpotlightProvider>
  );
}

describe("WorldviewKeyboardCoordinator", () => {
  it("executes exactly one priority-ordered Escape action", () => {
    const pending = parseScopeKeyCandidate("admin1:iso3166-2:UA-14");
    const module = new InteractiveModule(readySnapshot("ukraine", pending));
    render(<KeyboardHarness module={module} />);
    fireEvent.click(screen.getByRole("button", { name: "Set circle" }));

    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.getByTestId("selection-state")).toHaveTextContent("clear");
    expect(screen.getByTestId("spotlight-kind")).toHaveTextContent("circle");
    expect(module.commands).toHaveLength(0);

    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.getByTestId("spotlight-kind")).toHaveTextContent("none");
    expect(module.commands).toHaveLength(0);

    fireEvent.keyDown(window, { key: "Escape" });
    expect(module.commands).toEqual([{ type: "cancel-pending" }]);
  });

  it("ascends only when no transient action or pending resolve exists", () => {
    const module = new InteractiveModule(readySnapshot("ukraine"));
    render(
      <SpotlightProvider>
        <ScopeHarness module={module}>
          <WorldviewKeyboardCoordinator
            hasTransientSelection={false}
            clearTransientSelection={() => undefined}
          />
        </ScopeHarness>
      </SpotlightProvider>,
    );
    fireEvent.keyDown(window, { key: "Escape" });
    expect(module.commands).toEqual([{ type: "ascend", cause: "keyboard" }]);
  });
});

describe("CesiumSpatialPresentationBridge", () => {
  const input = fixture.resolvedScopes[0] as {
    readonly presentation: ResolvedPresentationInput;
  };

  it("waits for the Viewer, delegates once, and disposes on detach", async () => {
    const presenter: AttachedSpatialPresenter = {
      present: vi.fn(() => Promise.resolve()),
      dispose: vi.fn(),
      diagnostics: () => ({
        activeContainers: 1,
        buildChunks: 7,
        cameraListeners: 1,
        disposed: false,
        highWaterContainers: 2,
        highWaterPrimitives: 4,
        maxBuildChunkDurationMs: 8,
        over50MsBuildChunks: 0,
        postRenderChecks: 1,
        postRenderWaiters: 0,
        primitiveCount: 2,
        readyPrimitiveCount: 2,
        stagingContainers: 0,
      }),
    };
    const bridge = new CesiumSpatialPresentationBridge({
      createPresenter: () => presenter,
    });
    const pending = bridge.present(
      input.presentation,
      1,
      new AbortController().signal,
    );
    let settled = false;
    void pending.then(() => { settled = true; });
    await act(async () => Promise.resolve());
    expect(settled).toBe(false);
    expect(bridge.diagnostics()).toMatchObject({
      attached: false,
      waitingPresentations: 1,
      presenter: null,
    });

    const viewer = { isDestroyed: () => false };
    bridge.attachViewer(viewer);
    await pending;
    expect(presenter.present).toHaveBeenCalledOnce();
    expect(bridge.diagnostics()).toMatchObject({
      attached: true,
      waitingPresentations: 0,
      presenter: { primitiveCount: 2, stagingContainers: 0 },
    });

    bridge.detachViewer(viewer);
    expect(presenter.dispose).toHaveBeenCalledOnce();
    expect(bridge.diagnostics()).toMatchObject({ attached: false, presenter: null });
  });

  it("aborts a pre-Viewer presentation without invoking an adapter", async () => {
    const createPresenter = vi.fn<() => AttachedSpatialPresenter>();
    const bridge = new CesiumSpatialPresentationBridge({ createPresenter });
    const controller = new AbortController();
    const pending = bridge.present(input.presentation, 1, controller.signal);
    controller.abort();

    await expect(pending).rejects.toMatchObject({ name: "AbortError" });
    expect(createPresenter).not.toHaveBeenCalled();
  });

  it("attaches one Viewer adapter through StrictMode and detaches it on unmount", () => {
    const viewer = { isDestroyed: () => false };
    const bridge = {
      attachViewer: vi.fn(),
      detachViewer: vi.fn(),
    };
    const view = render(
      <StrictMode>
        <SpatialScopeViewerBridge viewer={viewer} bridge={bridge} />
      </StrictMode>,
    );

    expect(bridge.attachViewer).toHaveBeenCalledTimes(2);
    expect(bridge.detachViewer).toHaveBeenCalledTimes(1);
    view.unmount();
    expect(bridge.detachViewer).toHaveBeenCalledTimes(2);
  });
});
