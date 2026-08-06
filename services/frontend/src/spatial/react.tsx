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

const spatialScopeEnabledByDefault =
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
  const enabled = props.enabled ?? spatialScopeEnabledByDefault;
  if (!enabled) return <>{props.children}</>;
  if (props.navigation !== undefined) {
    return <InjectedSpatialScopeProvider {...props} navigation={props.navigation} />;
  }
  return <RouterBackedSpatialScopeProvider {...props} />;
}

function getStableHydratingSnapshot() {
  return HYDRATING_SPATIAL_SCOPE_SNAPSHOT;
}

export function useSpatialScope(): SpatialScopeHandle {
  const module = useContext(SpatialScopeContext);
  if (module === null) {
    throw new Error("useSpatialScope must be used inside <SpatialScopeProvider>");
  }
  const subscribe = useCallback(
    (listener: () => void) => module.subscribe(listener),
    [module],
  );
  const getSnapshot = useCallback(() => module.getSnapshot(), [module]);
  const snapshot = useSyncExternalStore(
    subscribe,
    getSnapshot,
    getStableHydratingSnapshot,
  );
  const enter = useCallback(
    (target: ScopeKey, cause: EnterCause) => module.dispatch({ type: "enter", target, cause }),
    [module],
  );
  const ascend = useCallback(
    (cause: "breadcrumb" | "keyboard") => module.dispatch({ type: "ascend", cause }),
    [module],
  );
  const prefetch = useCallback(
    (target: ScopeKey) => module.dispatch({ type: "prefetch", target, priority: "hover" }),
    [module],
  );
  const rehydrate = useCallback(
    () => module.dispatch({ type: "rehydrate" }),
    [module],
  );

  return useMemo<SpatialScopeHandle>(
    () => freezeSpatialValue({
      ...snapshot,
      enter,
      ascend,
      prefetch,
      rehydrate,
    }) as SpatialScopeHandle,
    [ascend, enter, prefetch, rehydrate, snapshot],
  );
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
