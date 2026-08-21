import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import { useLocation, useNavigate } from "react-router-dom";
import {
  HYDRATING_SPATIAL_SCOPE_SNAPSHOT,
  freezeSpatialValue,
  type EnterCause,
  type OwnedSpatialScopeModule,
  type ScopeKey,
  type ScopeNavigationPort,
  type SpatialCatalogPort,
  type SpatialScopeHandle,
  type SpatialScopeModule,
} from "./contracts";
import { createBootstrapSpatialCatalog } from "./catalog";
import {
  RouterScopeNavigation,
  type RouterLocationSnapshot,
  type ScopeNavigationClock,
} from "./navigation";
import {
  createSpatialScopeController,
  type CreateSpatialScopeControllerOptions,
  type SpatialScopePresentationPort,
} from "./scopeController";
import type { SpatialContainmentLifecyclePort } from "./containment";

export interface ReactRouterScopeNavigationOptions {
  readonly clock?: ScopeNavigationClock;
}

function routerLocationSnapshot(
  pathname: string,
  search: string,
  hash: string,
  state: unknown,
): RouterLocationSnapshot {
  return { pathname, search, hash, state };
}

export function useReactRouterScopeNavigation(
  options: ReactRouterScopeNavigationOptions = {},
): RouterScopeNavigation {
  const location = useLocation();
  const navigate = useNavigate();
  const navigateRef = useRef(navigate);
  navigateRef.current = navigate;
  const lastAcceptedLocationKeyRef = useRef(location.key);
  const initialLocationRef = useRef<RouterLocationSnapshot | null>(null);
  initialLocationRef.current ??= routerLocationSnapshot(
    location.pathname,
    location.search,
    location.hash,
    location.state as unknown,
  );
  const navigationRef = useRef<RouterScopeNavigation | null>(null);
  navigationRef.current ??= new RouterScopeNavigation({
    initialLocation: initialLocationRef.current,
    navigate: (request) => navigateRef.current(
      {
        pathname: request.pathname,
        search: request.search,
        hash: request.hash,
      },
      { replace: request.replace, state: request.state },
    ),
    clock: options.clock,
  });
  const navigation = navigationRef.current;

  useEffect(() => {
    if (lastAcceptedLocationKeyRef.current === location.key) return;
    lastAcceptedLocationKeyRef.current = location.key;
    navigation.acceptLocation(routerLocationSnapshot(
      location.pathname,
      location.search,
      location.hash,
      location.state as unknown,
    ));
  }, [
    location.hash,
    location.key,
    location.pathname,
    location.search,
    location.state,
    navigation,
  ]);

  const lifecycleGenerationRef = useRef(0);
  useEffect(() => {
    const lifecycleGeneration = ++lifecycleGenerationRef.current;
    return () => {
      queueMicrotask(() => {
        if (lifecycleGenerationRef.current === lifecycleGeneration) {
          navigation.dispose();
        }
      });
    };
  }, [navigation]);

  return navigation;
}

const SpatialScopeContext = createContext<SpatialScopeModule | null>(null);
SpatialScopeContext.displayName = "SpatialScopeContext";

export const SPATIAL_SCOPE_ENABLED =
  import.meta.env.VITE_SPATIAL_SCOPE_ENABLED === "true";

export type SpatialScopeModuleFactory = (
  options: CreateSpatialScopeControllerOptions,
) => OwnedSpatialScopeModule;

export type SpatialCatalogFactory = () => SpatialCatalogPort;

export interface SpatialScopeProviderProps {
  readonly children: ReactNode;
  readonly enabled?: boolean;
  /** Borrowed for the provider lifetime; the caller retains disposal ownership. */
  readonly catalog?: SpatialCatalogPort;
  /** Created once and disposed by the provider after its final cleanup. */
  readonly catalogFactory?: SpatialCatalogFactory;
  readonly navigation?: ScopeNavigationPort;
  readonly presentation?: SpatialScopePresentationPort;
  readonly containment?: SpatialContainmentLifecyclePort;
  readonly moduleFactory?: SpatialScopeModuleFactory;
}

interface ModuleProviderProps extends SpatialScopeProviderProps {
  readonly navigation: ScopeNavigationPort;
  readonly onNavigationCleanup?: () => void;
}

function ModuleProvider({
  children,
  catalog,
  catalogFactory,
  navigation,
  presentation,
  containment,
  moduleFactory = createSpatialScopeController,
  onNavigationCleanup,
}: ModuleProviderProps) {
  if (catalog !== undefined && catalogFactory !== undefined) {
    throw new Error("SpatialScopeProvider accepts catalog or catalogFactory, not both.");
  }
  const catalogSelectionRef = useRef<{
    readonly catalog: SpatialCatalogPort;
    readonly owned: boolean;
    disposed: boolean;
  } | null>(null);
  catalogSelectionRef.current ??= catalog === undefined
    ? {
        catalog: (catalogFactory ?? createBootstrapSpatialCatalog)(),
        owned: true,
        disposed: false,
      }
    : { catalog, owned: false, disposed: false };
  const catalogSelection = catalogSelectionRef.current;
  const moduleRef = useRef<OwnedSpatialScopeModule | null>(null);
  moduleRef.current ??= moduleFactory({
    catalog: catalogSelection.catalog,
    navigation,
    presentation,
    containment,
  });
  const module = moduleRef.current;
  const lifecycleGenerationRef = useRef(0);

  useEffect(() => {
    const lifecycleGeneration = ++lifecycleGenerationRef.current;
    module.start();
    return () => {
      module.stop();
      onNavigationCleanup?.();
      queueMicrotask(() => {
        if (
          lifecycleGenerationRef.current === lifecycleGeneration &&
          catalogSelection.owned &&
          !catalogSelection.disposed
        ) {
          catalogSelection.disposed = true;
          catalogSelection.catalog.dispose();
        }
      });
    };
  }, [catalogSelection, module, onNavigationCleanup]);

  return (
    <SpatialScopeContext.Provider value={module}>
      <SpatialScopeRecoveryAction />
      {children}
    </SpatialScopeContext.Provider>
  );
}

