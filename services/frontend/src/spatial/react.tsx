import { useEffect, useRef } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import {
  RouterScopeNavigation,
  type RouterLocationSnapshot,
  type ScopeNavigationClock,
} from "./navigation";

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
