import * as Cesium from "cesium";
import {
  type Dispatch,
  type SetStateAction,
  useCallback,
} from "react";
import {
  type Selected,
} from "./InspectorPanel";
import {
  useTime,
} from "../../state/TimeContext";
import {
  EntityClickHandler,
} from "../globe/EntityClickHandler";
import {
  useSpatialScope,
} from "../../spatial/react";
import {
  useSpotlight,
} from "../globe/spotlight/SpotlightContext";
import {
  openSpatialChild,
} from "../../spatial/selection";
import {
  SearchPanel,
} from "./SearchPanel";
import {
  useSpotlightTrigger,
} from "../globe/hooks/useSpotlightTrigger";

interface EventClickBridgeProps {
  viewer: Cesium.Viewer | null;
  photorealTileset: Cesium.Cesium3DTileset | null;
  onCountrySelect: Dispatch<SetStateAction<Selected | null>>;
  onSelectEvent: (id: string) => void;
  onClearEvent: () => void;
}

function useEventClickCallback(onSelectEvent: (id: string) => void) {
  const { pause, seek } = useTime();
  return useCallback(
    (id: string, timeIso?: string) => {
      onSelectEvent(id);
      if (timeIso) {
        const t = Date.parse(timeIso);
        if (Number.isFinite(t)) {
          pause();
          seek(t);
        }
      }
    },
    [onSelectEvent, pause, seek],
  );
}

// The build-time migration switch mounts this legacy country capability or the
// Spatial capability below. Operational entity handling remains available in both.
export function LegacyEventClickBridge({
  viewer,
  photorealTileset,
  onCountrySelect,
  onSelectEvent,
  onClearEvent,
}: EventClickBridgeProps) {
  const handleEventSelect = useEventClickCallback(onSelectEvent);
  return (
    <EntityClickHandler
      viewer={viewer}
      photorealTileset={photorealTileset}
      countryInteraction={{
        mode: "legacy",
        onCountrySelect: (selection) => {
          onCountrySelect(selection);
          onClearEvent();
        },
      }}
      onEventSelect={handleEventSelect}
    />
  );
}

export function SpatialEventClickBridge({
  viewer,
  photorealTileset,
  onCountrySelect,
  onSelectEvent,
  onClearEvent,
}: EventClickBridgeProps) {
  const scope = useSpatialScope();
  const { dispatch: dispatchSpotlight } = useSpotlight();
  const handleEventSelect = useEventClickCallback(onSelectEvent);
  const handleSpatialChild = useCallback(
    async (target: Parameters<typeof scope.enter>[0]) => {
      const cause = scope.phase !== "hydrating" && scope.current.kind === "world"
        ? "country-click"
        : "child-click";
      await openSpatialChild(
        target,
        () => scope.enter(target, cause),
        (selection) => {
          onCountrySelect(selection === null
            ? null
            : { type: "spatial-country", data: selection });
          onClearEvent();
        },
        () => dispatchSpotlight({ type: "reset" }),
      );
    },
    [dispatchSpotlight, onClearEvent, onCountrySelect, scope],
  );

  return (
    <EntityClickHandler
      viewer={viewer}
      photorealTileset={photorealTileset}
      countryInteraction={{
        mode: "spatial",
        stateRevision: scope.stateRevision,
        onSpatialChild: handleSpatialChild,
        onSpatialPrefetch: (target, signal) => scope.prefetch(target, signal),
        onBlank: () => {
          onCountrySelect(null);
          onClearEvent();
        },
      }}
      onEventSelect={handleEventSelect}
    />
  );
}

// ── SearchAcceptHook ───────────────────────────────────────────────────────────
// Inner component that lives inside <SpotlightProvider> so it can call
// useSpotlight(). Mounts SearchPanel and wires onAccept → camera flyTo + Spotlight.

export function SearchAcceptHook({
  viewer,
  initialQuery,
}: {
  viewer: Cesium.Viewer | null;
  initialQuery: string;
}) {
  const { dispatch } = useSpotlight();
  return (
    <SearchPanel
      viewer={viewer}
      initialQuery={initialQuery}
      onAccept={(node) => {
        const lat = node.properties?.lat;
        const lon = node.properties?.lon;
        if (typeof lat !== "number" || typeof lon !== "number") return;
        viewer?.camera.flyTo({
          destination: Cesium.Cartesian3.fromDegrees(lon, lat, 400_000),
          duration: 1.6,
        });
        dispatch({
          type: "set",
          target: {
            kind: "circle",
            trigger: "search",
            center: { lon, lat },
            radius: 1,
            altitude: 400_000,
            label: node.name,
            ref: `§ ${node.type}`,
          },
        });
      }}
    />
  );
}

// ── ZoomTriggerHook ────────────────────────────────────────────────────────────
// Inner component that lives inside <SpotlightProvider> so it can call
// useSpotlightTrigger(). Handles camera zoom events and updates Spotlight state.

export function ZoomTriggerHook({ viewer }: { viewer: Cesium.Viewer | null }) {
  useSpotlightTrigger(viewer);
  return null;
}