function RouterBackedSpatialScopeProvider(props: SpatialScopeProviderProps) {
  const navigation = useReactRouterScopeNavigation();
  const cleanupNavigation = useCallback(() => navigation.cancelPending(), [navigation]);
  return (
    <ModuleProvider
      {...props}
      navigation={navigation}
      onNavigationCleanup={cleanupNavigation}
    />
  );
}

function InjectedSpatialScopeProvider(
  props: SpatialScopeProviderProps & { readonly navigation: ScopeNavigationPort },
) {
  return <ModuleProvider {...props} navigation={props.navigation} />;
}

export function SpatialScopeProvider(props: SpatialScopeProviderProps) {
  const enabled = props.enabled ?? SPATIAL_SCOPE_ENABLED;
  if (!enabled) return <>{props.children}</>;
  if (props.navigation !== undefined) {
    return <InjectedSpatialScopeProvider {...props} navigation={props.navigation} />;
  }
  return <RouterBackedSpatialScopeProvider {...props} />;
}

function getStableHydratingSnapshot() {
  return HYDRATING_SPATIAL_SCOPE_SNAPSHOT;
}

function useSpatialScopeValue(): SpatialScopeHandle | null {
  const module = useContext(SpatialScopeContext);
  const subscribe = useCallback(
    (listener: () => void) => module?.subscribe(listener) ?? (() => undefined),
    [module],
  );
  const getSnapshot = useCallback(
    () => module?.getSnapshot() ?? HYDRATING_SPATIAL_SCOPE_SNAPSHOT,
    [module],
  );
  const snapshot = useSyncExternalStore(
    subscribe,
    getSnapshot,
    getStableHydratingSnapshot,
  );
  const enter = useCallback(
    (target: ScopeKey, cause: EnterCause) => {
      if (module === null) throw new Error("Spatial scope is unavailable.");
      return module.dispatch({ type: "enter", target, cause });
    },
    [module],
  );
  const ascend = useCallback(
    (cause: "breadcrumb" | "keyboard") => {
      if (module === null) throw new Error("Spatial scope is unavailable.");
      return module.dispatch({ type: "ascend", cause });
    },
    [module],
  );
  const prefetch = useCallback(
    (target: ScopeKey, signal?: AbortSignal) => {
      if (module === null) throw new Error("Spatial scope is unavailable.");
      return module.dispatch(
        { type: "prefetch", target, priority: "hover" },
        { signal },
      );
    },
    [module],
  );
  const cancelPending = useCallback(
    () => {
      if (module === null) throw new Error("Spatial scope is unavailable.");
      return module.dispatch({ type: "cancel-pending" });
    },
    [module],
  );
  const rehydrate = useCallback(
    () => {
      if (module === null) throw new Error("Spatial scope is unavailable.");
      return module.dispatch({ type: "rehydrate" });
    },
    [module],
  );

  return useMemo<SpatialScopeHandle | null>(
    () => module === null
      ? null
      : freezeSpatialValue({
          ...snapshot,
          enter,
          ascend,
          prefetch,
          cancelPending,
          rehydrate,
        }) as SpatialScopeHandle,
    [ascend, cancelPending, enter, module, prefetch, rehydrate, snapshot],
  );
}

export function useOptionalSpatialScope(): SpatialScopeHandle | null {
  return useSpatialScopeValue();
}

export function useSpatialScope(): SpatialScopeHandle {
  const scope = useSpatialScopeValue();
  if (scope === null) {
    throw new Error("useSpatialScope must be used inside <SpatialScopeProvider>");
  }
  return scope;
}

function SpatialScopeRecoveryAction() {
  const scope = useSpatialScope();
  const problem = scope.problem;
  if (
    scope.phase === "hydrating" ||
    problem?.code !== "CATALOG_REVISION_UNAVAILABLE" ||
    problem.activeCatalogRevision === null
  ) {
    return null;
  }
  return (
    <div
      role="alert"
      style={{
        position: "fixed",
        top: 16,
        left: "50%",
        zIndex: 50,
        display: "flex",
        alignItems: "center",
        gap: 12,
        maxWidth: 560,
        padding: "10px 12px",
        border: "1px solid rgba(255, 190, 80, 0.72)",
        background: "rgba(13, 17, 23, 0.94)",
        color: "#f5d7a1",
        fontFamily: "monospace",
        fontSize: 12,
        transform: "translateX(-50%)",
      }}
    >
      <span>
        Kartenstand abgelaufen. Aktive Revision: {problem.activeCatalogRevision}
      </span>
      <button
        type="button"
        onClick={() => { void scope.rehydrate(); }}
        style={{
          border: "1px solid currentColor",
          padding: "5px 8px",
          background: "transparent",
          color: "inherit",
          cursor: "pointer",
          whiteSpace: "nowrap",
        }}
      >
        Aktiven Kartenstand laden
      </button>
    </div>
  );
}
