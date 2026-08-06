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
    navigation.acceptLocation(routerLocationSnapshot(
      location.pathname,
      location.search,
      location.hash,
      location.state as unknown,
    ));
  }, [location.hash, location.pathname, location.search, location.state, navigation]);

  return navigation;
}

const SpatialScopeContext = createContext<SpatialScopeModule | null>(null);
SpatialScopeContext.displayName = "SpatialScopeContext";

const spatialScopeEnabledByDefault =
  import.meta.env.VITE_SPATIAL_SCOPE_ENABLED === "true";

export type SpatialScopeModuleFactory = (
  options: CreateSpatialScopeControllerOptions,
) => OwnedSpatialScopeModule;

export interface SpatialScopeProviderProps {
  readonly children: ReactNode;
  readonly enabled?: boolean;
  readonly catalog?: SpatialCatalogPort;
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
  navigation,
  presentation,
  moduleFactory = createSpatialScopeController,
  onNavigationCleanup,
}: ModuleProviderProps) {
  const bootstrapCatalogRef = useRef<SpatialCatalogPort | null>(null);
  const selectedCatalog = catalog ?? (
    bootstrapCatalogRef.current ??= createBootstrapSpatialCatalog()
  );
  const moduleRef = useRef<OwnedSpatialScopeModule | null>(null);
  moduleRef.current ??= moduleFactory({
    catalog: selectedCatalog,
    navigation,
    presentation,
  });
  const module = moduleRef.current;

  useEffect(() => {
    module.start();
    return () => {
      module.stop();
      onNavigationCleanup?.();
    };
  }, [module, onNavigationCleanup]);

  return (
    <SpatialScopeContext.Provider value={module}>
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

  return useMemo<SpatialScopeHandle>(
    () => freezeSpatialValue({ ...snapshot, enter, ascend, prefetch }) as SpatialScopeHandle,
    [ascend, enter, prefetch, snapshot],
  );
}
