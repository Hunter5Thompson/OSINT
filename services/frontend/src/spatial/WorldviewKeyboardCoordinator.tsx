import { useEffect } from "react";

import { useSpotlight } from "../components/globe/spotlight/SpotlightContext";
import { WORLD_SCOPE_KEY } from "./contracts";
import { useOptionalSpatialScope } from "./react";

export interface WorldviewKeyboardCoordinatorProps {
  readonly hasTransientSelection: boolean;
  readonly clearTransientSelection: () => void;
}

export function WorldviewKeyboardCoordinator({
  hasTransientSelection,
  clearTransientSelection,
}: WorldviewKeyboardCoordinatorProps) {
  const { focusTarget, dispatch: dispatchSpotlight } = useSpotlight();
  const scope = useOptionalSpatialScope();

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented) return;
      if (hasTransientSelection) {
        event.preventDefault();
        clearTransientSelection();
        return;
      }
      if (focusTarget?.kind === "circle") {
        event.preventDefault();
        dispatchSpotlight({ type: "reset" });
        return;
      }
      if (scope?.phase === "resolving") {
        event.preventDefault();
        void scope.cancelPending();
        return;
      }
      if (
        scope !== null
        && scope.phase !== "hydrating"
        && scope.current.key !== WORLD_SCOPE_KEY
      ) {
        event.preventDefault();
        void scope.ascend("keyboard");
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [
    clearTransientSelection,
    dispatchSpotlight,
    focusTarget,
    hasTransientSelection,
    scope,
  ]);

  return null;
}
